# GitHub backlog map

GitHub Issues and Milestones are the coordination source of truth. Stable NSB codes make `scripts/github_seed.py --apply` idempotent; issue numbers below are real for this repository, not guessed identifiers.

## M0 — Foundation

- [NSB-001 — Bootstrap repo, agent workflow, and CI/container delivery](https://github.com/NhanDuong21/nyan-shop-bot/issues/1) — in progress in the bootstrap PR.

## M1 — Catalog and read-only integrations

- [NSB-010 — Normalized catalog, capability model, and code-generated schema](https://github.com/NhanDuong21/nyan-shop-bot/issues/2) — first Ready item after NSB-001 merges.
- [NSB-011 — VietShare read-only adapter and signing tests](https://github.com/NhanDuong21/nyan-shop-bot/issues/3)
- [NSB-012 — KhoMMO read-only adapter](https://github.com/NhanDuong21/nyan-shop-bot/issues/4)
- [NSB-013 — Roboticvn schema audit and read-only adapter](https://github.com/NhanDuong21/nyan-shop-bot/issues/5)
- [NSB-014 — Admin catalog, suppliers, and environment state](https://github.com/NhanDuong21/nyan-shop-bot/issues/6)
- [NSB-015 — Telegram bot catalog browsing and simulated quote](https://github.com/NhanDuong21/nyan-shop-bot/issues/7)

## M2 — Simulated end-to-end orders

- [NSB-020 — Order orchestration, dedupe, and reconciliation with fake supplier](https://github.com/NhanDuong21/nyan-shop-bot/issues/8)
- [NSB-021 — Mock checkout across bot, API, and admin](https://github.com/NhanDuong21/nyan-shop-bot/issues/9)

## M3 — Staging and live readiness

- [NSB-030 — Deploy tested mock images to staging](https://github.com/NhanDuong21/nyan-shop-bot/issues/10) — blocked until an owner provides a staging target and secrets.
- [NSB-031 — Live readiness, Stars test, and supplier conformance](https://github.com/NhanDuong21/nyan-shop-bot/issues/11)

## M4 — Unattended agent dispatch

- [NSB-040 — Durable local agent orchestrator and owner-gated merge controls](https://github.com/NhanDuong21/nyan-shop-bot/issues/12) — accelerated by explicit owner direction; implemented in a separate stacked PR, with auto-merge still disabled.
- [NSB-041 — Prove runner with a no-money operator quickstart](https://github.com/NhanDuong21/nyan-shop-bot/issues/15) — low-risk real worker/CI/reviewer proof task; never independently mergeable from its runner base.

After NSB-001 and the separately reviewed NSB-040 merge, move only NSB-010 to Ready. After NSB-010 merges, the coordinator may select at most one supplier/backend issue alongside NSB-014; do not make every downstream issue Ready at once. Automatic selection is limited to committed task specs for M0–M2 and remains disabled until owner authorization.
