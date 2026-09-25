# VietShare product 28 capped test runtime: dormant preflight

Issue #72 implements a separate local test path for the owner-selected VietShare
partner catalog product ID `28`. This code is not imported by FastAPI, Telegram,
or admin. It has not performed a supplier POST or spent wallet funds. Issue #68
remains blocked until the owner approves the complete final tuple and a distinct
execution decision. PR #64 remains a draft readiness record.

## Boundaries

- `SUPPLIER_MODE=mock`, `PAYMENT_MODE=disabled`, and
  `ALLOW_REAL_PURCHASES=false` remain mandatory. Runtime sales stay disabled.
- The separate `VIETSHARE_CAPPED_TEST_ENABLED` switch defaults to `false`.
  The PostgreSQL gate also defaults `enabled=false`. Both must be enabled for
  this local capped path to dispatch.
- The only outbound write target in this path is
  `https://token.vietshare.site/v1/orders`, using fixed-host TLS without ambient
  proxies or redirects. The regular VietShare catalog transport remains GET-only.
- Product ID is fixed at `28`; quantity is fixed at `1`; wallet currency is VND;
  and the code imposes an additional 100,000 VND hard ceiling. The owner's
  approved absolute cap may be lower. No `supplier_emails`, `coupon_code`,
  `flash_sale_id`, or other optional field can enter the persisted body.
- On the first dispatch only, a read-only product detail must still have stock,
  a VND price at or below the approved maximum, no Flash Sale ID, and no
  description hint requiring an additional field. A changed description without
  a machine-readable requirement remains a human preflight concern.
- The configured operator ID is the actual local process token SID on Windows
  or effective UID on POSIX. No API/CLI request may supply a different identity.

## Durable dispatch and recovery

`prepare` commits one random Idempotency-Key and exact request bytes to the
PostgreSQL journal. `arm` locks the gate and journal in one transaction and
compares the exact test ID, product ID, quantity, max unit VND price, absolute
VND cap, wallet ID, and authenticated operator ID. It requires an owner approval
reference; the CLI cannot independently authenticate the owner decision. The
operator must preserve the actual owner decision as external evidence. An
approval reference alone never authorizes a real POST.
Approval and investigation references use only `sha256:` followed by 64 lowercase
hex digits, so raw messages, credentials, or delivered material cannot enter
the journal through those fields.

`dispatch` claims the prepared journal row before sending. Recovery uses only
the original key and byte-identical body, with a fresh timestamp, nonce, and
signature. Timeout or transport loss becomes `UNKNOWN`. HTTP 202 and
`REQUEST_IN_PROGRESS` become `RECONCILING` with the supplier's `Retry-After`.
The gate disarms after each attempt. An operator must investigate, deliberately
mark `UNKNOWN` as `RECONCILING` where appropriate, and rearm the same tuple
before another attempt. `IDEMPOTENCY_MISMATCH` and cap exceedance remain frozen.
An unresolved test prevents any new-key dispatch.
After this capped test succeeds, this implementation also refuses a different
test ID; another live test requires a separately reviewed change.

If a process crashes in `DISPATCHING`, the operator must first establish that
the old dispatcher has stopped and retain an evidence reference. Only then may
`mark-dispatch-lost` record `UNKNOWN` and an immutable recovery event. A separate
investigation reference is required for `mark-reconciling`. Neither command
sends a supplier request or creates a new key. The application cannot prove an
external supplier obligation absent after a lost response.

## Secret fulfillment

On a documented HTTP 200 completion, account material is encrypted with a
locally supplied Fernet key and committed to the separate
`vietshare_secret_deliveries` table before the journal may become `SUCCEEDED`.
The journal retains only a random delivery reference and supplier order code.
If storage fails, the test remains `RECONCILING` with no success claim or new-key
POST. An over-cap completion also preserves the encrypted material and remains
`RECONCILING`. Only the journal's authenticated operator may read the material
through the in-process store API. Explicit acknowledgement removes ciphertext;
reads are denied after 24 hours. The operator must run the local purge command
to physically remove expired ciphertext, and should acknowledge delivery to
remove it sooner. Never print delivery data
to a terminal, log, PR, CI artifact, or browser.

## Later owner-approved local procedure

Use an ignored local environment file, separate from the live-read catalog
configuration. It must contain the local PostgreSQL URL, existing VietShare API
credentials, a locally generated Fernet delivery key, the safe runtime defaults
above, and `VIETSHARE_CAPPED_TEST_ENABLED=false` until the final approval step.
Never pass credentials or encryption keys as command arguments or commit them.
The required names are `APP_ENV`, `APP_HOST`, `SUPPLIER_MODE`, `PAYMENT_MODE`,
`ALLOW_REAL_PURCHASES`, `DATABASE_URL`, `VIETSHARE_API_ID`,
`VIETSHARE_API_SECRET`, `VIETSHARE_DELIVERY_KEY`, and
`VIETSHARE_CAPPED_TEST_ENABLED`. The local database name must be
`nyan_shop_bot`; the database host must be loopback. No value is supplied by
this document.
The plan is an ignored local JSON file with exactly these keys:

```json
{
  "test_id": "owner-approved-test-id",
  "product_id": 28,
  "quantity": 1,
  "max_unit_price_vnd": 0,
  "absolute_spend_cap_vnd": 0,
  "wallet_id": "owner-approved-vnd-wallet",
  "operator_id": "local-operator-token-id"
}
```

The zero placeholders are deliberately invalid. The exact positive integer
values, wallet ID, operator ID, approval reference, and test ID still require
the owner's separate decision. `python scripts/vietshare_capped_test.py identity`
prints only the current OS operator
ID. `prepare` can persist the approved plan while the kill switch is OFF.
`arm` and `dispatch` must remain uninvoked until the later execution approval.
`disarm` is always available and requires no supplier credential. No command
in this runbook has been used for a real POST.

Offline tests use only fake/in-memory supplier transports and a disposable local
PostgreSQL database. Their PASS is technical evidence, not a live supplier test.
