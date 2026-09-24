# NSB-021 local mock checkout demo

This demo uses synthetic products, fake supplier responses, fake money, and the existing PostgreSQL order tables. It never calls a supplier purchase, payment, delivery, bank, or Telegram transport. `SUPPLIER_MODE=mock`, `PAYMENT_MODE=disabled`, and `ALLOW_REAL_PURCHASES=false` are enforced by the API and order service. The Nyan catalog linked to KhoMMO/VietShare stays read-only and is not an input to this checkout.

## Start

1. Keep the existing PostgreSQL volume and catalog data. Ensure migrations are current with `python -m alembic upgrade head`. Do not run `reset-test-data`.
2. Stop the existing local API process on port 8000. The admin Vite server on port 5173 can stay running.
3. From the repository root, run `.venv\Scripts\python.exe scripts/mock_checkout_demo.py` on Windows (or `.venv/bin/python scripts/mock_checkout_demo.py` on Linux). The script starts a loopback API on port 8000 with a random access key. It writes the key only to the ignored `.nyan-demo/access-token` file and prints the path, never the key.
4. Open `http://127.0.0.1:5173/` and select **Checkout MOCK**. Copy the key from `.nyan-demo/access-token` into the access field, then load the synthetic catalog and database history. The key is held only in the current browser tab's memory.

The browser actions create one order per explicit **Tạo đơn thử mới** cycle. A double click is blocked; a network retry reuses the same idempotency key. `FAILED_SAFE` means the fake supplier rejected the attempt with a definite outcome. `UNKNOWN` means the fake accepted it without final evidence. **Đối soát: chưa rõ** keeps it unresolved. The other reconciliation buttons provide explicit *synthetic* terminal evidence and never purchase again. The order list is read from PostgreSQL after each action and on refresh.

## Offline Telegram demonstration

In another terminal, run one of:

```powershell
.venv\Scripts\python.exe scripts/mock_bot_demo.py success
.venv\Scripts\python.exe scripts/mock_bot_demo.py failed_safe
.venv\Scripts\python.exe scripts/mock_bot_demo.py unknown
```

The script feeds `/catalog`, a callback, and `/orders` through aiogram with an in-memory transport and a synthetic allowlisted user. It writes the resulting order to the same PostgreSQL database. Refresh **Checkout MOCK** in the admin to see it. Repeated callbacks from the same chat message resolve to the same order intent. The actual Telegram polling runtime remains read-only and cannot use this demo dispatcher.

## Verification and data boundary

`python scripts/task.py verify` runs Python, PostgreSQL integration, admin unit, browser E2E, and security checks. Verification creates and migrates a separate `nyan_shop_bot_test` database; the test fixture truncates only its order tables. It does not clear the saved `nyan_shop_bot` catalog or demo orders. Local browser E2E uses installed Microsoft Edge on Windows; CI installs Playwright's version-matched Chromium headless shell.

The local access key is an operator gate for this demo, not a supplier credential. Keep `.nyan-demo/` untracked. No production deployment or real payment is provided by this issue. Live supplier selection, receiving money, delivery after uncertain outcomes, staging, backup, and rollback require a later owner-approved spec.
