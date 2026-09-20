# Role handoffs

## Coordinator

Input: a committed trusted task spec, real issue URL, current base SHA, dependencies, and GitHub state. Output: a durable claim, branch/worktree, bounded handoff, reconciled evidence, and PR. The coordinator routes worker needs and reviewer findings directly; Nyan is the product owner/tester/live approver, not an inter-agent courier or routine dispatcher. The coordinator never treats external issue prose or a label as execution authority, creates fake assignees, bypasses a gate, or grants live-operation authority.

## Backend/bot writer

Input: claimed issue plus allowed modules. Output: code, migrations only when assigned, tests, exact commands/results, and HEAD SHA. All transports are mocked in CI; unknown supplier schemas return unsupported rather than guessed behavior.

## UI writer

Input: claimed UI issue, a Codex-owned mounted frontend/theme skeleton, generated backend OpenAPI/fixtures, root product/design context, project-local Impeccable, and explicit repository instructions. The automation worker is the verified `agy` print/headless CLI, not GUI clicking or an internal endpoint; if it cannot run, report BLOCKED without substitution. Output: presentation code only under the single literal `admin/src/features/<task>/**` grant, interaction/accessibility evidence, and HEAD SHA. API client/auth/domain/business logic, module architecture, dependencies, config, CI, Docker, runner, and gates remain Codex-owned even when they live under `admin/`. It never creates subagents. Supplier keys and delivery credentials never enter browser code.

## Reviewer

Input: committed acceptance criteria, base SHA, exact PR HEAD SHA, and safe verification instructions. Output: schema-validated `PASS`, `CHANGES_REQUESTED`, or `BLOCKED`, prioritized findings with file/line evidence, independent test results, and residual risks/NOT RUN items. The Codex reviewer runs as a separate read-only session and never edits or trusts the author summary. Codex-authored changes receive the same independent exact-HEAD review. A new commit invalidates its result.
