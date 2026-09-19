# Owner-gated local orchestration

The runner is a local control plane, not a GitHub Actions agent and not a security sandbox. It uses the user's existing local CLI logins, creates one worktree per writer, stores durable state in ignored `.nyan-runner/state.sqlite3`, and gives GitHub Actions no Codex, Antigravity, supplier, payment, or production credential.

## Verified capability baseline (2026-09-19)

| Component | Verified locally | Automation boundary |
|---|---|---|
| Codex CLI | `codex-cli 0.153.0`; ChatGPT login; `exec`, JSONL, JSON Schema, explicit session resume, read-only/workspace-write sandbox | One process/session per writer or reviewer; never `--last`, ephemeral sessions, or approval/sandbox bypass |
| Codex models | Current account catalog includes `gpt-5.6-luna` and `codex-auto-review`, used by the proof task | Model slugs are task data only after discovery; no API key or billing switch |
| Antigravity CLI | Google-signed `agy 1.2.7`; print/headless, stream JSON, JSON Schema, conversation resume, finite timeout, sandbox; model discovery succeeds | `agy` only, with subprocess `cwd` set to the UI worktree; no GUI clicking or IDE/internal endpoint. Generation auth is proven only by a real UI task |
| Git/GitHub | Git worktrees, `gh 2.94.0`, active `NhanDuong21` login, repository admin | Runner uses normal branches/PRs and required checks; no push to `main`, force-push, fake approval, or admin bypass |
| Usage | Codex per-turn usage is read from JSONL; account quota is readable in the Codex app. Antigravity exposes per-run usage but no supported headless total-quota command | Bounds are invocations, elapsed time, fix rounds, and reported tokens; the runner never buys credits or enables paid API use |

OpenAI's documented non-interactive behavior is the basis for JSONL, schema output, and explicit session resume: <https://developers.openai.com/codex/non-interactive-mode>. Antigravity headless behavior is documented at <https://antigravity.google/docs/cli/headless/>. Installed `--help` output wins when it differs from current web documentation.

## Commands

From the repository worktree containing the runner:

```text
python scripts/agent_runner.py start --task ops/agent_tasks/NSB-041.json
python scripts/agent_runner.py status --run-id <run-id>
python scripts/agent_runner.py pause --run-id <run-id>
python scripts/agent_runner.py resume --run-id <run-id>
python scripts/agent_runner.py stop --run-id <run-id>
```

`start` launches a detached local runner process unless `--foreground` is supplied. `status` reports controller and active-agent PIDs/liveness, exact phase/HEAD, worker and reviewer session IDs, PR/CI URLs, counters, errors, and recent events. Pause/stop take effect immediately during CI backoff and at the next safe checkpoint during a bounded model turn. Resume uses the same durable run, claim, worktree, branch, worker session, and existing PR.

## Trust and review flow

Only committed, unmodified JSON files under `ops/agent_tasks/` are executable task inputs. A new run requires the file to match the exact resolved base SHA, then stores a canonical JSON snapshot and SHA-256 digest; later phases never reload mutable policy from the checkout. The runner reads a GitHub issue only to verify its number, URL, title marker, state, and labels; issue/comment/PR prose is never appended to a worker prompt.

For each run the coordinator resolves and persists an exact base SHA and absolute deadline, creates a distinct `nyan/*` worktree, and records an active SQLite claim before launch. A transactional process lease prevents concurrent controllers for one run. The child Codex/Antigravity PID is persisted before interaction; if a controller dies, resume refuses to launch a duplicate while that child is alive. Once it exits, recovery reuses the explicit CLI session recorded in its event stream. `stop` transitions to terminal `STOPPED` and releases the claim.

Worker output must include the GitHub issue number, branch, exact pre-commit HEAD, exact changed files, tests, result, and blockers. The worker edits only its worktree and cannot stage, commit, or push. The runner checks the clean parent SHA, working-tree paths, allowlist, and schema, stages exactly those paths, creates the commit, and only then pushes or opens/reuses a PR. The expected parent is persisted before launch; after a crash the runner validates a durable result plus the single runner-authored commit before advancing, so it does not repeat the worker turn or create a second commit. This preserves worktree isolation without granting a model write access to the repository's shared `.git` directory.

CI polling uses bounded exponential backoff and no model call. A required check is accepted only from the newest workflow run whose `headSha` equals the current worker HEAD; an older failed attempt cannot override a newer rerun in progress. The independent Codex reviewer runs in a read-only sandbox and must return `PASS`, `CHANGES_REQUESTED`, or `BLOCKED` for that same SHA. Findings resume the explicit saved writer session. A fix commit invalidates prior CI/review. Three fix rounds, five agent invocations by default, a persisted absolute deadline, and reported tokens are hard ceilings. Agent, Git, and GitHub subprocesses all receive a finite timeout capped by the remaining persisted deadline.

## Merge gate

Auto-merge is currently disabled. This runner/policy PR, workflows, permissions, migrations, secrets, and any live-operation path are protected and can never self-authorize. A task must target `main`, be explicitly low risk and auto-merge eligible, touch no protected path, pass exact-SHA CI, receive exact-SHA reviewer PASS, and have no blocker. The eventual GitHub command also uses `--match-head-commit`; a remote head change makes the queue request fail atomically.

The only accepted one-time confirmation text is:

```text
I authorize Nyan Shop Bot to enable GitHub auto-merge and automatically dispatch committed M0-M2 task specs, limited to two writers; only low-risk, unprotected, exact-SHA PASS PRs targeting main may be queued for merge.
```

After the owner sends that sentence to the coordinator, the coordinator—not a worker—may run `authorize-auto-merge` with the exact text. That command enables the GitHub repository setting, verifies it, and records local authorization. A run waiting at `MERGE_PENDING_CONFIRMATION` then requires an explicit `resume`; it revalidates the exact reviewed SHA before queuing. High-risk and protected PRs remain `READY_FOR_OWNER`: after the owner merges one manually, `resume` verifies the PR was merged from that exact reviewed head and, for `main`, requires both `ci-gate` and the GHCR publish job before completion. Only then may the authorized queue select the next committed M0–M2 task whose dependencies are closed. The runner never approves or merges its own runner/policy PR. Until the relevant gate is satisfied, PRs remain open and claims remain durable.

## Safety defaults and limitations

Every worker process receives `SUPPLIER_MODE=mock`, `PAYMENT_MODE=disabled`, and `ALLOW_REAL_PURCHASES=false`. Its environment is rebuilt from a small operating-system/path allowlist, not a secret-name blacklist; database access is forced to a dedicated fail-closed loopback URL, and ambient `DATABASE_URL`, `PG*`, Docker auth/config, Python injection paths, tokens, and keys are not inherited. GitHub, Docker, PostgreSQL, npm, pip, cloud, and Kubernetes config paths are redirected to empty per-run locations while local saved Codex/Antigravity login remains available to the signed tools. This is least exposure, not a hard security boundary: a worktree and a CLI sandbox are not equivalent to an isolated machine. Therefore only trusted backlog specs are dispatched, concurrency is at most two writers, and high-risk changes require the owner.

Publishing an exact-SHA image after a trusted `main` gate remains artifact delivery. Production and staging deployment stay BLOCKED until their separately documented owner inputs exist.
