# Local runbook

## PowerShell

```powershell
$env:NYAN_DOCKER_CONTEXT = "desktop-linux" # only if DOCKER_HOST overrides Docker Desktop
python scripts/task.py setup
python scripts/task.py verify
python scripts/task.py dev
```

Use another terminal for `dev`. Stop without deleting data:

```powershell
python scripts/task.py stop
```

Delete only the local Compose volume for this project (destructive to local test data):

```powershell
python scripts/task.py reset-test-data --yes
```

## Linux/macOS shell

```bash
python3 scripts/task.py setup
python3 scripts/task.py verify
python3 scripts/task.py dev
```

Use `python3 scripts/task.py stop` to stop, or `python3 scripts/task.py reset-test-data --yes` to delete only this project's local Compose volume.

## Targeted checks

Activate `.venv` or call its Python, then run `python scripts/verify.py --scope <scope>`. Supported scopes are `python-quality`, `python-tests`, `database`, `frontend`, `security`, `backend`, and `all`. CI calls the same verifier.

`python scripts/task.py smoke` creates a separate `nyan-shop-bot-smoke` Compose project, performs only GET health/readiness/catalog/admin checks plus absence checks for forbidden write routes, and removes its test volume in `finally`.

## Troubleshooting

- Port conflict: stop the existing local service on 5432, 8000, or 5173; do not change the container to a public bind.
- Docker Desktop overridden by `DOCKER_HOST`: set `NYAN_DOCKER_CONTEXT=desktop-linux` for task commands; this selects a context per command and does not change global Docker configuration.
- Readiness 503: inspect `docker compose logs db migrate api`; health can be green while PostgreSQL is unavailable.
- Unsafe configuration error: restore the three Phase 0 safety values in `.env`; live modes are intentionally unsupported.
- No Docker: Python/frontend unit checks can run individually, but database, container smoke, and Docker build must be reported NOT RUN rather than PASS.
