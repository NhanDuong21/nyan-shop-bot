# Runner quickstart

Run the local runner from the repository worktree with a trusted task spec:

```text
python scripts/agent_runner.py start --task ops/agent_tasks/<task>.json
```

Use the run ID printed by `start` to inspect or control that run:

```text
python scripts/agent_runner.py status --run-id <run-id>
python scripts/agent_runner.py pause --run-id <run-id>
python scripts/agent_runner.py resume --run-id <run-id>
python scripts/agent_runner.py stop --run-id <run-id>
```

`pause` is cooperative: for an active model turn, it takes effect at the next safe model-turn boundary. `stop` terminates the registered agent process tree before releasing the claim. `resume` reuses the run's durable state, including its claim, worktree, branch, and saved session.

The worker safety defaults remain:

```text
SUPPLIER_MODE=mock
PAYMENT_MODE=disabled
ALLOW_REAL_PURCHASES=false
```
