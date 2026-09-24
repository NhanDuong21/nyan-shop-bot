# Local catalog curation contract

`GET /api/v1/admin/catalog-curation` joins the current read-only supplier catalog
snapshot with one owner-authored, versioned Nyan Shop catalog document. `PUT` replaces
that local document using `expected_revision`; a stale revision returns `409`.

This is a localhost owner tool, not a supplier write API:

- `APP_ENV` and the configured bind host must be local/loopback.
- The actual client address must be loopback.
- `PUT` accepts JSON only from the exact Vite localhost origins.
- The service imports no order, payment, delivery, top-up, refund, or supplier-write port.
- `supplier_writes_enabled` is permanently `false` in the response.

Each canonical listing stores its Nyan-facing name, description, optional category,
visibility, deterministic sort order, optional integer-minor-unit VND retail price, and
one or more exact `{supplier, supplier_product_id}` references. An offer reference can
belong to only one listing. The service never groups products automatically by name or
price, and grouping does not approve a supplier purchase mapping.

Listings may remain hidden while their retail price is unset. A visible listing must
have a VND price. Empty listings, duplicate offer assignments, floats, unknown
currencies, duplicate sort orders, stale revisions, malformed keys, unknown fields,
and oversized documents fail closed.

The admin response includes supplier names and IDs only inside the private curation
workspace. The customer preview is built solely from canonical Nyan fields and must
not expose supplier provenance, source cost, credentials, or delivery data.
