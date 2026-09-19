"""SQLite persistence for resumable runs, claims, and audit events."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nyan_shop_bot.orchestrator.models import DesiredState, RunPhase, TaskSpec

RUN_FIELDS = {
    "phase",
    "desired_state",
    "pid",
    "worker_parent_sha",
    "merge_sha",
    "deadline_at",
    "review_started_head_sha",
    "worker_accounted_events_sha256",
    "reviewer_accounted_events_sha256",
    "worker_session_id",
    "reviewer_session_id",
    "head_sha",
    "reviewed_head_sha",
    "pr_number",
    "pr_url",
    "ci_run_id",
    "ci_url",
    "fix_rounds",
    "agent_invocations",
    "total_tokens",
    "last_error",
    "ended_at",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def freeze_task(task: TaskSpec) -> tuple[str, str]:
    """Return a canonical task snapshot and its tamper-evident digest."""

    snapshot = json.dumps(task.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    return snapshot, digest


class StateStore:
    """Small transactional state store shared by runner control processes."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir.resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "state.sqlite3"
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    task_path TEXT NOT NULL,
                    task_json TEXT,
                    task_sha256 TEXT,
                    issue_number INTEGER NOT NULL,
                    repository TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    base_ref TEXT NOT NULL,
                    base_sha TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    worker_kind TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    desired_state TEXT NOT NULL,
                    pid INTEGER,
                    process_token TEXT,
                    process_started_at TEXT,
                    process_heartbeat_at TEXT,
                    active_agent_pid INTEGER,
                    active_agent_started_at TEXT,
                    worker_session_id TEXT,
                    reviewer_session_id TEXT,
                    head_sha TEXT,
                    reviewed_head_sha TEXT,
                    pr_number INTEGER,
                    pr_url TEXT,
                    ci_run_id INTEGER,
                    ci_url TEXT,
                    fix_rounds INTEGER NOT NULL DEFAULT 0,
                    agent_invocations INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    worker_parent_sha TEXT,
                    merge_sha TEXT,
                    review_started_head_sha TEXT,
                    worker_accounted_events_sha256 TEXT,
                    reviewer_accounted_events_sha256 TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deadline_at TEXT,
                    ended_at TEXT
                );
                CREATE TABLE IF NOT EXISTS claims (
                    repository TEXT NOT NULL,
                    issue_number INTEGER NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    active INTEGER NOT NULL CHECK(active IN (0, 1)),
                    claimed_at TEXT NOT NULL,
                    released_at TEXT,
                    PRIMARY KEY (repository, issue_number, run_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_issue_claim
                    ON claims(repository, issue_number) WHERE active = 1;
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            self._ensure_run_columns(connection)

    @staticmethod
    def _ensure_run_columns(connection: sqlite3.Connection) -> None:
        """Add fail-closed columns when opening pre-runner-fix local state."""

        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(runs)").fetchall()}
        additions = {
            "task_json": "TEXT",
            "task_sha256": "TEXT",
            "process_token": "TEXT",
            "process_started_at": "TEXT",
            "process_heartbeat_at": "TEXT",
            "active_agent_pid": "INTEGER",
            "active_agent_started_at": "TEXT",
            "deadline_at": "TEXT",
            "worker_parent_sha": "TEXT",
            "merge_sha": "TEXT",
            "review_started_head_sha": "TEXT",
            "worker_accounted_events_sha256": "TEXT",
            "reviewer_accounted_events_sha256": "TEXT",
        }
        for name, kind in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {kind}")

    def create_run(
        self,
        *,
        run_id: str,
        task: TaskSpec,
        task_path: Path,
        base_sha: str,
        worktree_path: Path,
        max_workers: int,
    ) -> None:
        now = utc_now()
        deadline_at = (
            datetime.now(UTC) + timedelta(seconds=task.budget.max_elapsed_seconds)
        ).isoformat()
        task_json, task_sha256 = freeze_task(task)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active_count = int(
                connection.execute("SELECT COUNT(*) FROM claims WHERE active = 1").fetchone()[0]
            )
            if active_count >= max_workers:
                raise RuntimeError(f"writer limit reached ({active_count}/{max_workers})")
            duplicate = connection.execute(
                "SELECT run_id FROM runs WHERE task_id = ? AND phase NOT IN (?, ?, ?)",
                (task.task_id, RunPhase.COMPLETED, RunPhase.BLOCKED, RunPhase.STOPPED),
            ).fetchone()
            if duplicate is not None:
                raise RuntimeError(
                    f"task {task.task_id} already has active run {duplicate['run_id']}"
                )
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, task_id, task_path, task_json, task_sha256,
                    issue_number, repository, branch,
                    base_ref, base_sha, worktree_path, worker_kind, phase,
                    desired_state, created_at, updated_at, deadline_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    task.task_id,
                    str(task_path),
                    task_json,
                    task_sha256,
                    task.issue_number,
                    task.repository,
                    task.branch,
                    task.base_ref,
                    base_sha,
                    str(worktree_path),
                    task.worker,
                    RunPhase.CREATED,
                    DesiredState.RUNNING,
                    now,
                    now,
                    deadline_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO claims(repository, issue_number, run_id, active, claimed_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (task.repository, task.issue_number, run_id, now),
            )
            self._append_event(connection, run_id, "run.created", {"base_sha": base_sha})

    def acquire_process_lease(self, run_id: str, *, pid: int, token: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT process_token FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
            if row["process_token"] is not None:
                raise RuntimeError("run already has an active process lease")
            connection.execute(
                """
                UPDATE runs
                SET pid = ?, process_token = ?, process_started_at = ?,
                    process_heartbeat_at = ?, updated_at = ?
                WHERE run_id = ? AND process_token IS NULL
                """,
                (pid, token, now, now, now, run_id),
            )
            self._append_event(connection, run_id, "process.lease_acquired", {"pid": pid})

    def heartbeat_process_lease(self, run_id: str, token: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs SET process_heartbeat_at = ?, updated_at = ?
                WHERE run_id = ? AND process_token = ?
                """,
                (now, now, run_id, token),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("runner process lease was lost")

    def set_active_agent(self, run_id: str, *, token: str, pid: int) -> None:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET active_agent_pid = ?, active_agent_started_at = ?, updated_at = ?
                WHERE run_id = ? AND process_token = ? AND active_agent_pid IS NULL
                """,
                (pid, now, now, run_id, token),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("cannot attach agent process to the current runner lease")
            self._append_event(connection, run_id, "agent.process_started", {"pid": pid})

    def clear_active_agent(self, run_id: str, *, token: str, pid: int) -> None:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET active_agent_pid = NULL, active_agent_started_at = NULL, updated_at = ?
                WHERE run_id = ? AND process_token = ? AND active_agent_pid = ?
                """,
                (now, run_id, token, pid),
            )
            if cursor.rowcount == 1:
                self._append_event(connection, run_id, "agent.process_finished", {"pid": pid})

    def clear_stale_active_agent(self, run_id: str, *, token: str, pid: int) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE runs
                SET active_agent_pid = NULL, active_agent_started_at = NULL, updated_at = ?
                WHERE run_id = ? AND process_token = ? AND active_agent_pid = ?
                """,
                (now, run_id, token, pid),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("stale agent process changed before it could be cleared")
            self._append_event(connection, run_id, "agent.stale_process_cleared", {"pid": pid})

    def release_process_lease(self, run_id: str, token: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET pid = NULL, process_token = NULL, process_started_at = NULL,
                    process_heartbeat_at = NULL, updated_at = ?
                WHERE run_id = ? AND process_token = ? AND active_agent_pid IS NULL
                """,
                (now, run_id, token),
            )
            if cursor.rowcount == 1:
                self._append_event(connection, run_id, "process.lease_released", {})
            else:
                active = connection.execute(
                    "SELECT active_agent_pid FROM runs WHERE run_id = ? AND process_token = ?",
                    (run_id, token),
                ).fetchone()
                if active is not None and active["active_agent_pid"] is not None:
                    raise RuntimeError("cannot release runner lease while an agent is active")

    def clear_stale_process_lease(self, run_id: str, *, pid: int, token: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE runs
                SET pid = NULL, process_token = NULL, process_started_at = NULL,
                    process_heartbeat_at = NULL, updated_at = ?
                WHERE run_id = ? AND pid = ? AND process_token = ?
                """,
                (now, run_id, pid, token),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("stale process lease changed before it could be cleared")
            self._append_event(connection, run_id, "process.stale_lease_cleared", {"pid": pid})

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        return dict(row)

    def latest_run_id(self) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise KeyError("no runner state exists")
        return str(row["run_id"])

    def update_run(self, run_id: str, **values: object) -> None:
        unknown = set(values) - RUN_FIELDS
        if unknown:
            raise ValueError(f"unsupported run fields: {sorted(unknown)}")
        if not values:
            return
        assignments = ", ".join(f"{name} = ?" for name in values)
        parameters = [*values.values(), utc_now(), run_id]
        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE runs SET {assignments}, updated_at = ? WHERE run_id = ?",
                parameters,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown run: {run_id}")

    def transition(
        self,
        run_id: str,
        phase: RunPhase,
        *,
        payload: dict[str, object] | None = None,
    ) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE runs SET phase = ?, updated_at = ? WHERE run_id = ?",
                (phase, utc_now(), run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown run: {run_id}")
            self._append_event(connection, run_id, f"phase.{phase.value.lower()}", payload or {})

    def set_desired_state(self, run_id: str, desired_state: DesiredState) -> None:
        self.update_run(run_id, desired_state=desired_state)
        self.append_event(run_id, "control.requested", {"desired_state": desired_state})

    def append_event(self, run_id: str, kind: str, payload: dict[str, object]) -> None:
        with self.connect() as connection:
            self._append_event(connection, run_id, kind, payload)

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        run_id: str,
        kind: str,
        payload: dict[str, object],
    ) -> None:
        connection.execute(
            "INSERT INTO events(run_id, created_at, kind, payload_json) VALUES (?, ?, ?, ?)",
            (run_id, utc_now(), kind, json.dumps(payload, sort_keys=True)),
        )

    def events(self, run_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, created_at, kind, payload_json
                FROM events WHERE run_id = ? ORDER BY event_id DESC LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
        return [
            {
                "event_id": int(row["event_id"]),
                "created_at": str(row["created_at"]),
                "kind": str(row["kind"]),
                "payload": json.loads(str(row["payload_json"])),
            }
            for row in reversed(rows)
        ]

    def release_claim(self, run_id: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                "UPDATE claims SET active = 0, released_at = ? WHERE run_id = ? AND active = 1",
                (now, run_id),
            )
            self._append_event(connection, run_id, "claim.released", {})

    def active_claims(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT repository, issue_number, run_id, claimed_at
                FROM claims WHERE active = 1 ORDER BY claimed_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def task_has_run(self, task_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM runs WHERE task_id = ? LIMIT 1", (task_id,)
            ).fetchone()
        return row is not None
