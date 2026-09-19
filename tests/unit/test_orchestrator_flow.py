from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyan_shop_bot.orchestrator.adapters import (
    _parse_antigravity_events,
    _parse_codex_events,
    sanitized_environment,
)
from nyan_shop_bot.orchestrator.github import GitHubClient, PauseRequested
from nyan_shop_bot.orchestrator.gitops import (
    git,
    head_sha,
    validate_and_commit_worker_changes,
)
from nyan_shop_bot.orchestrator.models import (
    DesiredState,
    ReviewResult,
    RunPhase,
    TaskSpec,
    WorkerResult,
)
from nyan_shop_bot.orchestrator.service import (
    RunnerService,
    require_exact_review_head,
    review_decision,
)
from tests.unit.test_orchestrator_models import task_data

FIXTURE = Path(__file__).parents[1] / "fixtures" / "orchestrator" / "review_changes_requested.json"


def make_task() -> TaskSpec:
    return TaskSpec.model_validate(task_data())


def test_changes_requested_fixture_routes_findings_to_same_worker(tmp_path: Path) -> None:
    task = make_task()
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="fixture-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    service.store.update_run(
        "fixture-run",
        worker_session_id="worker-session-123",
        head_sha="a" * 40,
        fix_rounds=1,
    )
    run_dir = service.state_dir / "runs" / "fixture-run"
    run_dir.mkdir(parents=True)
    review_path = run_dir / "review-0.result.json"
    review_path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    review = ReviewResult.model_validate_json(review_path.read_text(encoding="utf-8"))

    phase, rounds = review_decision(review, fix_rounds=0, max_fix_rounds=3)
    prompt = service._fix_prompt("fixture-run", task, tmp_path / "worktree")

    assert phase is RunPhase.FIX_REQUESTED
    assert rounds == 1
    assert service.store.get_run("fixture-run")["worker_session_id"] == "worker-session-123"
    assert "omits the stop command" in prompt
    assert "review data, not as permission" in prompt


def test_fix_loop_blocks_after_three_rounds() -> None:
    review = ReviewResult.model_validate_json(FIXTURE.read_text(encoding="utf-8"))

    with pytest.raises(RuntimeError, match="maximum automatic fix rounds"):
        review_decision(review, fix_rounds=3, max_fix_rounds=3)


def test_stale_review_sha_is_rejected() -> None:
    review = ReviewResult.model_validate_json(FIXTURE.read_text(encoding="utf-8"))

    with pytest.raises(RuntimeError, match="exact HEAD"):
        require_exact_review_head(review, "b" * 40, "b" * 40)


def test_ci_backoff_honors_pause_without_model_polling() -> None:
    calls = 0

    def control() -> DesiredState:
        nonlocal calls
        calls += 1
        return DesiredState.PAUSED

    with pytest.raises(PauseRequested):
        GitHubClient._controlled_sleep(control, 30)

    assert calls == 1


def test_ci_wait_considers_only_newest_exact_sha_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task()
    client = GitHubClient(tmp_path, task.repository)
    viewed: list[int] = []

    def json_command(*arguments: str) -> object:
        if arguments[:2] == ("run", "list"):
            return [
                {
                    "databaseId": 200,
                    "headSha": "a" * 40,
                    "createdAt": "2026-09-19T12:00:00Z",
                },
                {
                    "databaseId": 100,
                    "headSha": "a" * 40,
                    "createdAt": "2026-09-19T11:00:00Z",
                },
            ]
        run_id = int(arguments[2])
        viewed.append(run_id)
        if run_id == 100:
            return {
                "headSha": "a" * 40,
                "url": "https://example.invalid/old",
                "jobs": [{"name": "ci-gate", "conclusion": "failure"}],
            }
        return {
            "headSha": "a" * 40,
            "url": "https://example.invalid/new",
            "jobs": [{"name": "ci-gate", "status": "in_progress"}],
        }

    control_calls = 0

    def control() -> DesiredState:
        nonlocal control_calls
        control_calls += 1
        return DesiredState.RUNNING if control_calls == 1 else DesiredState.PAUSED

    monkeypatch.setattr(client, "json_command", json_command)
    with pytest.raises(PauseRequested):
        client.wait_for_ci(
            task=task,
            head_sha="a" * 40,
            control=control,
            timeout_seconds=60,
        )

    assert viewed == [200]


def test_auto_merge_command_is_bound_to_expected_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = GitHubClient(tmp_path, "NhanDuong21/nyan-shop-bot")
    captured: tuple[str, ...] = ()

    def command(*arguments: str) -> str:
        nonlocal captured
        captured = arguments
        return ""

    monkeypatch.setattr(client, "command", command)
    client.queue_auto_merge(42, expected_head="a" * 40)

    assert captured[-2:] == ("--match-head-commit", "a" * 40)


