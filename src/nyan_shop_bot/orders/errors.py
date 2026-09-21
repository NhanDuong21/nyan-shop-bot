"""Typed, client-safe failures for mock order orchestration."""

from __future__ import annotations


class OrderError(Exception):
    """Base error whose text never includes caller or supplier-controlled data."""

    code = "order_error"
    safe_message = "The mock order operation could not be completed safely."

    def __init__(self) -> None:
        super().__init__(self.safe_message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class InvalidOrderInput(OrderError, ValueError):
    code = "invalid_order_input"
    safe_message = "The order request is invalid."


class UnsafeOrderExecution(OrderError):
    code = "unsafe_order_execution"
    safe_message = "Order execution is disabled outside the safe mock configuration."


class CatalogReadRejected(OrderError):
    code = "catalog_read_rejected"
    safe_message = "The current catalog could not be established safely."


class CatalogNotFresh(OrderError):
    code = "catalog_not_fresh"
    safe_message = "A fresh catalog is required before creating an order."


class ProductUnavailable(OrderError):
    code = "product_unavailable"
    safe_message = "The requested product is not available in the current catalog."


class VariantUnavailable(OrderError):
    code = "variant_unavailable"
    safe_message = "The requested variant is not available in the current catalog."


class CatalogDetailRejected(OrderError):
    code = "catalog_detail_rejected"
    safe_message = "Authoritative product detail is unavailable."


class CatalogSnapshotMismatch(OrderError):
    code = "catalog_snapshot_mismatch"
    safe_message = "Catalog listing and detail snapshots do not match."


class MappingNotApproved(OrderError):
    code = "mapping_not_approved"
    safe_message = "The selected supplier mapping is not approved."


class SupplierMappingMismatch(OrderError):
    code = "supplier_mapping_mismatch"
    safe_message = "The selected mapping does not match the configured mock supplier."


class SupplierCapabilityRejected(OrderError):
    code = "supplier_capability_rejected"
    safe_message = "The mock supplier lacks a required safety capability."


class MoneyMismatch(OrderError):
    code = "money_mismatch"
    safe_message = "The price cap currency and unit must match the current server price."


class PriceCapExceeded(OrderError):
    code = "price_cap_exceeded"
    safe_message = "The current server price exceeds the accepted unit-price cap."


class QuantityUnavailable(OrderError):
    code = "quantity_unavailable"
    safe_message = "The requested quantity is not currently available."


class IdempotencyConflict(OrderError):
    code = "idempotency_conflict"
    safe_message = "The idempotency key is already bound to a different request."


class OrderNotFound(OrderError):
    code = "order_not_found"
    safe_message = "The mock order was not found."


class OrderStateConflict(OrderError):
    code = "order_state_conflict"
    safe_message = "The mock order is not in a state that permits this operation."


class PersistenceInvariantError(OrderError):
    code = "persistence_invariant_error"
    safe_message = "Stored mock order state failed a safety invariant."


class DeliveryNotAllowed(OrderError):
    code = "delivery_not_allowed"
    safe_message = "Delivery can start only after a confirmed purchase success."


class AmbiguousPurchaseError(Exception):
    """Synthetic exception indicating that non-acceptance cannot be proven."""

    def __init__(self) -> None:
        super().__init__("The fake purchase outcome is intentionally ambiguous.")

    def __repr__(self) -> str:
        return "AmbiguousPurchaseError()"
