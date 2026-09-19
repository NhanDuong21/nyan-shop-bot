# Nyan Shop Bot agent instructions

These instructions apply to the whole repository.

## Verify and run

- Setup: `python scripts/task.py setup`
- Full verification: `python scripts/task.py verify`
- Isolated container smoke: `python scripts/task.py smoke`
- Local mock stack: `python scripts/task.py dev`
- Stop without deleting data: `python scripts/task.py stop`

Use `python3` instead of `python` where that is the platform command. Do not claim PASS for a command that was not run.

## Safety and privacy

- Keep `SUPPLIER_MODE=mock`, `PAYMENT_MODE=disabled`, and `ALLOW_REAL_PURCHASES=false` until a later owner-approved issue explicitly changes the boundary.
- Never call live purchase, top-up, refund, delivery, bank, supplier, or Telegram transport in tests or demos. Never put credentials in source, frontend, logs, screenshots, artifacts, fixtures, or Actions.
- `nyan-bootstrap/`, `.env*` (except `.env.example`), local data, and partner source documents stay untracked. Use only synthetic mock catalog data.
- Represent money as integer minor units plus explicit currency; never use float or combine currencies.

## Issue and PR workflow

- `main` is PR-only. Never push directly, force-push, auto-merge, or bypass `ci-gate`.
- A coordinator claims an issue before work. One writer owns one branch/worktree and a declared file scope. Shared workflows, lockfiles, contracts, and migrations belong to the coordinator.
- Keep changes inside the issue scope, link real dependencies, and attach exact-SHA test evidence. Nyan performs the final merge.
- Read [docs/agent-ops.md](docs/agent-ops.md) before dispatching or accepting agent work.

## Code Review Rules

- Reject any path that can enable live money/supplier operations, leak a credential, or let an unauthenticated admin bind publicly.
- Reject retries or failure handling that could create a second supplier obligation; uncertain outcomes must not be guessed successful or failed.
- Reject workflow changes that broaden PR permissions, use unpinned Actions, skip a required job, or publish an image before the same commit passes `ci-gate`.