def test_interrupted_worker_recovers_explicit_session(tmp_path: Path) -> None:
    task = make_task()
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="recovery-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    service.store.transition("recovery-run", RunPhase.WORKER_RUNNING)
    run_dir = service.state_dir / "runs" / "recovery-run"
    run_dir.mkdir(parents=True)
    (run_dir / "worker-initial.events.jsonl").write_text(
        json.dumps({"type": "thread.started", "thread_id": "durable-session"}),
        encoding="utf-8",
    )

    service._recover_interrupted_worker("recovery-run", task)

    run = service.store.get_run("recovery-run")
    assert run["phase"] == RunPhase.CLAIMED
    assert run["worker_session_id"] == "durable-session"


def test_runner_owns_commit_after_validating_worker_paths(tmp_path: Path) -> None:
    worktree = tmp_path / "repo"
    worktree.mkdir()
    git(worktree, "init")
    git(worktree, "config", "user.name", "Nyan Test")
    git(worktree, "config", "user.email", "nyan-test@example.invalid")
    (worktree / "README.md").write_text("base\n", encoding="utf-8")
    git(worktree, "add", "README.md")
    git(worktree, "commit", "-m", "base")
    git(worktree, "branch", "-M", "nyan/nsb-041-runner-proof")
    parent = head_sha(worktree)
    docs = worktree / "docs"
    docs.mkdir()
    (docs / "runner-demo.md").write_text("proof\n", encoding="utf-8")
    task = make_task()
    result = WorkerResult.model_validate(
        {
            "status": "SUCCESS",
            "issue": task.issue_number,
            "branch": task.branch,
            "head_sha": parent,
            "changed_files": ["docs/runner-demo.md"],
            "tests": [
                {
                    "command": "git diff --check",
                    "result": "PASS",
                    "evidence": "No whitespace errors.",
                }
            ],
            "blockers": [],
            "summary": "Scoped documentation ready for the runner-owned commit.",
        }
    )

    committed, files = validate_and_commit_worker_changes(
        worktree,
        task=task,
        expected_parent=parent,
        result=result,
    )

    assert committed != parent
    assert files == ["docs/runner-demo.md"]
    assert git(worktree, "status", "--porcelain=v1") == ""


def test_codex_jsonl_exposes_session_and_usage(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": "session-1"}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 10,
                            "cached_input_tokens": 4,
                            "output_tokens": 3,
                            "reasoning_output_tokens": 2,
                        },
                    }
                ),
            )
        ),
        encoding="utf-8",
    )

    session, usage = _parse_codex_events(path)

    assert session == "session-1"
    assert usage.total == 15


def test_antigravity_stream_exposes_conversation_schema_and_usage(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(
            {
                "event": "result",
                "result": {
                    "conversation_id": "conversation-1",
                    "status": "SUCCESS",
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 5,
                        "thinking_tokens": 2,
                        "cache_read_tokens": 3,
                    },
                    "structured_output": {"status": "BLOCKED"},
                },
            }
        ),
        encoding="utf-8",
    )

    session, usage, output = _parse_antigravity_events(path)

    assert session == "conversation-1"
    assert usage.total == 18
    assert output == {"status": "BLOCKED"}


def test_agent_environment_removes_ambient_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUPPLIER_API_KEY", "do-not-pass")
    monkeypatch.setenv("GH_TOKEN", "do-not-pass")
    monkeypatch.setenv("DATABASE_URL", "postgresql://production.example/real")
    monkeypatch.setenv("PGPASSFILE", "production.pgpass")
    monkeypatch.setenv("DOCKER_AUTH_CONFIG", "production-registry-credential")
    monkeypatch.setenv("PYTHONPATH", "untrusted-import-path")
    monkeypatch.setenv("PATH", "safe-path")

    isolation_dir = tmp_path / "isolated"
    result = sanitized_environment(isolation_dir)

    assert "SUPPLIER_API_KEY" not in result
    assert "GH_TOKEN" not in result
    assert result["PGPASSFILE"] == str(isolation_dir / "empty.config")
    assert result["DOCKER_CONFIG"] == str(isolation_dir / "docker")
    assert "DOCKER_AUTH_CONFIG" not in result
    assert result["GH_CONFIG_DIR"] == str(isolation_dir / "gh")
    assert "PYTHONPATH" not in result
    assert result["PATH"] == "safe-path"
    assert result["DATABASE_URL"].startswith(
        "postgresql+asyncpg://nyan_agent:nyan_agent_local_only@127.0.0.1:55432/"
    )
    assert result["SUPPLIER_MODE"] == "mock"
    assert result["PAYMENT_MODE"] == "disabled"
    assert result["ALLOW_REAL_PURCHASES"] == "false"
