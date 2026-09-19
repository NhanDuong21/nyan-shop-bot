# Role handoffs

## Coordinator

Input: real issue URL, current base SHA, dependencies, and GitHub state. Output: a claim, branch/worktree, bounded handoff, reconciled evidence, and PR. Never treats a label as a lock, creates fake assignees, merges, or grants live-operation authority.

## Backend/bot writer

Input: claimed issue plus allowed modules. Output: code, migrations only when assigned, tests, exact commands/results, and HEAD SHA. All transports are mocked in CI; unknown supplier schemas return unsupported rather than guessed behavior.

## UI writer

Input: claimed UI issue, generated backend OpenAPI/fixtures, and explicit repository instructions. Output: code under `admin/`, interaction/accessibility evidence, and HEAD SHA. Supplier keys and delivery credentials never enter browser code.

## Reviewer

Input: issue URL, base SHA, exact PR HEAD SHA, and safe verification instructions. Output: prioritized findings with file/line evidence, independent test results, and residual risks/NOT RUN items. Reviewer leaves a COMMENT; Nyan remains final reviewer/merger.
