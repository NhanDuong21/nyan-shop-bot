"""Fail-closed orchestration for the injected deterministic fake supplier."""

from __future__ import annotations

import asyncio

from nyan_shop_bot.catalog.models import (
    CatalogDetailFound,
    CatalogProduct,
    CatalogState,
    CatalogVariant,
)
from nyan_shop_bot.catalog.ports import CatalogReader
from nyan_shop_bot.orders.errors import (
    CatalogDetailRejected,
    CatalogNotFresh,
    CatalogReadRejected,
    CatalogSnapshotMismatch,
    InvalidOrderInput,
    MappingNotApproved,
    MoneyMismatch,
    OrderStateConflict,
    PriceCapExceeded,
    ProductUnavailable,
    QuantityUnavailable,
    SupplierCapabilityRejected,
    SupplierMappingMismatch,
    UnsafeOrderExecution,
    VariantUnavailable,
)
from nyan_shop_bot.orders.models import (
    CanonicalPurchasePayload,
    MinorMoney,
    OrderAggregate,
    OrderRequest,
    OrderSnapshot,
    PurchaseState,
    build_prepared_order,
)
from nyan_shop_bot.orders.ports import (
    DeliveryFailed,
    DeliveryRequest,
    DeliverySink,
    DeliverySucceeded,
    OrderRepository,
    PurchaseAccepted,
    PurchaseFailedSafe,
    PurchasePort,
    PurchaseSucceeded,
    ReconciliationFailedSafe,
    ReconciliationSucceeded,
    ReconciliationUnresolved,
    RuntimeSafetySettings,
    SupplierPurchaseRequest,
)

DELIVERY_CANCELLED = "DELIVERY_CANCELLED"
DELIVERY_FAILED = "DELIVERY_FAILED"
DELIVERY_SINK_ERROR = "DELIVERY_SINK_ERROR"


def assert_safe_execution(runtime: RuntimeSafetySettings) -> None:
    """Read only the three safety modes and reject missing, malformed, or unsafe values."""
    try:
        supplier_mode = runtime.supplier_mode
        payment_mode = runtime.payment_mode
        allow_real_purchases = runtime.allow_real_purchases
    except Exception:
        raise UnsafeOrderExecution from None
    safe = (
        type(supplier_mode) is str
        and supplier_mode == "mock"
        and type(payment_mode) is str
        and payment_mode == "disabled"
        and type(allow_real_purchases) is bool
        and not allow_real_purchases
    )
    if not safe:
        raise UnsafeOrderExecution


