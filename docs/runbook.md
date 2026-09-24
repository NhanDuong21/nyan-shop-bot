# Local runbook

## PowerShell

```powershell
$env:NYAN_DOCKER_CONTEXT = "desktop-linux" # only if DOCKER_HOST overrides Docker Desktop
python scripts/task.py setup
python scripts/task.py verify
python scripts/task.py dev
```

Use another terminal for `dev`. Stop without deleting data:

```powershell
python scripts/task.py stop
```

Delete only the local Compose volume for this project (destructive to local test data):

```powershell
python scripts/task.py reset-test-data --yes
```

## Linux/macOS shell

```bash
python3 scripts/task.py setup
python3 scripts/task.py verify
python3 scripts/task.py dev
```

Use `python3 scripts/task.py stop` to stop, or `python3 scripts/task.py reset-test-data --yes` to delete only this project's local Compose volume.

## Targeted checks

Activate `.venv` or call its Python, then run `python scripts/verify.py --scope <scope>`. Supported scopes are `python-quality`, `python-tests`, `database`, `frontend`, `security`, `backend`, and `all`. CI calls the same verifier.

`python scripts/task.py smoke` creates a separate `nyan-shop-bot-smoke` Compose project, performs only GET health/readiness/catalog/admin checks plus absence checks for forbidden write routes, and removes its test volume in `finally`.

## Owner-controlled KhoMMO live read

This mode is local and read-only. It permits only `GET /me`, `GET /products`, and
`GET /products/{id}` at the fixed KhoMMO Partner API host. The application currently uses the
product endpoints for catalog and detail reads; it has no supplier order method or API route.
Startup rejects non-loopback `APP_HOST` values, and every live-read catalog route independently
rejects a non-loopback client even if Uvicorn is accidentally given a public bind override.

Obtain the Partner API token yourself through the KhoMMO Telegram bot's **Kết nối API** flow.
Do not paste it into an issue, PR, chat, command argument, screenshot, or log. In the repository
root, copy `.env.example` to the ignored `.env` file and edit these values locally:

```text
APP_ENV=local
SUPPLIER_MODE=khommo-readonly
KHOMMO_API_TOKEN=<set the real value only in this local .env file>
PAYMENT_MODE=disabled
ALLOW_REAL_PURCHASES=false
```

The tracked `.env.example` must keep `KHOMMO_API_TOKEN` empty. Docker Compose deliberately stays
in mock mode so a credential is not copied into a container environment. Use two local terminals:

```powershell
# Terminal 1, repository root
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
.\.venv\Scripts\python.exe -m uvicorn nyan_shop_bot.main:app --host 127.0.0.1 --port 8000

# Terminal 2
Set-Location admin
npm run dev
```

Starting FastAPI does not contact KhoMMO. First verify the safety state without making a supplier
request:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
```

The result must show `supplier_mode=khommo-readonly`, `payment_mode=disabled`,
`allow_real_purchases=false`, and `read_only=true`. Opening <http://127.0.0.1:5173> or requesting
the following URL is the explicit owner action that triggers the first real read-only
`GET /products` request:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/catalog
```

The live catalog accepts the owner-observed `VND_ONLY` value only for read-only display using
the documented integer `priceVnd` field and explicit `VND` currency. It does not authorize a
purchase payment mode. Products whose `description` or `stock` is null are omitted instead of
being guessed; the API returns `partial=true` and an exact `omitted_count`, and the admin must
show that warning. Every other schema, identity, currency, stock-consistency, or pagination
problem still fails the whole catalog closed.

One owner-authorized detail probe observed HTTP 200 with the exact top-level keys `ok` (boolean)
and `data` (product object). Detail parsing accepts only that envelope, requires `ok=true`, and
then applies the same strict product projection and requested-ID match as the listing boundary.
Direct product objects, extra keys, or mismatched identities fail closed. No raw live response or
product value is stored in the repository.

### Owner-started local Telegram read

