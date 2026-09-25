# VietShare PostgreSQL write gate: offline preflight

Issue #70 implements the local gate required by Issue #68. It does not authorize
or perform a supplier POST. The application runtime does not import
`VietSharePgOfflineExecutor`, and the only exercised transport is an injected fake.
`SUPPLIER_MODE=mock`, `PAYMENT_MODE=disabled`, and
`ALLOW_REAL_PURCHASES=false` remain required.

## Durable boundary

Migration `20260925_0004` creates a singleton gate control row, a write journal,
and signing attempt reservations. The control row is seeded `enabled=false` with
an empty operator allowlist. The database refuses an incomplete arm. The
approved test ID, product ID, quantity, integer VND max unit price, integer VND
absolute spend cap, wallet ID, and allowed operator must all match the prepared
journal row before a dispatch claim commits.

`prepare` commits the exact UTF-8 JSON bytes and their SHA-256, idempotency key,
source, product, quantity, spend bounds, VND wallet, operator identity, and
`PREPARED` state before any outbound work. Uniqueness covers test ID and
idempotency key. A partial unique index also permits only one unresolved
VietShare dispatch across local tests. The body and commercial identity fields
cannot be updated. Repeating `prepare` accepts only the same test, key, body,
and commercial fields.

`claim` locks the singleton control and journal row in one PostgreSQL
transaction. It reserves the attempt timestamp and nonce, records
`DISPATCHING`, and commits before the injected transport sees a request. The
request signs the journal's unchanged raw bytes and reuses its key. A recovery
attempt must use a new timestamp and nonce; the signature therefore changes.
Concurrent claims leave at most one dispatch. A crash in `DISPATCHING` does not
cause an automatic retry.

## Uncertain outcomes

| Observation | Persisted state | Effect |
| --- | --- | --- |
| Documented completed HTTP 200 within cap | `SUCCEEDED` | Store order code only; discard account material. |
| HTTP 202 or `REQUEST_IN_PROGRESS` | `RECONCILING` | Persist `Retry-After`, disarm gate, freeze new keys. |
| Timeout, transport loss, 502, or malformed response | `UNKNOWN` | Disarm gate, freeze new keys; investigate before recovery. |
| `IDEMPOTENCY_MISMATCH` | `RECONCILING` | Disarm gate; never dispatch this key automatically again. |
| Supplier total exceeds absolute cap | `RECONCILING` | Keep order code for investigation; never call it successful or failed. |
| Verified absence of commercial obligation | `FAILED_SAFE` | Reserved terminal state; this offline module cannot assert the evidence. |

Recovery from `UNKNOWN` must be explicitly moved to `RECONCILING`. A new
dispatch then requires the control row to be deliberately rearmed for the same
test. The old key and byte-identical body are mandatory. New-key dispatch
remains blocked while any VietShare test is `DISPATCHING`, `UNKNOWN`, or
`RECONCILING`. Reaching `SUCCEEDED` does not arm another test.

## Remaining gate before capped live test

Issue #68 remains blocked. The owner must approve an exact VietShare product ID,
quantity, max unit price in integer VND, absolute total cap in integer VND, VND
wallet, and exact allowed operator. An authenticated operator identity binding,
controlled arming procedure, and real transport wiring are deliberately absent
from this offline task. They require a separate reviewed change and explicit
approval before any real POST. No top-up, Telegram Stars, staging, or production
deployment is part of this gate.
