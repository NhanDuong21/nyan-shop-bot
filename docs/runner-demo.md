# Runner operator quickstart

From the repository worktree containing the runner, replace `<run-id>` with the
durable run identifier you want to inspect or control:

```powershell
python scripts/agent_runner.py status --run-id <run-id>
python scripts/agent_runner.py pause --run-id <run-id>
python scripts/agent_runner.py resume --run-id <run-id>
python scripts/agent_runner.py stop --run-id <run-id>
```

- `status` prints the current persisted run state.
- `pause` requests a cooperative pause. During an active model turn, it takes
  effect at the next safe model-turn boundary/checkpoint.
- `resume` continues the same run by reusing its durable persisted state and
  saved session when available.
- `stop` requests a cooperative stop. During an active model turn, it takes
  effect at the next safe model-turn boundary/checkpoint.

Keep the current safety defaults:

```text
SUPPLIER_MODE=mock
PAYMENT_MODE=disabled
ALLOW_REAL_PURCHASES=false
```
