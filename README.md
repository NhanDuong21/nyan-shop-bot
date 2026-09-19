# Nyan Shop Bot

Mock-first foundation for a Telegram reseller bot: FastAPI + aiogram, PostgreSQL/Alembic, and a React/Vite/TypeScript admin. Phase 0 is deliberately incapable of live purchases or payments.

## Start locally

Prerequisites: Python 3.12–3.14, Node.js 22.12+ (Node 24 tested), npm, Docker, and Docker Compose.

```text
python scripts/task.py setup
python scripts/task.py verify
python scripts/task.py dev
```

Open the admin at <http://127.0.0.1:5173>, API docs at <http://127.0.0.1:8000/docs>, and health at <http://127.0.0.1:8000/healthz>. The admin is unauthenticated in NSB-001 and therefore only binds to localhost.

On Linux, use `python3` if `python` is not available. See [the runbook](docs/runbook.md) for PowerShell/Linux commands and safe cleanup.

## Safety defaults

```text
SUPPLIER_MODE=mock
PAYMENT_MODE=disabled
ALLOW_REAL_PURCHASES=false
```

Startup rejects any other Phase 0 combination. Tests block non-loopback sockets, catalog fixtures are synthetic, no purchase/top-up/refund/delivery routes exist, and CI receives no supplier, bank, Telegram, or OpenAI production secrets.

## Repository map

- `src/nyan_shop_bot/`: FastAPI, read-only catalog boundary, and offline bot skeleton.
- `alembic/`: initial PostgreSQL migration.
- `admin/`: localhost-only mock catalog UI.
- `tests/`: unit, network-policy, bot, and PostgreSQL integration tests.
- `scripts/`: cross-platform task, verification, policy, smoke, and GitHub seed tools.
- `src/nyan_shop_bot/orchestrator/`: durable local runner, CLI adapters, policy, and state machine.
- `ops/agent_tasks/`: trusted, committed worker task specifications; GitHub prose is never executed as instructions.
- `docs/`: runbooks, roles, supplier boundary, and delivery status.
- `.codex/agents/`: project-scoped coordinator/backend/UI/reviewer definitions.

Container publishing to GHCR after a trusted `main` gate is artifact delivery, not deployment. Staging deployment remains blocked until an owner supplies a host, ingress/auth design, and staging-only secrets.

The owner-gated local orchestration workflow is documented in [docs/orchestration.md](docs/orchestration.md). Auto-merge remains disabled until the explicit one-time owner authorization is given; high-risk and protected-path PRs always stay open for the owner.
