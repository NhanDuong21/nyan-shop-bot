# KhoMMO order write contract: offline gate

Source inspected 2026-09-25: official [KhoMMO Partner API documentation](https://api.khommo.vn/docs/partner)
and the owner's local excerpt. The official page documents Bearer auth,
`POST /api/partner/v1/orders` with `productId`, positive `quantity`, and
`paymentMode` (`CREDIT` or `VND`), plus `GET /orders/:orderNo` for an order
belonging to the authenticated account. It lists recent orders via GET but
does not define a deterministic client-reference lookup.

## Offline model

`KhoMmoOfflineOrderAdapter` requires an injected transport; the existing
production HTTP transport still rejects POST and order-status GET. The local
SQLite journal commits an operation and exact body before at most one fake
POST dispatch. Once dispatch starts, timeout, connection loss, 502, any other
HTTP response, and process restart remain `UNKNOWN_RECONCILING`; the adapter
never sends a second POST for that operation. A 2xx is not called delivered
because the official page does not define the create response schema.

Known-number GET status is modeled, but its response body is not projected:
the documentation does not define status/delivery fields. The opaque body may
contain account material and is never returned, logged, or put in repr/errors.
The adapter does not infer an order number from an undocumented response or
try a list search to match a lost-response order.

## Live automation gate: BLOCKED

The inspected documentation establishes none of these: an idempotency key,
a client reference accepted during create and deterministically queryable
later, or another documented deterministic lookup for a lost-response order.
`GET /orders/:orderNo` cannot recover a lost response if its `orderNo` is
unknown. Recent-first `GET /orders` with pagination is not a safe identity
match when other orders may exist. The 502 description combines unavailable
and failed outcomes and mentions refund flow without a transaction guarantee.

**LIVE AUTOMATION BLOCKED** until KhoMMO supplies a documented safe
lost-response reconciliation method and complete order/status/delivery
schemas. Do not use a second POST for reconciliation, and do not perform a
capped live KhoMMO POST on this evidence. Offline conformance is not a live
supplier test. Runtime writes, payments, and real purchases remain disabled.
