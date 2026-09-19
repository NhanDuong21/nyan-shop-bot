"""Command-line control plane for the local Nyan agent runner."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from nyan_shop_bot.orchestrator.launcher import spawn_background
from nyan_shop_bot.orchestrator.models import DesiredState
from nyan_shop_bot.orchestrator.service import OWNER_CONFIRMATION, RunnerService, process_alive


def _service(root: Path, state_dir: Path | None) -> RunnerService:
    return RunnerService(root, state_dir)


def _start_background(service: RunnerService, run_id: str) -> dict[str, object]:
    service.prepare_process_launch(run_id)
    launched_pid = spawn_background(service.root, service.state_dir, run_id)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = service.store.get_run(run_id)
        persisted_pid = int(run["pid"]) if run["pid"] is not None else None
        if persisted_pid is not None:
            return {
                "run_id": run_id,
                "launched_pid": launched_pid,
                "pid": persisted_pid,
                "process_alive": process_alive(persisted_pid),
            }
        if not process_alive(launched_pid):
            break
        time.sleep(0.2)
    status = service.status(run_id)
    return {
        "run_id": run_id,
        "launched_pid": launched_pid,
        "pid": status["pid"],
        "process_alive": status["process_alive"],
        "phase": status["phase"],
        "last_error": status["last_error"],
    }


def _resolve_run_id(service: RunnerService, value: str | None) -> str:
    return value or service.store.latest_run_id()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--state-dir", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Claim a trusted task and launch its runner")
    selection = start.add_mutually_exclusive_group(required=True)
    selection.add_argument("--task", type=Path)
    selection.add_argument("--next", action="store_true", help="Select the next trusted M0-M2 task")
    start.add_argument("--max-workers", type=int, default=2, choices=(1, 2))
    start.add_argument("--foreground", action="store_true")

    for name in ("status", "pause", "resume", "stop"):
        control = subparsers.add_parser(name)
        control.add_argument("--run-id")

    authorize = subparsers.add_parser(
        "authorize-auto-merge",
        help="Owner-only one-time enablement; never called by a worker",
    )
    authorize.add_argument("--repository", required=True)
    authorize.add_argument("--confirm", required=True)

    internal = subparsers.add_parser("_run", help=argparse.SUPPRESS)
    internal.add_argument("--run-id", required=True)
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = build_parser().parse_args(arguments)
    root = args.root.resolve()
    state_dir = args.state_dir.resolve() if args.state_dir else None
    service = _service(root, state_dir)

    if args.command == "start":
        if args.next:
            task_path = service.select_next_task_path("NhanDuong21/nyan-shop-bot")
            if task_path is None:
                raise SystemExit("No trusted M0-M2 task has closed dependencies")
        else:
            task_path = args.task if args.task.is_absolute() else root / args.task
        run_id = service.create_run(task_path, max_workers=args.max_workers)
        if args.foreground:
            service.run(run_id)
            print(json.dumps(service.status(run_id), indent=2, default=str))
        else:
            print(json.dumps(_start_background(service, run_id), indent=2, default=str))
        return 0

    if args.command == "_run":
        service.run(args.run_id)
        return 0

    if args.command == "authorize-auto-merge":
        service.authorize_auto_merge(args.repository, args.confirm)
        print(
            json.dumps(
                {
                    "repository": args.repository,
                    "authorized": True,
                    "scope": "low-risk unprotected exact-SHA PASS PRs targeting main only",
                },
                indent=2,
            )
        )
        return 0

    run_id = _resolve_run_id(service, args.run_id)
    if args.command == "status":
        print(json.dumps(service.status(run_id), indent=2, default=str))
        return 0

    if args.command == "resume":
        service.resume_run(run_id)
    else:
        desired = {
            "pause": DesiredState.PAUSED,
            "stop": DesiredState.STOPPED,
        }[args.command]
        service.set_control(run_id, desired)
    status = service.status(run_id)
    if args.command == "resume" and not bool(status["process_alive"]):
        status.update(_start_background(service, run_id))
    print(json.dumps(status, indent=2, default=str))
    return 0


def confirmation_text() -> str:
    """Expose the exact owner sentence without silently applying it."""

    return OWNER_CONFIRMATION
