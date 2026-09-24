"""Authenticated loopback-only HTTP adapter for synthetic checkout."""

from __future__ import annotations

import hashlib
import hmac
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from nyan_shop_bot.catalog.mock import FakeCatalogReader
from nyan_shop_bot.catalog.models import CatalogProduct, Money
from nyan_shop_bot.config import Settings, is_loopback_host
from nyan_shop_bot.orders.errors import OrderError
from nyan_shop_bot.orders.fakes import (
    FakeDeliverySink,
    FakePurchaseOutcome,
    FakeReconciliationOutcome,
    FakeSupplierPort,
)
from nyan_shop_bot.orders.models import MinorMoney, OrderRequest, OrderSnapshot
from nyan_shop_bot.orders.ports import OrderRepository
from nyan_shop_bot.orders.service import OrderService

_ALLOWED_ORIGINS = frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})


class MockScenario(StrEnum):
    SUCCESS = "success"
    FAILED_SAFE = "failed_safe"
    UNKNOWN = "unknown"


class MockEvidence(StrEnum):
    UNRESOLVED = "unresolved"
    CONFIRMED_SUCCESS = "confirmed_success"
    CONFIRMED_OUT_OF_STOCK = "confirmed_out_of_stock"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MockCheckoutRequest(StrictModel):
    product_id: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    variant_id: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    quantity: Annotated[StrictInt, Field(ge=1, le=100)]
    idempotency_key: Annotated[
        StrictStr, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ]
    max_unit_price: Money
    scenario: MockScenario


class MockReconciliationRequest(StrictModel):
    evidence: MockEvidence


class MockCatalogItem(StrictModel):
    id: str
    name: str
    description: str
    variants: tuple[MockCatalogVariant, ...]


class MockCatalogVariant(StrictModel):
    id: str
    name: str
    price: Money
    available_quantity: int


class MockCatalogResponse(StrictModel):
    mode: str = "MOCK"
    payment_mode: str = "disabled"
    items: tuple[MockCatalogItem, ...]


class MockOrderResponse(StrictModel):
    intent_id: str
    product_id: str
    variant_id: str
    quantity: int
    unit_price: Money
    max_unit_price: Money
    total_price: Money
    purchase_state: str
    failure_code: str | None


def _public_order(snapshot: OrderSnapshot) -> MockOrderResponse:
    unit = snapshot.unit_price
    return MockOrderResponse(
        intent_id=snapshot.intent_id,
        product_id=snapshot.product_id,
        variant_id=snapshot.variant_id,
        quantity=snapshot.quantity,
        unit_price=Money(amount_minor=unit.amount_minor, currency=unit.currency, unit="minor"),
        max_unit_price=Money(
            amount_minor=snapshot.max_unit_price.amount_minor,
            currency=snapshot.max_unit_price.currency,
            unit="minor",
        ),
        total_price=Money(
            amount_minor=unit.amount_minor * snapshot.quantity,
            currency=unit.currency,
            unit="minor",
        ),
        purchase_state=snapshot.purchase_state.value,
        failure_code=None if snapshot.failure_code is None else snapshot.failure_code.value,
    )


def _public_product(product: CatalogProduct) -> MockCatalogItem:
    return MockCatalogItem(
        id=product.id,
        name=product.name,
        description=product.description,
        variants=tuple(
            MockCatalogVariant(
                id=item.id,
                name=item.name,
                price=item.price,
                available_quantity=item.available_quantity,
            )
            for item in product.variants
        ),
    )


def create_mock_order_service(
    settings: Settings,
    repository: OrderRepository,
    *,
    purchase: FakePurchaseOutcome = FakePurchaseOutcome.SUCCESS,
    reconciliation: FakeReconciliationOutcome = FakeReconciliationOutcome.UNRESOLVED,
) -> OrderService:
    return OrderService(
        catalog=FakeCatalogReader(),
        repository=repository,
        supplier=FakeSupplierPort(purchase_outcome=purchase, reconciliation_outcome=reconciliation),
        delivery_sink=FakeDeliverySink(),
        runtime=settings,
    )


def build_mock_checkout_router(
    *, settings: Settings, repository: OrderRepository | None
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/mock-checkout", tags=["mock-checkout"])

    async def require_access(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        client = request.client
        configured = settings.mock_checkout_access_token
        safe_profile = (
            settings.app_env in {"local", "test"}
            and is_loopback_host(settings.app_host)
            and settings.supplier_mode == "mock"
            and settings.payment_mode == "disabled"
            and settings.allow_real_purchases is False
        )
        if not safe_profile or client is None or not is_loopback_host(client.host):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="mock checkout disabled"
            )
        if repository is None or configured is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="mock checkout unavailable"
            )
        expected = configured.get_secret_value()
        provided = authorization.removeprefix("Bearer ") if authorization else ""
        if (
            not authorization
            or not authorization.startswith("Bearer ")
            or len(expected) < 32
            or not hmac.compare_digest(provided, expected)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="demo access required"
            )
        origin = request.headers.get("origin")
        if origin is not None and origin not in _ALLOWED_ORIGINS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="invalid local origin"
            )

    access = [Depends(require_access)]

    @router.get("/catalog", response_model=MockCatalogResponse, dependencies=access)
    async def catalog() -> MockCatalogResponse:
        response = await FakeCatalogReader().read_catalog()
        return MockCatalogResponse(items=tuple(_public_product(item) for item in response.items))

    @router.get("/orders", response_model=tuple[MockOrderResponse, ...], dependencies=access)
    async def history() -> tuple[MockOrderResponse, ...]:
        assert repository is not None
        snapshots = await create_mock_order_service(settings, repository).list_recent()
        return tuple(_public_order(item) for item in snapshots)

    @router.post("/orders", response_model=MockOrderResponse, dependencies=access)
    async def checkout(body: MockCheckoutRequest) -> MockOrderResponse:
        assert repository is not None
        outcome = {
            MockScenario.SUCCESS: FakePurchaseOutcome.SUCCESS,
            MockScenario.FAILED_SAFE: FakePurchaseOutcome.OUT_OF_STOCK,
            MockScenario.UNKNOWN: FakePurchaseOutcome.ACCEPTED,
        }[body.scenario]
        key = hashlib.sha256(f"admin:{body.idempotency_key}".encode("ascii")).hexdigest()
        try:
            snapshot = await create_mock_order_service(
                settings, repository, purchase=outcome
            ).place_order(
                customer_reference="local-demo-operator",
                request=OrderRequest(
                    product_id=body.product_id,
                    variant_id=body.variant_id,
                    quantity=body.quantity,
                    idempotency_key=key,
                    max_unit_price=MinorMoney.from_catalog(body.max_unit_price),
                ),
            )
        except OrderError as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        return _public_order(snapshot)

    @router.get("/orders/{intent_id}", response_model=MockOrderResponse, dependencies=access)
    async def order_detail(intent_id: str) -> MockOrderResponse:
        assert repository is not None
        try:
            return _public_order(
                await create_mock_order_service(settings, repository).get_order(intent_id)
            )
        except OrderError as exc:
            raise HTTPException(status_code=404, detail=exc.code) from exc

    @router.post(
        "/orders/{intent_id}/reconcile", response_model=MockOrderResponse, dependencies=access
    )
    async def reconcile(intent_id: str, body: MockReconciliationRequest) -> MockOrderResponse:
        assert repository is not None
        evidence = FakeReconciliationOutcome(body.evidence.value)
        try:
            snapshot = await create_mock_order_service(
                settings, repository, reconciliation=evidence
            ).recover(intent_id)
        except OrderError as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        return _public_order(snapshot)

    return router