The Telegram dispatcher uses the same configured `CatalogReader` as FastAPI. The runtime never
starts at application import, during tests, or without an explicit command-line confirmation.
Create your own bot through [@BotFather](https://t.me/BotFather); the project cannot create or
invent this credential. Put the returned value only in the ignored local `.env` file:

```text
TELEGRAM_BOT_TOKEN=<set the BotFather value only in this local .env file>
```

Do not paste the token into chat, a command argument, issue, PR, screenshot, or log. Keep the
same `APP_ENV=local`, loopback `APP_HOST`, `SUPPLIER_MODE=khommo-readonly`, disabled payment,
and false purchase guard shown above. After checking those values, this command is the explicit
owner action that starts Telegram polling and allows `/catalog` to issue read-only KhoMMO GETs:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
.\.venv\Scripts\python.exe -m nyan_shop_bot.bot.runtime --start-local-polling
```

Stop it with `Ctrl+C`. This runtime is for local owner verification only; do not start it in CI or
production. The Telegram customer surface uses Nyan Shop branding and does not expose the
upstream supplier name. It still marks stale/partial state and reports the exact omitted count.
The callback keeps the source identity internally so detail reads cannot cross suppliers.
`/orders` remains unavailable, and no purchase, payment, top-up, refund, or delivery operation
exists in this runtime.

To return to the synthetic catalog, stop both processes, set `SUPPLIER_MODE=mock`, remove the
supplier and Telegram tokens from `.env`, and restart. Never commit `.env`.

### VietShare local read-only source

VietShare uses the same FastAPI, admin, and Telegram `CatalogReader` path. It can run alone or as
part of the owner-approved `multi-readonly` catalog. In the ignored local `.env`, configure its
credentials and keep both independent write guards closed:

```text
APP_ENV=local
APP_HOST=127.0.0.1
SUPPLIER_MODE=vietshare-readonly
VIETSHARE_API_ID=<set only in this ignored local file>
VIETSHARE_API_SECRET=<set only in this ignored local file>
PAYMENT_MODE=disabled
ALLOW_REAL_PURCHASES=false
```

Never put either credential in a command argument, frontend variable, issue, PR, screenshot,
fixture, log, container image, or GitHub Actions secret. The production transport pins
`token.vietshare.site` over TLS, disables ambient proxies and redirects, limits response size,
and accepts only empty-body `GET /v1/account`, `GET /v1/products`, and
`GET /v1/products/{positive_integer}`. The catalog runtime uses only the latter two routes;
account data is not needed or exposed.

Sanitized pre-parser schema verification on 2026-09-22 made two catalog GETs and one detail GET.
All returned HTTP 200. Catalog retained the documented `count`/`products` envelope. Each observed
product had
exactly `id` (integer), `name` and `description` (string), `price` (integer), `flash_sale_id`
(null in the sample; documentation also permits integer), `stock` and `max_quantity` (integer),
`allow_quantity` (boolean), plus the observed production fields `currency` (array of strings) and
`price_usd` (string). Detail returned that product object directly and its ID matched the requested
ID. No raw response, product value, identifier, balance, credential, or delivery data was stored.

The normalized catalog intentionally uses the documented integer `price` as VND and does not use
or convert `price_usd`. Any missing, extra, mistyped, duplicate, or mismatched field fails closed.
Every retry creates a new timestamp, nonce, and signature while preserving the exact
`timestamp|nonce|METHOD|PATH_WITH_QUERY|sha256(raw_body)` rule; GET hashes empty bytes.

Run FastAPI and the admin with the same commands above, then verify `/healthz` before explicitly
opening `/api/v1/catalog`. Telegram polling uses the same owner-confirmed command after
`TELEGRAM_BOT_TOKEN` is present locally. `/orders` stays informational and no supplier order,
payment, top-up, refund, or delivery operation is implemented.

For the combined seller catalog, set `SUPPLIER_MODE=multi-readonly` and provide both suppliers'
local read-only credentials in the ignored `.env`. Telegram `/catalog` then opens the aggregate
view directly. Customer-visible catalog, detail, and price messages contain only Nyan Shop
branding; source names remain available in the loopback FastAPI/admin operations view for audit
and are retained internally in callback routing. Products are not deduplicated by name or price.

## Troubleshooting

- Port conflict: stop the existing local service on 5432, 8000, or 5173; do not change the container to a public bind.
- Docker Desktop overridden by `DOCKER_HOST`: set `NYAN_DOCKER_CONTEXT=desktop-linux` for task commands; this selects a context per command and does not change global Docker configuration.
- Readiness 503: inspect `docker compose logs db migrate api`; health can be green while PostgreSQL is unavailable.
- Unsafe configuration error: keep payment disabled and real purchases false. A live read requires `APP_ENV=local`, a loopback `APP_HOST`, one explicit `*-readonly` mode, and only that source's non-empty local credentials; generic live modes remain unsupported.
- No Docker: Python/frontend unit checks can run individually, but database, container smoke, and Docker build must be reported NOT RUN rather than PASS.
