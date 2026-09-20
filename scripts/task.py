"""Cross-platform setup, development, verification, and safe local cleanup."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"


def venv_python() -> Path:
    windows_python = VENV / "Scripts" / "python.exe"
    return windows_python if windows_python.exists() else VENV / "bin" / "python"


def run(*command: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"\n> {' '.join(command)}", flush=True)
    executable = shutil.which(command[0]) or command[0]
    subprocess.run(
        (executable, *command[1:]),
        cwd=cwd,
        check=True,
        env=env or os.environ.copy(),
    )


def ensure_venv() -> Path:
    interpreter = venv_python()
    if not interpreter.exists():
        raise SystemExit("Missing .venv. Run: python scripts/task.py setup")
    return interpreter


def compose(*arguments: str, env: dict[str, str] | None = None) -> None:
    command = ["docker"]
    context = os.environ.get("NYAN_DOCKER_CONTEXT")
    if context:
        command.extend(("--context", context))
    command.extend(("compose", *arguments))
    run(*command, env=env)


def setup() -> None:
    if not VENV.exists():
        run(sys.executable, "-m", "venv", str(VENV))
    interpreter = ensure_venv()
    run(str(interpreter), "-m", "pip", "install", "-r", "requirements-dev.lock")
    run("npm", "ci", cwd=ROOT / "admin")
    compose("up", "-d", "--wait", "db")


def verify() -> None:
    interpreter = ensure_venv()
    compose("up", "-d", "--wait", "db")
    run(str(interpreter), "scripts/verify.py", "--scope", "all")


def smoke() -> None:
    interpreter = ensure_venv()
    project = "nyan-shop-bot-smoke"
    smoke_env = os.environ.copy()
    smoke_env.update(
        {
            "NYAN_DB_PORT": "55432",
            "NYAN_API_PORT": "18000",
            "NYAN_ADMIN_PORT": "15173",
            "NYAN_API_URL": "http://127.0.0.1:18000",
            "NYAN_ADMIN_URL": "http://127.0.0.1:15173",
        }
    )
    try:
        compose("-p", project, "up", "-d", "--build", "--wait", env=smoke_env)
        run(str(interpreter), "scripts/smoke.py", env=smoke_env)
    finally:
        compose(
            "-p",
            project,
            "down",
            "--volumes",
            "--remove-orphans",
            env=smoke_env,
        )


def reset_test_data(confirmed: bool) -> None:
    if not confirmed:
        raise SystemExit("Refusing cleanup without: python scripts/task.py reset-test-data --yes")
    compose("down", "--volumes", "--remove-orphans")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("setup", help="Install locked dependencies and start local PostgreSQL")
    subparsers.add_parser("verify", help="Run every required local check")
    subparsers.add_parser("dev", help="Run the complete mock stack")
    subparsers.add_parser("stop", help="Stop the local stack without deleting data")
    subparsers.add_parser("smoke", help="Build and smoke-test an isolated Docker stack")
    reset_parser = subparsers.add_parser(
        "reset-test-data", help="Delete only this Compose project's local volumes"
    )
    reset_parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if args.command == "setup":
        setup()
    elif args.command == "verify":
        verify()
    elif args.command == "dev":
        compose("up", "--build")
    elif args.command == "stop":
        compose("down", "--remove-orphans")
    elif args.command == "smoke":
        smoke()
    elif args.command == "reset-test-data":
        reset_test_data(args.yes)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