class OrderService:
    """Coordinates one durable fake obligation without exposing supplier internals."""

    def __init__(
        self,
        *,
        catalog: CatalogReader,
        repository: OrderRepository,
        supplier: PurchasePort,
        delivery_sink: DeliverySink,
        runtime: RuntimeSafetySettings,
    ) -> None:
        self._catalog = catalog
        self._repository = repository
        self._supplier = supplier
        self._delivery_sink = delivery_sink
        self._runtime = runtime

    async def place_order(
        self,
        *,
        customer_reference: str,
        request: OrderRequest,
    ) -> OrderSnapshot:
        """Validate fresh server authority, persist atomically, then claim once."""
        assert_safe_execution(self._runtime)
        _validate_customer_reference(customer_reference)
        self._require_purchase_capability()
        product, variant = await self._authoritative_selection(request)

        server_price = MinorMoney.from_catalog(variant.price)
        if (
            server_price.currency != request.max_unit_price.currency
            or server_price.unit != request.max_unit_price.unit
        ):
            raise MoneyMismatch
        if server_price.amount_minor > request.max_unit_price.amount_minor:
            raise PriceCapExceeded
        if variant.available_quantity < request.quantity:
            raise QuantityUnavailable

        mapping = variant.mapping
        if not mapping.is_approved:
            raise MappingNotApproved
        try:
            supplier_code = self._supplier.supplier_code
        except Exception:
            raise SupplierMappingMismatch from None
        if (
            mapping.supplier_product.supplier_id != supplier_code
            or mapping.supplier_variant.supplier_id != supplier_code
        ):
            raise SupplierMappingMismatch
        try:
            payload = CanonicalPurchasePayload(
                customer_reference=customer_reference,
                product_id=product.id,
                variant_id=variant.id,
                quantity=request.quantity,
                unit_price=server_price,
                max_unit_price=request.max_unit_price,
                supplier_code=supplier_code,
                supplier_product_id=mapping.supplier_product.supplier_product_id,
                supplier_variant_id=mapping.supplier_variant.supplier_variant_id,
            )
        except InvalidOrderInput:
            raise SupplierMappingMismatch from None

        candidate = build_prepared_order(
            customer_reference=customer_reference,
            request=request,
            payload=payload,
        )
        assert_safe_execution(self._runtime)
        prepared = await self._repository.prepare(candidate)
        if prepared.aggregate.intent.purchase_state is PurchaseState.PREPARED:
            aggregate = await self._dispatch_once(prepared.aggregate.intent.id)
        else:
            aggregate = prepared.aggregate
        return OrderSnapshot.from_aggregate(aggregate)

    async def recover(self, intent_id: str) -> OrderSnapshot:
        """Move crash-visible work through UNKNOWN and reconcile without repurchase."""
        assert_safe_execution(self._runtime)
        aggregate = await self._repository.get(intent_id)
        if aggregate.intent.purchase_state is PurchaseState.DISPATCHING:
            aggregate = await self._repository.record_unknown(intent_id)
        if aggregate.intent.purchase_state in (
            PurchaseState.SUCCEEDED,
            PurchaseState.FAILED_SAFE,
        ):
            return OrderSnapshot.from_aggregate(aggregate)
        if aggregate.intent.purchase_state not in (
            PurchaseState.UNKNOWN,
            PurchaseState.RECONCILING,
        ):
            raise OrderStateConflict

        started = await self._repository.begin_reconciliation(intent_id)
        if not started.should_reconcile:
            return OrderSnapshot.from_aggregate(started.aggregate)
        if not self._reconciliation_supported():
            return OrderSnapshot.from_aggregate(started.aggregate)
        self._require_matching_persisted_supplier(started.aggregate)
        assert_safe_execution(self._runtime)
        request = _supplier_request(started.aggregate)
        try:
            result = await self._supplier.reconcile(request)
        except asyncio.CancelledError:
            raise
        except Exception:
            return OrderSnapshot.from_aggregate(started.aggregate)

        if isinstance(result, ReconciliationSucceeded):
            aggregate = await self._repository.record_success(
                intent_id,
                result.supplier_reference,
            )
        elif isinstance(result, ReconciliationFailedSafe):
            aggregate = await self._repository.record_safe_failure(
                intent_id,
                result.failure_code,
            )
        elif isinstance(result, ReconciliationUnresolved):
            aggregate = started.aggregate
        else:
            aggregate = started.aggregate
        return OrderSnapshot.from_aggregate(aggregate)

    async def deliver(self, intent_id: str) -> OrderSnapshot:
        """Persist one independent notification attempt and never touch purchase."""
        assert_safe_execution(self._runtime)
        attempt = await self._repository.create_delivery_attempt(intent_id)
        request = DeliveryRequest(
            order_intent_id=intent_id,
            attempt_number=attempt.attempt_number,
            delivery_key=attempt.delivery_key,
        )
        assert_safe_execution(self._runtime)
        try:
            result = await self._delivery_sink.deliver(request)
        except asyncio.CancelledError:
            await self._repository.finish_delivery(
                attempt.id,
                succeeded=False,
                failure_code=DELIVERY_CANCELLED,
            )
            raise
        except Exception:
            await self._repository.finish_delivery(
                attempt.id,
                succeeded=False,
                failure_code=DELIVERY_SINK_ERROR,
            )
        else:
            if isinstance(result, DeliverySucceeded):
                await self._repository.finish_delivery(
                    attempt.id,
                    succeeded=True,
                    failure_code=None,
                )
            elif isinstance(result, DeliveryFailed):
                await self._repository.finish_delivery(
                    attempt.id,
                    succeeded=False,
                    failure_code=DELIVERY_FAILED,
                )
            else:
                await self._repository.finish_delivery(
                    attempt.id,
                    succeeded=False,
                    failure_code=DELIVERY_SINK_ERROR,
                )
        aggregate = await self._repository.get(intent_id)
        return OrderSnapshot.from_aggregate(aggregate)

    async def get_order(self, intent_id: str) -> OrderSnapshot:
        assert_safe_execution(self._runtime)
        return OrderSnapshot.from_aggregate(await self._repository.get(intent_id))

    async def _dispatch_once(self, intent_id: str) -> OrderAggregate:
        assert_safe_execution(self._runtime)
        self._require_purchase_capability()
        claimed = await self._repository.claim_prepared(intent_id)
        if claimed is None:
            return await self._repository.get(intent_id)
        self._require_matching_persisted_supplier(claimed)
        assert_safe_execution(self._runtime)
        request = _supplier_request(claimed)
        try:
            result = await self._supplier.purchase(request)
        except asyncio.CancelledError:
            await self._repository.record_unknown(intent_id)
            raise
        except Exception:
            return await self._repository.record_unknown(intent_id)

        if isinstance(result, PurchaseSucceeded):
            return await self._repository.record_success(
                intent_id,
                result.supplier_reference,
            )
        if isinstance(result, PurchaseFailedSafe):
            return await self._repository.record_safe_failure(
                intent_id,
                result.failure_code,
            )
        if isinstance(result, PurchaseAccepted):
            return await self._repository.record_unknown(intent_id)
        return await self._repository.record_unknown(intent_id)

    async def _authoritative_selection(
        self,
        request: OrderRequest,
    ) -> tuple[CatalogProduct, CatalogVariant]:
        try:
            response = await self._catalog.read_catalog()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise CatalogReadRejected from None
        if response.state is not CatalogState.FRESH:
            raise CatalogNotFresh
        product = next((item for item in response.items if item.id == request.product_id), None)
        if product is None:
            raise ProductUnavailable
        variant = next(
            (item for item in product.variants if item.id == request.variant_id),
            None,
        )
        if variant is None:
            raise VariantUnavailable
        try:
            detail = await self._catalog.get_product(request.product_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise CatalogDetailRejected from None
        if not isinstance(detail, CatalogDetailFound):
            raise CatalogDetailRejected
        if detail.item != product:
            raise CatalogSnapshotMismatch
        detail_variant = next(
            (item for item in detail.item.variants if item.id == request.variant_id),
            None,
        )
        if detail_variant is None:
            raise CatalogSnapshotMismatch
        return detail.item, detail_variant

    def _require_purchase_capability(self) -> None:
        try:
            capabilities = self._supplier.capabilities
        except Exception:
            raise SupplierCapabilityRejected from None
        if type(capabilities.idempotent_purchase) is not bool:
            raise SupplierCapabilityRejected
        if not capabilities.idempotent_purchase:
            raise SupplierCapabilityRejected
        if type(capabilities.reconciliation) is not bool:
            raise SupplierCapabilityRejected

    def _reconciliation_supported(self) -> bool:
        try:
            capabilities = self._supplier.capabilities
        except Exception:
            raise SupplierCapabilityRejected from None
        if type(capabilities.reconciliation) is not bool:
            raise SupplierCapabilityRejected
        return capabilities.reconciliation

    def _require_matching_persisted_supplier(self, aggregate: OrderAggregate) -> None:
        try:
            supplier_code = self._supplier.supplier_code
        except Exception:
            raise SupplierMappingMismatch from None
        payload = aggregate.supplier_attempt.request_payload
        if (
            aggregate.supplier_attempt.supplier_code != supplier_code
            or payload.supplier_code != supplier_code
        ):
            raise SupplierMappingMismatch


def _supplier_request(aggregate: OrderAggregate) -> SupplierPurchaseRequest:
    return SupplierPurchaseRequest(
        request_key=aggregate.supplier_attempt.request_key,
        payload=aggregate.supplier_attempt.request_payload,
    )


def _validate_customer_reference(value: object) -> str:
    if type(value) is not str or not value or len(value) > 128:
        raise InvalidOrderInput
    if value != value.strip() or not value.isprintable():
        raise InvalidOrderInput
    return value
