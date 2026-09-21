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

from nyan_shop_bot.orchestrator.models import (
    DesiredState,
    RunPhase,
    TaskSpec,
    UsageAccounting,
)

RUN_FIELDS = {
    "phase",
    "desired_state",
    "pid",
    "process_identity",
    "active_agent_identity",
    "active_agent_completion_path",
    "active_agent_nonce",
    "worker_parent_sha",
    "merge_sha",
    "deadline_at",
    "review_started_head_sha",
    "worker_accounted_events_sha256",
    "reviewer_accounted_events_sha256",
    "worker_cumulative_tokens",
    "worker_enforceable_tokens",
    "reviewer_enforceable_tokens",
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
                    max_workers INTEGER NOT NULL DEFAULT 1 CHECK(max_workers IN (1, 2)),
                    pid INTEGER,
                    process_identity TEXT,
                    process_token TEXT,
                    process_started_at TEXT,
                    process_heartbeat_at TEXT,
                    active_agent_pid INTEGER,
                    active_agent_identity TEXT,
                    active_agent_completion_path TEXT,
                    active_agent_nonce TEXT,
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
                    worker_cumulative_tokens INTEGER NOT NULL DEFAULT 0,
                    worker_enforceable_tokens INTEGER,
                    reviewer_enforceable_tokens INTEGER,
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
                    payload_json TEXT NOT NULL,
                    source_key TEXT
                );
                CREATE TABLE IF NOT EXISTS invocation_usage (
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    invocation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('worker', 'reviewer')),
                    session_id TEXT NOT NULL,
                    terminal_events_sha256 TEXT NOT NULL,
                    raw_input_tokens INTEGER CHECK(raw_input_tokens >= 0),
                    cached_input_tokens INTEGER CHECK(cached_input_tokens >= 0),
                    fresh_input_tokens INTEGER CHECK(fresh_input_tokens >= 0),
                    raw_output_tokens INTEGER CHECK(raw_output_tokens >= 0),
                    reasoning_tokens INTEGER CHECK(reasoning_tokens >= 0),
                    raw_provider_total INTEGER CHECK(raw_provider_total >= 0),
                    normalization_state TEXT NOT NULL
                        CHECK(normalization_state IN ('COMPLETE', 'PARTIAL', 'UNKNOWN')),
                    enforceable_tokens INTEGER CHECK(enforceable_tokens >= 0),
                    enforcement_basis TEXT NOT NULL CHECK(
                        enforcement_basis IN (
                            'CODEX_COMPONENTS', 'PROVIDER_CUMULATIVE', 'UNAVAILABLE'
                        )
                    ),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, invocation_id)
                );
                """
            )
            self._ensure_run_columns(connection)
            self._ensure_event_columns(connection)

    @staticmethod
    def _ensure_run_columns(connection: sqlite3.Connection) -> None:
        """Add fail-closed columns when opening pre-runner-fix local state."""

        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(runs)").fetchall()}
        additions = {
            "task_json": "TEXT",
            "task_sha256": "TEXT",
            "process_token": "TEXT",
            "process_identity": "TEXT",
            "process_started_at": "TEXT",
            "process_heartbeat_at": "TEXT",
            "active_agent_pid": "INTEGER",
            "active_agent_identity": "TEXT",
            "active_agent_completion_path": "TEXT",
            "active_agent_nonce": "TEXT",
            "active_agent_started_at": "TEXT",
            "deadline_at": "TEXT",
            "worker_parent_sha": "TEXT",
            "merge_sha": "TEXT",
            "review_started_head_sha": "TEXT",
            "worker_accounted_events_sha256": "TEXT",
            "reviewer_accounted_events_sha256": "TEXT",
            "worker_cumulative_tokens": "INTEGER NOT NULL DEFAULT 0",
            "worker_enforceable_tokens": "INTEGER",
            "reviewer_enforceable_tokens": "INTEGER",
            "max_workers": "INTEGER NOT NULL DEFAULT 1",
        }
        for name, kind in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {kind}")

    @staticmethod
    def _ensure_event_columns(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(events)").fetchall()
        }
        if "source_key" not in columns:
            connection.execute("ALTER TABLE events ADD COLUMN source_key TEXT")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS one_event_per_stream_position
            ON events(run_id, source_key) WHERE source_key IS NOT NULL
            """
        )

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
                    desired_state, max_workers, created_at, updated_at, deadline_at,
                    worker_cumulative_tokens, worker_enforceable_tokens,
                    reviewer_enforceable_tokens
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    max_workers,
                    now,
                    now,
                    deadline_at,
                    0,
                    0,
                    0,
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

    def acquire_process_lease(
        self,
        run_id: str,
        *,
        pid: int,
        identity: str,
        token: str,
    ) -> None:
        if not identity:
            raise ValueError("runner process identity is required")
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
                SET pid = ?, process_identity = ?, process_token = ?, process_started_at = ?,
                    process_heartbeat_at = ?, updated_at = ?
                WHERE run_id = ? AND process_token IS NULL
                """,
                (pid, identity, token, now, now, now, run_id),
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

    def set_active_agent(
        self,
        run_id: str,
        *,
        token: str,
        pid: int,
        identity: str,
        completion_path: str,
        nonce: str,
    ) -> None:
        if not identity or not completion_path or not nonce:
            raise ValueError("agent identity, containment path, and nonce are required")
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET active_agent_pid = ?, active_agent_identity = ?,
                    active_agent_completion_path = ?, active_agent_nonce = ?,
                    active_agent_started_at = ?, updated_at = ?
                WHERE run_id = ? AND process_token = ? AND active_agent_pid IS NULL
                """,
                (pid, identity, completion_path, nonce, now, now, run_id, token),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("cannot attach agent process to the current runner lease")
            self._append_event(connection, run_id, "agent.process_started", {"pid": pid})

    def clear_active_agent(
        self,
        run_id: str,
        *,
        token: str,
        pid: int,
        identity: str,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET active_agent_pid = NULL, active_agent_identity = NULL,
                    active_agent_completion_path = NULL, active_agent_nonce = NULL,
                    active_agent_started_at = NULL,
                    updated_at = ?
                WHERE run_id = ? AND process_token = ? AND active_agent_pid = ?
                    AND active_agent_identity = ?
                """,
                (now, run_id, token, pid, identity),
            )
            if cursor.rowcount == 1:
                self._append_event(connection, run_id, "agent.process_finished", {"pid": pid})

    def clear_stale_active_agent(
        self,
        run_id: str,
        *,
        token: str,
        pid: int,
        identity: str,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE runs
                SET active_agent_pid = NULL, active_agent_identity = NULL,
                    active_agent_completion_path = NULL, active_agent_nonce = NULL,
                    active_agent_started_at = NULL,
                    updated_at = ?
                WHERE run_id = ? AND process_token = ? AND active_agent_pid = ?
                    AND active_agent_identity = ?
                """,
                (now, run_id, token, pid, identity),
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
                SET pid = NULL, process_identity = NULL, process_token = NULL,
                    process_started_at = NULL,
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

    def clear_stale_process_lease(
        self,
        run_id: str,
        *,
        pid: int,
        identity: str,
        token: str,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE runs
                SET pid = NULL, process_identity = NULL, process_token = NULL,
                    process_started_at = NULL,
                    process_heartbeat_at = NULL, updated_at = ?
                WHERE run_id = ? AND pid = ? AND process_identity = ? AND process_token = ?
                """,
                (now, run_id, pid, identity, token),
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

    def record_invocation_usage(
        self,
        run_id: str,
        *,
        invocation_id: str,
        role: str,
        session_id: str,
        terminal_events_sha256: str,
        accounting: UsageAccounting,
        cumulative_provider_total: bool = False,
    ) -> dict[str, Any]:
        """Atomically account one terminal stream, or return its prior ledger record."""

        if role not in {"worker", "reviewer"}:
            raise ValueError(f"unsupported invocation role: {role}")
        if not invocation_id or len(invocation_id) > 200:
            raise ValueError("invocation identity must be between 1 and 200 characters")
        if len(terminal_events_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in terminal_events_sha256
        ):
            raise ValueError("terminal event evidence must be a lowercase SHA-256 digest")
        if not session_id:
            raise ValueError("usage accounting requires a session ID")

        raw_values = {
            "raw_input_tokens": accounting.raw_input_tokens,
            "cached_input_tokens": accounting.cached_input_tokens,
            "fresh_input_tokens": accounting.fresh_input_tokens,
            "raw_output_tokens": accounting.raw_output_tokens,
            "reasoning_tokens": accounting.reasoning_tokens,
            "raw_provider_total": accounting.raw_provider_total,
            "normalization_state": accounting.normalization_state.value,
        }
        basis = (
            "PROVIDER_CUMULATIVE"
            if cumulative_provider_total
            else (
                "CODEX_COMPONENTS" if accounting.enforceable_tokens is not None else "UNAVAILABLE"
            )
        )
        now = utc_now()
        role_total_field = f"{role}_enforceable_tokens"
        cumulative_field = "worker_cumulative_tokens"
        session_field = f"{role}_session_id"
        legacy_digest_field = f"{role}_accounted_events_sha256"
        if cumulative_provider_total and role != "worker":
            raise ValueError("cumulative provider accounting is supported only for workers")

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM invocation_usage
                WHERE run_id = ? AND invocation_id = ?
                """,
                (run_id, invocation_id),
            ).fetchone()
            if existing is not None:
                expected = {
                    "role": role,
                    "session_id": session_id,
                    "terminal_events_sha256": terminal_events_sha256,
                    "enforcement_basis": basis,
                    **raw_values,
                }
                if any(existing[key] != value for key, value in expected.items()):
                    raise RuntimeError("persisted invocation usage does not match replay evidence")
                if not cumulative_provider_total and (
                    existing["enforceable_tokens"] != accounting.enforceable_tokens
                ):
                    raise RuntimeError("persisted invocation policy value changed during replay")
                run = connection.execute(
                    f"SELECT {role_total_field} FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if run is None:
                    raise KeyError(f"unknown run: {run_id}")
                return {
                    **dict(existing),
                    "role_enforceable_total": run[role_total_field],
                    "replayed": True,
                }

            run = connection.execute(
                f"""
                SELECT total_tokens, {role_total_field}, {cumulative_field}, {session_field}
                FROM runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise KeyError(f"unknown run: {run_id}")
            if run[role_total_field] is None:
                raise RuntimeError(
                    "run predates role-isolated usage accounting and cannot be resumed"
                )
            if (
                role == "worker"
                and run[session_field] is not None
                and str(run[session_field]) != session_id
            ):
                raise RuntimeError("worker usage session changed during accounting")

            enforceable_tokens = accounting.enforceable_tokens
            next_cumulative: int | None = None
            if cumulative_provider_total:
                if accounting.raw_provider_total is None:
                    raise RuntimeError("cumulative provider usage omitted its raw total")
                if run[cumulative_field] is None:
                    raise RuntimeError(
                        "run predates cumulative provider accounting and cannot be resumed"
                    )
                prior_cumulative = int(run[cumulative_field])
                if accounting.raw_provider_total < prior_cumulative:
                    raise RuntimeError("provider cumulative usage moved backwards")
                enforceable_tokens = accounting.raw_provider_total - prior_cumulative
                next_cumulative = accounting.raw_provider_total

            role_total = int(run[role_total_field])
            legacy_total = int(run["total_tokens"])
            if enforceable_tokens is not None:
                role_total += enforceable_tokens
                legacy_total += enforceable_tokens

            connection.execute(
                """
                INSERT INTO invocation_usage (
                    run_id, invocation_id, role, session_id, terminal_events_sha256,
                    raw_input_tokens, cached_input_tokens, fresh_input_tokens,
                    raw_output_tokens, reasoning_tokens, raw_provider_total,
                    normalization_state, enforceable_tokens, enforcement_basis, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    invocation_id,
                    role,
                    session_id,
                    terminal_events_sha256,
                    accounting.raw_input_tokens,
                    accounting.cached_input_tokens,
                    accounting.fresh_input_tokens,
                    accounting.raw_output_tokens,
                    accounting.reasoning_tokens,
                    accounting.raw_provider_total,
                    accounting.normalization_state,
                    enforceable_tokens,
                    basis,
                    now,
                ),
            )
            cumulative_assignment = (
                f", {cumulative_field} = ?" if next_cumulative is not None else ""
            )
            parameters: list[object] = [
                role_total,
                legacy_total,
                session_id,
                terminal_events_sha256,
            ]
            if next_cumulative is not None:
                parameters.append(next_cumulative)
            parameters.extend((now, run_id))
            connection.execute(
                f"""
                UPDATE runs
                SET {role_total_field} = ?, total_tokens = ?, {session_field} = ?,
                    {legacy_digest_field} = ? {cumulative_assignment}, updated_at = ?
                WHERE run_id = ?
                """,
                parameters,
            )
            self._append_event(
                connection,
                run_id,
                "usage.accounted",
                {
                    "invocation_id": invocation_id,
                    "role": role,
                    "session_id": session_id,
                    "terminal_events_sha256": terminal_events_sha256,
                    **raw_values,
                    "enforceable_tokens": enforceable_tokens,
                    "enforcement_basis": basis,
                    "role_enforceable_total": role_total,
                },
            )
            return {
                "run_id": run_id,
                "invocation_id": invocation_id,
                "role": role,
                "session_id": session_id,
                "terminal_events_sha256": terminal_events_sha256,
                **raw_values,
                "enforceable_tokens": enforceable_tokens,
                "enforcement_basis": basis,
                "created_at": now,
                "role_enforceable_total": role_total,
                "replayed": False,
            }

    def has_unenforceable_usage(self, run_id: str) -> bool:
        """Return whether any completed invocation lacks a policy token value."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM invocation_usage
                WHERE run_id = ? AND enforceable_tokens IS NULL LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return row is not None

    def invocation_usage(self, run_id: str) -> list[dict[str, Any]]:
        """Return the durable usage ledger in accounting order."""

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM invocation_usage
                WHERE run_id = ? ORDER BY rowid
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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

    def record_ci_fix_request(
        self,
        run_id: str,
        *,
        expected_phase: RunPhase,
        expected_head: str,
        expected_fix_rounds: int,
        next_fix_round: int,
        ci_run_id: int,
        ci_url: str,
        request: dict[str, object],
    ) -> None:
        """Atomically checkpoint one exact-HEAD CI failure and its fix transition."""

        if expected_phase not in {RunPhase.CI_WAITING, RunPhase.BLOCKED}:
            raise ValueError("CI fix requests require CI_WAITING or legacy BLOCKED state")
        if next_fix_round != expected_fix_rounds + 1:
            raise ValueError("CI fix round must advance exactly once")
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT phase, desired_state, head_sha, fix_rounds,
                       repository, issue_number, max_workers
                FROM runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
            if (
                str(row["phase"]) != expected_phase.value
                or str(row["desired_state"]) != DesiredState.RUNNING.value
                or str(row["head_sha"]) != expected_head
                or int(row["fix_rounds"]) != expected_fix_rounds
            ):
                raise RuntimeError("CI fix checkpoint changed before it could be recorded")
            if expected_phase is RunPhase.BLOCKED:
                self._reactivate_claim_in_transaction(
                    connection,
                    run_id=run_id,
                    repository=str(row["repository"]),
                    issue_number=int(row["issue_number"]),
                    max_workers=int(row["max_workers"]),
                )
            connection.execute(
                """
                UPDATE runs
                SET phase = ?, fix_rounds = ?, ci_run_id = ?, ci_url = ?,
                    reviewed_head_sha = NULL, review_started_head_sha = NULL,
                    last_error = NULL, ended_at = NULL, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    RunPhase.FIX_REQUESTED,
                    next_fix_round,
                    ci_run_id,
                    ci_url,
                    now,
                    run_id,
                ),
            )
            self._append_event(connection, run_id, "ci.failed", request)
            self._append_event(
                connection,
                run_id,
                "phase.fix_requested",
                {
                    "head_sha": expected_head,
                    "run_id": ci_run_id,
                    "failed_jobs": request.get("failed_jobs", []),
                    "fix_round": next_fix_round,
                },
            )

    def recover_blocked_ci_pass(
        self,
        run_id: str,
        *,
        expected_head: str,
        ci_run_id: int,
        ci_url: str,
    ) -> None:
        """Atomically resume a legacy CI-blocked run when a newer exact-HEAD rerun passed."""

        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT phase, desired_state, head_sha,
                       repository, issue_number, max_workers
                FROM runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
            if (
                str(row["phase"]) != RunPhase.BLOCKED.value
                or str(row["desired_state"]) != DesiredState.RUNNING.value
                or str(row["head_sha"]) != expected_head
            ):
                raise RuntimeError("CI recovery checkpoint changed before it could be recorded")
            self._reactivate_claim_in_transaction(
                connection,
                run_id=run_id,
                repository=str(row["repository"]),
                issue_number=int(row["issue_number"]),
                max_workers=int(row["max_workers"]),
            )
            connection.execute(
                """
                UPDATE runs
                SET phase = ?, ci_run_id = ?, ci_url = ?, last_error = NULL,
                    ended_at = NULL, reviewed_head_sha = NULL,
                    review_started_head_sha = NULL, updated_at = ?
                WHERE run_id = ?
                """,
                (RunPhase.REVIEW_RUNNING, ci_run_id, ci_url, now, run_id),
            )
            self._append_event(
                connection,
                run_id,
                "ci.passed",
                {"head_sha": expected_head, "url": ci_url, "recovered": True},
            )
            self._append_event(connection, run_id, "phase.review_running", {})

    def set_desired_state(self, run_id: str, desired_state: DesiredState) -> None:
        self.update_run(run_id, desired_state=desired_state)
        self.append_event(run_id, "control.requested", {"desired_state": desired_state})

    def append_event(self, run_id: str, kind: str, payload: dict[str, object]) -> None:
        with self.connect() as connection:
            self._append_event(connection, run_id, kind, payload)

    def append_activity_event(
        self,
        run_id: str,
        payload: dict[str, object],
        *,
        source_key: str,
        session_field: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        """Insert one idempotent live event with a short lock budget."""

        if session_field not in {None, "worker_session_id", "reviewer_session_id"}:
            raise ValueError("invalid live session field")
        connection = sqlite3.connect(self.db_path, timeout=0.1)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 100")
        try:
            connection.execute("BEGIN IMMEDIATE")
            if session_field is not None and session_id is not None:
                row = connection.execute(
                    f"SELECT {session_field} FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown run: {run_id}")
                persisted = row[0]
                if persisted is not None and str(persisted) != session_id:
                    raise RuntimeError("live stream changed the persisted session")
                if persisted is None:
                    connection.execute(
                        f"UPDATE runs SET {session_field} = ?, updated_at = ? WHERE run_id = ?",
                        (session_id, utc_now(), run_id),
                    )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO events(
                    run_id, created_at, kind, payload_json, source_key
                ) VALUES (?, ?, 'agent.activity', ?, ?)
                """,
                (run_id, utc_now(), json.dumps(payload, sort_keys=True), source_key),
            )
            connection.commit()
            return cursor.rowcount == 1
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

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

    @classmethod
    def _reactivate_claim_in_transaction(
        cls,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        repository: str,
        issue_number: int,
        max_workers: int,
    ) -> None:
        """Reserve a legacy recovery inside the same transaction as its phase change."""

        if not 1 <= max_workers <= 2:
            raise RuntimeError("persisted writer limit is invalid")
        claim = connection.execute(
            "SELECT active FROM claims WHERE run_id = ?", (run_id,)
        ).fetchone()
        if claim is None:
            raise RuntimeError("run has no durable claim to reactivate")
        if bool(claim["active"]):
            raise RuntimeError("run claim is already active")
        conflicting = connection.execute(
            """
            SELECT run_id FROM claims
            WHERE repository = ? AND issue_number = ? AND active = 1
            """,
            (repository, issue_number),
        ).fetchone()
        if conflicting is not None:
            raise RuntimeError(f"issue already has active run {conflicting['run_id']}")
        active_count = int(
            connection.execute("SELECT COUNT(*) FROM claims WHERE active = 1").fetchone()[0]
        )
        if active_count >= max_workers:
            raise RuntimeError(f"writer limit reached ({active_count}/{max_workers})")
        cursor = connection.execute(
            """
            UPDATE claims
            SET active = 1, claimed_at = ?, released_at = NULL
            WHERE run_id = ? AND active = 0
            """,
            (utc_now(), run_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("claim changed before it could be reactivated")
        cls._append_event(connection, run_id, "claim.reactivated", {})

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
