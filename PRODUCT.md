# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Nyan is the product owner and primary trial user. The admin surface is for a shop operator who needs to inspect catalog and environment state quickly, understand failures, and recover without handling source code or relaying messages between agents.

## Product Purpose

Nyan Shop Bot combines a Telegram customer surface, a FastAPI/PostgreSQL service, supplier adapters, and an admin web tool. The current product must provide a repeatable mock-only trial; success means Nyan can run and evaluate honest end-to-end behavior before separately approving any live deployment or transaction.

## Positioning

Operational truth and safety state are first-class product data: unsupported supplier capabilities remain disabled, unknown outcomes are reconciled rather than guessed, and the interface never hides MOCK, READ-ONLY, or unavailable behavior behind a polished demo.

## Operating Context

- Local development and CI use a synthetic catalog, PostgreSQL, an offline-testable bot, and a localhost-bound admin.
- The operator scans catalog availability, supplier/environment status, errors, and recovery actions during routine shop operations.
- The coordinator routes agent work and review findings. Nyan provides product feedback, tests a handed-off build, and makes live-readiness decisions.

## Capabilities and Constraints

- `SUPPLIER_MODE=mock`, `PAYMENT_MODE=disabled`, and `ALLOW_REAL_PURCHASES=false` remain mandatory until a later owner-approved issue changes them.
- No production secrets, live purchase, top-up, refund, supplier delivery, or production deployment is authorized.
- Missing supplier schemas disable only the affected operation; they do not block mock foundations.
- Codex owns architecture, contracts, API/client/auth/business logic, shared theme infrastructure, dependencies, CI/CD, security, and orchestration.
- Antigravity may change presentation only inside one exact feature path supplied by a trusted task, using coordinator-provided props, callbacks, and hooks.
- `READY_FOR_USER_TESTING` and `APPROVED_FOR_LIVE` are distinct; only Nyan grants the latter.

## Brand Commitments

- Keep the product name “Nyan Shop Bot” and use concise Vietnamese operational language.
- The admin is a basic, clean, light-first work surface, not a landing page. It must not introduce marketing heroes, 3D/neon styling, heavy glass, or distracting looping motion.

## Evidence on Hand

- The repository contains a runnable mock catalog/API/admin foundation and automated tests.
- Catalog content committed to the repository is synthetic. Private supplier source documents and credentials are deliberately absent.
- Live supplier purchase, production deployment, backup/restore, and payment behavior remain unverified until their dedicated issues produce evidence.

## Product Principles

1. Show operational truth before visual confidence.
2. Keep money and supplier writes disabled by default.
3. Make routine work scannable, recoverable, and keyboard accessible.
4. Separate a trial-ready build from permission to go live.
5. Let agents coordinate directly inside reviewed, bounded scopes.

## Accessibility & Inclusion

Both themes must preserve readable contrast, visible keyboard focus, semantic state announcements, reduced-motion behavior, and layouts that remain usable on narrow screens and with enlarged text.
