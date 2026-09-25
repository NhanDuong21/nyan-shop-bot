# VietShare write conformance: offline gate

Source: official VietShare warehouse/reseller API documentation available to the owner
at `https://token.vietshare.site/docs`. This file records the implemented contract,
not permission to spend or enable a supplier write.

## Boundary

`VietShareOfflineWriteAdapter` exists only in the source-specific module and requires
an injected transport. The existing production HTTP transport still rejects POST;
the application never constructs or registers this adapter. The runtime remains
`SUPPLIER_MODE=mock`, `PAYMENT_MODE=disabled`, `ALLOW_REAL_PURCHASES=false`.

`SqliteWriteJournal` demonstrates durable ordering for offline conformance. Before
the first dispatch it commits an operation ID, a unique `Idempotency-Key`, and the
exact JSON bytes. A production implementation requires equivalent PostgreSQL
transactional ownership and explicit operational control; this SQLite journal is
not an authorization to connect a live transport.

## Contract and state

- POST `/v1/orders` signs `timestamp|nonce|POST|/v1/orders|sha256(raw_body)`.
  The raw body is sent unchanged after signing.
- Explicit retry or recovery reads the saved key and bytes. A new timestamp, nonce,
  and HMAC signature are made for every attempt; timestamp and nonce uniqueness is
  recorded durably across adapter restarts. A concurrent dispatch of the same
  operation is refused. A crash in `DISPATCHING` requires an operator to establish
  that the old dispatcher has stopped and mark it UNKNOWN before recovery.
- Timeout, transport failure, 5xx, and an invalid 200 schema stay UNKNOWN. HTTP 202
  and `REQUEST_IN_PROGRESS` stay IN_PROGRESS; their `Retry-After` deadline is
  measured from response receipt, persisted, and blocks early resubmission,
  including after restart. `REPLAYED_REQUEST`
  permits another attempt only with fresh auth and the saved commercial key/bytes.
  `IDEMPOTENCY_MISMATCH` is a terminal mismatch. Only a documented completed
  HTTP 200 envelope becomes COMPLETED. No response triggers an automatic POST retry.
- Completed order lookup uses signed GET `/v1/orders/{order_code}` and parses the
  same documented completed envelope. Unknown order codes are never guessed from
  an ambiguous POST; recovery in that case uses the saved key and exact bytes.
- Delivered account strings are returned through an explicit secret field; object
  representations, parse errors, and adapter logs do not render them. The journal
  stores the order code, not account material.
- `total_amount` has no separately documented unit for a USD wallet. The parser
  retains the integer as a supplier-reported value with currency explicitly
  unspecified; it must not be used as USD minor units for accounting.

## Still required before any live POST

Independent exact-HEAD CI and review; source-specific capped live test approval;
PostgreSQL journal integration; operator allowlist and kill switch; exact product,
quantity, integer spend cap and wallet currency; evidence and reconciliation plan.
Offline PASS does not enable VietShare or KhoMMO sales.
