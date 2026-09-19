"""Barrier launcher used to register an agent process before it can execute."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _validated_spec(path: Path) -> tuple[list[str], str | None]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("launcher spec must be a JSON object")
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item for item in command)
    ):
        raise RuntimeError("launcher command must be a non-empty string array")
    stdin_path = value.get("stdin_path")
    if stdin_path is not None and not isinstance(stdin_path, str):
        raise RuntimeError("launcher stdin_path must be a string or null")
    return command, stdin_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--start", type=Path, required=True)
    parser.add_argument("--barrier-timeout", type=float, default=30.0)
    args = parser.parse_args()

    command, stdin_path = _validated_spec(args.spec)
    args.ready.write_text(str(sys.version_info.major), encoding="utf-8")
    deadline = time.monotonic() + max(1.0, args.barrier_timeout)
    while not args.start.is_file():
        if time.monotonic() >= deadline:
            return 124
        time.sleep(0.02)

    if stdin_path is None:
        return subprocess.run(command, stdin=subprocess.DEVNULL, check=False).returncode
    with Path(stdin_path).open("r", encoding="utf-8") as stdin_file:
        return subprocess.run(command, stdin=stdin_file, check=False, text=True).returncode


if __name__ == "__main__":
    raise SystemExit(main())
