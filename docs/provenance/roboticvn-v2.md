# Roboticvn v2 sanitized provenance

This note records only the facts needed to bound the read adapter. It does not reproduce the
partner document, OpenAPI schemas, examples, credentials, delivery data, or response content.

## Source checks

- Nyan's locally pasted Swagger snapshot had SHA-256
  `09be6d7dd099c57115ecd611d67bc0a28b0dcb12634b7435051d98e20db0cc9f`.
- A credential-free `GET` of
  `https://api.roboticvn.com/api/v2/docs/openapi.json` at `2026-09-21T03:05:06Z`
  returned HTTP `200`, content type `application/json`, and `19,482` raw bytes. The raw-byte
  SHA-256 was
  `22de68f114b6c30e68cc88ded579bf4b77632f43bc67fe9c74bbe60f8cdb1930`.
- That public document identified OpenAPI `3.0.3`, title `Roboticvn Customer API`, and API
  version `2.2.0`.

The documented production origin is `https://api.roboticvn.com`; data paths use `/api/v2`.
Authentication is the global `x-api-key` header. No key value is recorded here.

## Enabled boundary and unresolved gaps

The adapter can construct only these authenticated reads:

- `GET /api/v2/products`
- `GET /api/v2/products/{id}`
- `GET /api/v2/wallet/balance`
- `GET /api/v2/wallet/transactions`

The account endpoint is outside Issue #5's product, variant, and wallet scope. Quote, order,
order-history/detail, payment-status, purchase, payment, top-up, refund, and delivery operations
are not implemented. Sensitive delivery remains a separate disabled endpoint.

Variant prices, wallet balances, and transaction amounts are documented only as numbers; their
precision, scale, and major-versus-minor unit are not defined. They therefore produce an explicit
unsupported monetary projection and are never converted to shared Money using an assumed VND or
USD exponent. The document gives no Retry-After contract, retry interval, or retry guarantee, so
the adapter does not retry or sleep automatically.

## Request-body audit delta

The pasted Swagger rendered blank request-body schema sections for the quote, order, and top-up
writes. The checked public document instead marks those bodies required and references
`ProductQuoteRequest`, `CreateOrderRequest`, and `TopupRequest`, respectively. This difference
does not authorize a write and does not establish idempotency, uncertain-outcome reconciliation,
supplier-obligation handling, settlement, or delivery-credential safety. Purchase, payment,
top-up, refund, and delivery capabilities remain disabled.
