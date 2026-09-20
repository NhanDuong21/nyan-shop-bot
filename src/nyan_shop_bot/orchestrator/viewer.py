"""Read-only terminal viewer for live runner activity."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from nyan_shop_bot.orchestrator.activity import redact_text
from nyan_shop_bot.orchestrator.adapters import process_matches


class ReplayReader:
    """Open runner state without creating, migrating, or checkpointing it."""

    def __init__(self, state_dir: Path) -> None:
        self.db_path = (state_dir / "state.sqlite3").resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(f"runner state does not exist: {self.db_path}")

    def connect(self) -> sqlite3.Connection:
        uri = f"{self.db_path.as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if not {"events", "runs"}.issubset(tables):
            connection.close()
            raise RuntimeError("runner visibility schema is unavailable")
        return connection

    def runs(self, run_id: str | None) -> list[dict[str, Any]]:
        fields = """
            run_id, task_id, issue_number, branch, base_sha, head_sha, worktree_path,
            worker_kind, phase, pid, process_identity, active_agent_pid,
            active_agent_identity, worker_session_id, reviewer_session_id,
            (SELECT MAX(created_at) FROM events WHERE events.run_id = runs.run_id)
                AS last_event_at
        """
        with self.connect() as connection:
            if run_id is None:
                rows = connection.execute(
                    f"SELECT {fields} FROM runs ORDER BY created_at DESC LIMIT 50"
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT {fields} FROM runs WHERE run_id = ?", (run_id,)
                ).fetchall()
        if run_id is not None and not rows:
            raise KeyError(f"unknown run: {run_id}")
        return [dict(row) for row in rows]

    def latest_cursor(self, run_id: str | None) -> int:
        with self.connect() as connection:
            if run_id is None:
                row = connection.execute("SELECT COALESCE(MAX(event_id), 0) FROM events").fetchone()
            else:
                row = connection.execute(
                    "SELECT COALESCE(MAX(event_id), 0) FROM events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
        assert row is not None
        return int(row[0])

    def history(self, run_id: str | None, limit: int) -> list[dict[str, Any]]:
        where = "WHERE e.run_id = ?" if run_id is not None else ""
        parameters: tuple[object, ...] = (run_id, limit) if run_id is not None else (limit,)
        query = f"""
            SELECT * FROM (
                SELECT e.event_id, e.run_id, e.created_at, e.kind, e.payload_json,
                       r.task_id, r.issue_number, r.branch, r.worktree_path,
                       COALESCE(r.head_sha, r.base_sha) AS commit_sha
                FROM events e JOIN runs r ON r.run_id = e.run_id
                {where}
                ORDER BY e.event_id DESC LIMIT ?
            ) ORDER BY event_id
        """
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_event_row(row) for row in rows]

    def after(
        self,
        cursor: int,
        *,
        run_id: str | None,
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        where = "AND e.run_id = ?" if run_id is not None else ""
        parameters: tuple[object, ...] = (
            (cursor, run_id, limit) if run_id is not None else (cursor, limit)
        )
        query = f"""
            SELECT e.event_id, e.run_id, e.created_at, e.kind, e.payload_json,
                   r.task_id, r.issue_number, r.branch, r.worktree_path,
                   COALESCE(r.head_sha, r.base_sha) AS commit_sha
            FROM events e JOIN runs r ON r.run_id = e.run_id
            WHERE e.event_id > ? {where}
            ORDER BY e.event_id LIMIT ?
        """
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_event_row(row) for row in rows]


def _event_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "cursor": int(row["event_id"]),
        "run_id": str(row["run_id"]),
        "created_at": str(row["created_at"]),
        "kind": str(row["kind"]),
        "payload": payload,
        "task_id": str(row["task_id"]),
        "issue": int(row["issue_number"]),
        "branch": str(row["branch"]),
        "worktree": str(row["worktree_path"]),
        "commit": str(row["commit_sha"]),
    }


def _alive(pid: object, identity: object) -> str:
    if not isinstance(pid, int) or not isinstance(identity, str):
        return "stopped"
    try:
        return "alive" if process_matches(pid, identity) else "stopped"
    except (OSError, RuntimeError):
        return "unknown"


def _state_line(run: dict[str, Any]) -> str:
    controller = _alive(run.get("pid"), run.get("process_identity"))
    agent = _alive(run.get("active_agent_pid"), run.get("active_agent_identity"))
    head = str(run.get("head_sha") or run["base_sha"])
    sessions = []
    if run.get("worker_session_id"):
        sessions.append(f"worker_session={redact_text(run['worker_session_id'], limit=180)}")
    if run.get("reviewer_session_id"):
        sessions.append(f"reviewer_session={redact_text(run['reviewer_session_id'], limit=180)}")
    suffix = f" {' '.join(sessions)}" if sessions else ""
    return (
        f"STATE run={redact_text(run['run_id'], limit=180)} "
        f"task={redact_text(run['task_id'], limit=80)} issue=#{run['issue_number']} "
        f"phase={redact_text(run['phase'], limit=80)} controller={controller} agent={agent} "
        f"adapter={redact_text(run['worker_kind'], limit=80)} "
        f"branch={redact_text(run['branch'], limit=240)} commit={redact_text(head, limit=80)} "
        f"worktree={redact_text(run['worktree_path'], limit=500)} "
        f"last_event={redact_text(run.get('last_event_at') or 'none', limit=100)}{suffix}"
    )


def _event_role(event: dict[str, Any]) -> str:
    payload = event["payload"]
    if event["kind"] == "agent.activity" and payload.get("role") in {"worker", "reviewer"}:
        return str(payload["role"])
    return "runner"


def _format_event(event: dict[str, Any]) -> str:
    payload = event["payload"]
    role = _event_role(event)
    details: list[str] = []
    for field in ("session_id", "invocation", "tool", "status", "verdict", "exit_code"):
        if field in payload:
            details.append(f"{field}={redact_text(payload[field], limit=240)}")
    if isinstance(payload.get("command"), str):
        details.append(f"command={redact_text(payload['command'])}")
    files = payload.get("files")
    if isinstance(files, list):
        rendered = []
        for value in files[:30]:
            if isinstance(value, dict):
                rendered.append(
                    f"{redact_text(value.get('operation', 'changed'), limit=60)}:"
                    f"{redact_text(value.get('path', '?'), limit=240)}"
                )
        if rendered:
            details.append(f"files={','.join(rendered)}")
    usage = payload.get("usage")
    if isinstance(usage, dict):
        actual = ",".join(
            f"{key}={value}" for key, value in usage.items() if isinstance(value, int)
        )
        if actual:
            details.append(f"usage({actual})")
    if isinstance(payload.get("summary"), str):
        details.append(redact_text(payload["summary"]))
    return (
        f"{event['created_at']} cursor={event['cursor']} [{role}] "
        f"{event['task_id']}/#{event['issue']} run={event['run_id']} "
        f"commit={event['commit']} {event['kind']} {' '.join(details)}"
    ).rstrip()


def watch_activity(
    state_dir: Path,
    *,
    run_id: str | None,
    role: str,
    history: int,
    after_cursor: int | None,
    follow: bool,
    poll_seconds: float,
    idle_seconds: float,
    output: TextIO,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    """Render real persisted activity; never starts, resumes, pauses, or stops a run."""

    reader = ReplayReader(state_dir)
    runs = reader.runs(run_id)
    if not runs:
        raise RuntimeError("runner state contains no runs")
    for run in runs:
        print(_state_line(run), file=output, flush=True)

    cursor = after_cursor if after_cursor is not None else 0
    if after_cursor is None and history > 0:
        events = reader.history(run_id, history)
        for event in events:
            cursor = max(cursor, int(event["cursor"]))
            if role == "all" or _event_role(event) == role:
                print(_format_event(event), file=output, flush=True)
    elif after_cursor is None:
        # `--history 0` means start at now, not replay every historical event once
        # follow mode begins polling.
        cursor = reader.latest_cursor(run_id)
    elif after_cursor is not None:
        remaining = max(history, 1)
        while remaining > 0:
            events = reader.after(cursor, run_id=run_id, limit=min(remaining, 250))
            if not events:
                break
            for event in events:
                cursor = int(event["cursor"])
                if role == "all" or _event_role(event) == role:
                    print(_format_event(event), file=output, flush=True)
            remaining -= len(events)
    if not follow:
        print(f"VIEWER_STOPPED cursor={cursor}; no runner control was changed", file=output)
        return cursor

    last_activity_at = time.monotonic()
    last_state = {str(run["run_id"]): _state_line(run) for run in runs}
    try:
        while True:
            events = reader.after(cursor, run_id=run_id)
            if events:
                last_activity_at = time.monotonic()
                for event in events:
                    cursor = int(event["cursor"])
                    if role == "all" or _event_role(event) == role:
                        print(_format_event(event), file=output, flush=True)
                continue
            current_runs = reader.runs(run_id)
            state_changed = False
            for run in current_runs:
                line = _state_line(run)
                key = str(run["run_id"])
                if last_state.get(key) != line:
                    print(line, file=output, flush=True)
                    last_state[key] = line
                    state_changed = True
            now = time.monotonic()
            if not state_changed and now - last_activity_at >= idle_seconds:
                print(
                    f"NO_NEW_ACTIVITY cursor={cursor}; liveness is shown separately above",
                    file=output,
                    flush=True,
                )
                last_activity_at = now
            sleeper(poll_seconds)
    except KeyboardInterrupt:
        print(f"VIEWER_CLOSED cursor={cursor}; worker was not signaled", file=output)
        return cursor
