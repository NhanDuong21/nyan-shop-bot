# Supplier provenance and Phase 0 boundary

Reference snapshot date: 2026-09-19. Nyan supplied local snapshots/excerpts from [KhoMMO partner docs](https://api.khommo.vn/docs/partner), [VietShare Warehouse API](https://token.vietshare.site/docs), and [Roboticvn OpenAPI](https://api.roboticvn.com/api/v2/docs/openapi.json). No API key or real transaction was used. These links do not establish supplier reliability or permission to distribute a product.

Private partner inputs remain in ignored `nyan-bootstrap/` and are not reproduced here. The repository stores only these minimal conclusions:

- KhoMMO uses Bearer auth and describes CREDIT/VND wallets, but the supplied excerpt does not establish complete response schemas, idempotency, price ceilings, or timeout/refund outcomes. CREDIT must not be interpreted as postpaid.
- VietShare signs exact raw bytes plus method and ordered `/v1` path/query. Its order endpoint spends wallet balance; timeout/202 is uncertain, retry must retain idempotency identity/payload, and delivered accounts are sensitive. The supplied executable POST examples were not run or copied.
- Roboticvn separates product/variant, quote, order, wallet, and delivery endpoints. The supplied Swagger snapshot omitted write request-body schemas and showed a wallet/bank-transfer inconsistency. Do not guess or enable quote/order/top-up.

NSB-001 therefore exposes only a `CatalogReader` boundary backed by `MockCatalogReader`. Purchase, top-up, refund, and delivery capabilities are false and no corresponding routes or adapter methods exist. Missing supplier schema blocks only that operation, not mock foundation work.

Future adapters must keep per-supplier semantics rather than forcing a pretend-common retry model. Live readiness requires owner approval, credentials outside CI, product-distribution review, explicit currency units, persisted request identity before outbound calls, database uniqueness/transactions, and UNKNOWN/RECONCILING handling for uncertain outcomes.
