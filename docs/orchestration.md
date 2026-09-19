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

`start` launches a detached local runner process unless `--foreground` is supplied. `status` reports controller and registered-launcher PIDs/liveness, exact phase/HEAD, worker and reviewer session IDs, PR/CI URLs, counters, errors, and recent events. Pause takes effect immediately during CI backoff and at the next safe checkpoint during a bounded model turn. Stop terminates the registered containment boundary before the claim can be released. Resume uses the same durable run, claim, worktree, branch, worker session, and existing PR.

## Trust and review flow

Only committed, unmodified JSON files under `ops/agent_tasks/` are executable task inputs. A new run requires the file to match the exact resolved base SHA, then stores a canonical JSON snapshot and SHA-256 digest; later phases never reload mutable policy from the checkout. The runner reads a GitHub issue only to verify its number, URL, title marker, state, and labels; issue/comment/PR prose is never appended to a worker prompt.

For each run the coordinator resolves and persists an exact base SHA and absolute deadline, creates a distinct `nyan/*` worktree, and records an active SQLite claim before launch. A transactional process lease prevents concurrent controllers for one run. The launcher has its own absolute deadline and cannot run indefinitely after controller failure. Before the model command can start, the runner captures the launcher's OS creation identity and persists a random nonce plus an acknowledgement path. On Windows, an out-of-Job watchdog owns a named `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` Job, terminates it, and waits for `ActiveProcesses == 0`. On Linux, an in-group watchdog anchors the process-group ID until an out-of-group cleanup helper kills that group and proves it disappeared. Only the matching nonce acknowledgement permits the active record or claim to clear. PID reuse, missing identity, unreadable identity, missing acknowledgement, and nonce mismatch all fail closed. Once an interrupted invocation exits safely, recovery reuses the explicit CLI session recorded in its event stream.

Worker output must include the GitHub issue number, branch, exact pre-commit HEAD, exact changed files, tests, result, and blockers. The worker edits only its worktree and cannot stage, commit, or push. The runner checks the clean parent SHA, working-tree paths, allowlist, and schema, stages exactly those paths, creates the commit, and only then pushes or opens/reuses a PR. The expected parent is persisted before launch; after a crash the runner validates a durable result plus the single runner-authored commit before advancing, so it does not repeat the worker turn or create a second commit. This preserves worktree isolation without granting a model write access to the repository's shared `.git` directory.

CI polling uses bounded exponential backoff and no model call. A required check is accepted only from the newest workflow run whose `headSha` equals the current worker HEAD; an older failed attempt cannot override a newer rerun in progress. The independent Codex reviewer runs in a read-only sandbox and must return `PASS`, `CHANGES_REQUESTED`, or `BLOCKED` for that same SHA; nullable finding locations are still required schema fields. Findings resume the explicit saved writer session. A fix commit invalidates prior CI/review. Durable terminal event streams recover worker/reviewer session IDs and account usage exactly once before advancing, so a controller crash cannot erase tokens or duplicate a completed review. Three fix rounds, five agent invocations by default, a persisted absolute deadline, and reported tokens are hard ceilings. Every individual Agent, Git, and GitHub subprocess recomputes a finite timeout capped by the remaining persisted deadline.

## Merge gate

Automatic merge and automatic next-task dispatch are **BLOCKED**, including for otherwise low-risk PRs. GitHub's supported `--match-head-commit` precondition binds the reviewed head SHA but does not atomically bind the reviewed base branch. A base-retarget race therefore remains between validation and queueing. The service, policy, GitHub adapter, legacy authorization path, and repository mutation command all fail closed; an old local authorization file or the previously drafted confirmation sentence grants no authority.

Every reviewer PASS ends at `READY_FOR_OWNER`. The owner may merge through the protected GitHub UI. A subsequent explicit `resume` only reconciles a PR already merged with the exact reviewed head and trusted base; it does not issue a merge. For `main`, completion then requires both `ci-gate` and the GHCR publish job for that merge commit. The runner never approves or merges its own runner/policy PR. A future unattended merge design needs a mechanism that atomically binds both head and base, or a new explicit product/risk decision; no current one-time permission is sufficient.

## Safety defaults and limitations

Every worker process receives `SUPPLIER_MODE=mock`, `PAYMENT_MODE=disabled`, and `ALLOW_REAL_PURCHASES=false`. Its environment is rebuilt from a small operating-system/path allowlist, not a secret-name blacklist; database access is forced to a dedicated fail-closed loopback URL, and ambient `DATABASE_URL`, `PG*`, Docker auth/config, Python injection paths, tokens, and keys are not inherited. The local Python runtime that launched the controller is prepended to `PATH`, so bounded worker/reviewer checks reuse its installed project dependencies without installing or downloading anything. GitHub, Docker, PostgreSQL, npm, pip, cloud, and Kubernetes config paths are redirected to empty per-run locations while local saved Codex/Antigravity login remains available to the signed tools. This is least exposure, not a hard security boundary: a worktree and a CLI sandbox are not equivalent to an isolated machine. Therefore only trusted backlog specs are dispatched, concurrency is at most two writers, and high-risk changes require the owner.

Publishing an exact-SHA image after a trusted `main` gate remains artifact delivery. Production and staging deployment stay BLOCKED until their separately documented owner inputs exist.
