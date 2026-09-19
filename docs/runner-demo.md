# Runner operator quickstart

Run these controls from the repository worktree that contains the runner. Replace
`<run-id>` with the durable run identifier; do not invent a new identifier.

```text
python scripts/agent_runner.py status --run-id <run-id>
python scripts/agent_runner.py pause --run-id <run-id>
python scripts/agent_runner.py resume --run-id <run-id>
python scripts/agent_runner.py stop --run-id <run-id>
```

- `status` reports the current state of the registered run.
- `pause` is cooperative. During an active model turn, it takes effect at the
  next safe turn boundary rather than forcibly interrupting the turn.
- `resume` reuses the run's durable state, including its existing claim, rather
  than creating a new run.
- `stop` terminates the registered agent process tree before releasing the
  claim.

The current safety defaults remain:

```text
SUPPLIER_MODE=mock
PAYMENT_MODE=disabled
ALLOW_REAL_PURCHASES=false
```
