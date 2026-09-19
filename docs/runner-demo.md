# Runner control quickstart

From the repository worktree containing the runner, inspect or control a run:

```text
python scripts/agent_runner.py status --run-id <run-id>
python scripts/agent_runner.py pause --run-id <run-id>
python scripts/agent_runner.py resume --run-id <run-id>
python scripts/agent_runner.py stop --run-id <run-id>
```

- `status` reports the current run state.
- `pause` is cooperative: during an active model turn, it takes effect at the next safe boundary.
- `resume` reuses the run's durable state.
- `stop` terminates the registered agent process tree before releasing the claim.

The safety defaults remain `SUPPLIER_MODE=mock`, `PAYMENT_MODE=disabled`, and
`ALLOW_REAL_PURCHASES=false`.
