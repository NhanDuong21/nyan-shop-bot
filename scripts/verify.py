"""Unified verification entry point used locally and by CI."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "admin"
TEST_DATABASE_URL = (
    "postgresql+asyncpg://nyan_local:nyan_local_only@127.0.0.1:5432/nyan_shop_bot_test"
)


def run(command: Sequence[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    printable = " ".join(command)
    print(f"\n> {printable}", flush=True)
    executable = shutil.which(command[0]) or command[0]
    subprocess.run(
        (executable, *command[1:]),
        cwd=cwd,
        check=True,
        env=env or os.environ.copy(),
    )


def verify_python_quality() -> None:
    run([sys.executable, "-m", "ruff", "format", "--check", "src", "tests", "scripts"])
    run([sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"])
    run([sys.executable, "-m", "mypy", "src"])


def verify_python_tests() -> None:
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit",
            "tests/suppliers",
            "tests/bot",
            "tests/e2e",
            "-m",
            "not integration",
        ]
    )


def verify_database() -> None:
    run([sys.executable, "scripts/ensure_test_database.py"])
    test_env = os.environ.copy()
    test_env.update(
        DATABASE_URL=TEST_DATABASE_URL,
        SUPPLIER_MODE="mock",
        PAYMENT_MODE="disabled",
        ALLOW_REAL_PURCHASES="false",
    )
    run([sys.executable, "-m", "alembic", "upgrade", "head"], env=test_env)
    run([sys.executable, "-m", "alembic", "current", "--check-head"], env=test_env)
    run([sys.executable, "-m", "pytest", "tests/integration", "-m", "integration"], env=test_env)


def verify_frontend() -> None:
    run(["npm", "run", "lint"], cwd=ADMIN)
    run(["npm", "run", "typecheck"], cwd=ADMIN)
    run(["npm", "run", "test"], cwd=ADMIN)
    run(["npm", "run", "test:e2e"], cwd=ADMIN)
    run(["npm", "run", "build"], cwd=ADMIN)


def verify_security() -> None:
    run([sys.executable, "scripts/security_policy.py"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=(
            "all",
            "backend",
            "python-quality",
            "python-tests",
            "database",
            "frontend",
            "security",
        ),
        default="all",
    )
    args = parser.parse_args()

    scopes = (
        ("python-quality", verify_python_quality),
        ("python-tests", verify_python_tests),
        ("database", verify_database),
        ("frontend", verify_frontend),
        ("security", verify_security),
    )
    for name, function in scopes:
        if args.scope in ("all", name) or (
            args.scope == "backend" and name in {"python-quality", "python-tests"}
        ):
            function()

    print("\nVerification passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
