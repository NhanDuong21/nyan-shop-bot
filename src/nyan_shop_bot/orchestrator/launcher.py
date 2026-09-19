"""Detached local process launcher shared by CLI and automatic queue continuation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def spawn_background(root: Path, state_dir: Path, run_id: str) -> int:
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "runner.stdout.log"
    stderr_path = run_dir / "runner.stderr.log"
    script = root / "scripts" / "agent_runner.py"
    command = [
        sys.executable,
        str(script),
        "--root",
        str(root),
        "--state-dir",
        str(state_dir),
        "_run",
        "--run-id",
        run_id,
    ]
    with (
        stdout_path.open("a", encoding="utf-8") as stdout_file,
        stderr_path.open("a", encoding="utf-8") as stderr_file,
    ):
        if os.name == "nt":
            process = subprocess.Popen(  # noqa: S603 - fixed local script and argv
                command,
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP),
            )
        else:
            process = subprocess.Popen(  # noqa: S603 - fixed local script and argv
                command,
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
            )
    return int(process.pid)
