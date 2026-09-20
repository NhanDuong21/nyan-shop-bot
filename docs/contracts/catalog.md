# Catalog contract

The FastAPI application and Pydantic models are the contract source of truth. The checked-in
artifacts are generated outputs:

- `generated/openapi.json` is the UI client-generator input from `FastAPI.openapi()`.
- `generated/catalog-ui-fixtures.json` contains validated `fresh`, `stale`, `empty`, and
  `error` responses for UI development and tests.

Regenerate both from the repository root with:

```text
PYTHONPATH=src python -m nyan_shop_bot.catalog.generate
```

In PowerShell, set `$env:PYTHONPATH = "src"` before the same Python module command. Contract
tests fail when either tracked artifact differs from code generation.

## Identity and mapping

A normalized catalog product owns normalized variants. Every variant mapping retains two opaque,
separate supplier identities: `supplier_product_id` and `supplier_variant_id`, each namespaced
by `supplier_id`. Display names do not participate in lookup or mapping.

A mapping is active only when its discriminated approval record has status `approved`, an
explicit `approved_by_admin_id`, and an aware `approved_at` timestamp. A `pending` record has
no implicit approval evidence.

## Money and state

Money always carries `amount_minor` as a strict non-negative integer, a three-letter uppercase
`currency`, and the explicit unit `minor`. Adding different currencies or units is rejected.

Catalog responses are internally validated:

- `fresh` has current items and fresh timestamp evidence.
- `stale` has cached items, stale timestamp evidence, and a safe refresh error.
- `empty` is a successful fresh read with no items.
- `error` has no items or claimed freshness and carries a client-safe error.

## Capability boundary

Catalog list and verified detail reads are read-only. A supplier without a verified detail schema
uses the explicit `unsupported` capability/result; it does not invent fields and does not block
catalog listing. Purchase, payment, top-up, refund, and delivery capabilities are structurally
required to remain `disabled`. No corresponding write routes or fake-supplier methods exist.
