from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from nyan_shop_bot.orchestrator.adapters import (
    AgentStopped,
    _parse_antigravity_events,
    _parse_codex_events,
    _run_monitored,
    process_identity,
    recover_completed_result,
    sanitized_environment,
)
from nyan_shop_bot.orchestrator.github import GitHubClient, PauseRequested
from nyan_shop_bot.orchestrator.gitops import (
    git,
    head_sha,
    pending_files,
    validate_and_commit_worker_changes,
)
from nyan_shop_bot.orchestrator.models import (
    AgentInvocation,
    CiEvidence,
    DesiredState,
    ReviewResult,
    RunPhase,
    TaskSpec,
    Usage,
    WorkerKind,
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


def initialize_task_repo(worktree: Path, task: TaskSpec) -> str:
    worktree.mkdir()
    git(worktree, "init")
    git(worktree, "config", "user.name", "Nyan Test")
    git(worktree, "config", "user.email", "nyan-test@example.invalid")
    (worktree / "README.md").write_text("base\n", encoding="utf-8")
    git(worktree, "add", "README.md")
    git(worktree, "commit", "-m", "base")
    git(worktree, "branch", "-M", task.branch)
    return head_sha(worktree)


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


def test_service_progresses_fix_ci_and_rereview_on_distinct_heads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the real state machine, commits, and same-session fix routing."""

    task = make_task()
    worktree = tmp_path / "worktree"
    base = initialize_task_repo(worktree, task)
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="full-fix-flow",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha=base,
        worktree_path=worktree,
        max_workers=2,
    )
    service.store.transition("full-fix-flow", RunPhase.CLAIMED)
    worker_resumes: list[str | None] = []
    review_heads: list[str] = []
    ci_heads: list[str] = []

    class FakeCodexAdapter:
        def worker(self, **kwargs: object) -> tuple[WorkerResult, AgentInvocation]:
            name = str(kwargs["name"])
            run_dir = Path(str(kwargs["run_dir"]))
            worker_tree = Path(str(kwargs["worktree"]))
            resume = kwargs.get("resume_session_id")
            assert resume is None or isinstance(resume, str)
            worker_resumes.append(resume)
            document = worker_tree / "docs" / "runner-demo.md"
            document.parent.mkdir(exist_ok=True)
            if resume is None:
                document.write_text("status\nresume\n", encoding="utf-8")
            else:
                assert resume == "worker-session"
                document.write_text("status\nresume\nstop\n", encoding="utf-8")
            observed_head = head_sha(worker_tree)
            result = WorkerResult.model_validate(
                {
                    "status": "SUCCESS",
                    "issue": task.issue_number,
                    "branch": task.branch,
                    "head_sha": observed_head,
                    "changed_files": ["docs/runner-demo.md"],
                    "tests": [
                        {
                            "command": "fixture-check",
                            "result": "PASS",
                            "evidence": f"{name} produced the scoped document.",
                        }
                    ],
                    "blockers": [],
                    "summary": "Deterministic worker fixture completed.",
                }
            )
            run_dir.mkdir(parents=True, exist_ok=True)
            result_path = run_dir / f"{name}.result.json"
            events_path = run_dir / f"{name}.events.jsonl"
            stderr_path = run_dir / f"{name}.stderr.log"
            result_path.write_text(result.model_dump_json(), encoding="utf-8")
            events_path.write_text(f"{name}-worker-events", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            return result, AgentInvocation(
                session_id="worker-session",
                result_path=str(result_path),
                events_path=str(events_path),
                stderr_path=str(stderr_path),
                usage=Usage(input_tokens=10, output_tokens=2),
            )

        def reviewer(self, **kwargs: object) -> tuple[ReviewResult, AgentInvocation]:
            name = str(kwargs["name"])
            run_dir = Path(str(kwargs["run_dir"]))
            reviewer_tree = Path(str(kwargs["worktree"]))
            current = head_sha(reviewer_tree)
            review_heads.append(current)
            first = len(review_heads) == 1
            result = ReviewResult.model_validate(
                {
                    "verdict": "CHANGES_REQUESTED" if first else "PASS",
                    "reviewed_head_sha": current,
                    "findings": (
                        [
                            {
                                "severity": "medium",
                                "file": "docs/runner-demo.md",
                                "line": 2,
                                "message": "Add the required stop command.",
                                "evidence": "The first committed document omits stop.",
                            }
                        ]
                        if first
                        else []
                    ),
                    "tests": [
                        {
                            "command": "fixture-review",
                            "result": "PASS",
                            "evidence": "Reviewed the exact committed document.",
                        }
                    ],
                    "blockers": [],
                    "summary": "Deterministic independent review completed.",
                }
            )
            run_dir.mkdir(parents=True, exist_ok=True)
            result_path = run_dir / f"{name}.result.json"
            events_path = run_dir / f"{name}.events.jsonl"
            stderr_path = run_dir / f"{name}.stderr.log"
            result_path.write_text(result.model_dump_json(), encoding="utf-8")
            events_path.write_text(f"{name}-review-events", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            return result, AgentInvocation(
                session_id=f"review-session-{len(review_heads)}",
                result_path=str(result_path),
                events_path=str(events_path),
                stderr_path=str(stderr_path),
                usage=Usage(input_tokens=8, output_tokens=2),
            )

    class FakeGitHub:
        def ensure_pull_request(
            self, frozen_task: TaskSpec, current_head: str, run_id: str
        ) -> dict[str, object]:
            assert frozen_task == task
            assert run_id == "full-fix-flow"
            assert current_head == head_sha(worktree)
            return {"number": 17, "url": "https://github.com/example/repo/pull/17"}

        def mark_in_review(self, frozen_task: TaskSpec) -> None:
            assert frozen_task == task

        def wait_for_ci(self, **kwargs: object) -> CiEvidence:
            current = str(kwargs["head_sha"])
            ci_heads.append(current)
            return CiEvidence(
                head_sha=current,
                run_id=100 + len(ci_heads),
                run_url=f"https://github.com/example/repo/actions/runs/{100 + len(ci_heads)}",
                checks={"ci-gate": "SUCCESS"},
            )

    monkeypatch.setattr("nyan_shop_bot.orchestrator.service.CodexAdapter", FakeCodexAdapter)
    monkeypatch.setattr(
        "nyan_shop_bot.orchestrator.service.push_branch", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(service, "_github_for_run", lambda run_id, frozen_task: FakeGitHub())

    service._run_loop("full-fix-flow")

    run = service.store.get_run("full-fix-flow")
    assert run["phase"] == RunPhase.READY_FOR_OWNER
    assert run["fix_rounds"] == 1
    assert run["agent_invocations"] == 4
    assert worker_resumes == [None, "worker-session"]
    assert len(ci_heads) == 2
    assert len(set(ci_heads)) == 2
    assert review_heads == ci_heads
    assert run["reviewed_head_sha"] == ci_heads[-1]
    assert git(worktree, "rev-list", "--count", f"{base}..HEAD") == "2"


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


def test_monitored_process_reports_child_pid_lifecycle(tmp_path: Path) -> None:
    started: list[int] = []
    finished_pids: list[int] = []
    marker = tmp_path / "agent-started.txt"

    def registered(pid: int, identity: str, completion: str, nonce: str) -> None:
        assert not marker.exists()
        assert identity
        assert completion.endswith(".launcher-contained")
        assert nonce
        started.append(pid)

    def finished(pid: int, identity: str, completion: str, nonce: str) -> None:
        assert identity
        assert Path(completion).read_text(encoding="utf-8") == nonce
        finished_pids.append(pid)

    _run_monitored(
        [
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')",
        ],
        cwd=tmp_path,
        stdin_text=None,
        stdout_path=tmp_path / "events.jsonl",
        stderr_path=tmp_path / "stderr.log",
        control=lambda: DesiredState.RUNNING,
        timeout_seconds=10,
        on_process_start=registered,
        on_process_end=finished,
    )

    assert len(started) == 1
    assert finished_pids == started
    assert marker.read_text(encoding="utf-8") == "ok"


def test_stop_terminates_registered_process_tree(tmp_path: Path) -> None:
    sentinel = tmp_path / "detached-child-was-still-running.txt"
    grandchild = (
        "import time; from pathlib import Path; time.sleep(3); "
        f"Path({str(sentinel)!r}).write_text('unsafe')"
    )
    agent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        "time.sleep(30)"
    )
    calls = 0

    def control() -> DesiredState:
        nonlocal calls
        calls += 1
        return DesiredState.RUNNING if calls == 1 else DesiredState.STOPPED

    with pytest.raises(AgentStopped, match="process tree"):
        _run_monitored(
            [sys.executable, "-c", agent],
            cwd=tmp_path,
            stdin_text=None,
            stdout_path=tmp_path / "tree.events.jsonl",
            stderr_path=tmp_path / "tree.stderr.log",
            control=control,
            timeout_seconds=10,
        )

    time.sleep(3.5)
    assert not sentinel.exists()


def test_registered_launcher_enforces_deadline_without_controller_polling(tmp_path: Path) -> None:
    sentinel = tmp_path / "deadline-child-was-still-running.txt"
    grandchild = (
        "import time; from pathlib import Path; time.sleep(1.5); "
        f"Path({str(sentinel)!r}).write_text('unsafe')"
    )
    agent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        "time.sleep(30)"
    )
    spec = tmp_path / "launch.json"
    ready = tmp_path / "ready"
    start = tmp_path / "start"
    complete = tmp_path / "complete"
    nonce = "deadline-nonce"
    spec.write_text(
        json.dumps(
            {
                "command": [sys.executable, "-c", agent],
                "stdin_path": None,
                "deadline_epoch": time.time() + 0.5,
            }
        ),
        encoding="utf-8",
    )
    start.write_text("start", encoding="utf-8")
    launcher = (
        Path(__file__).parents[2] / "src" / "nyan_shop_bot" / "orchestrator" / "agent_process.py"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(launcher),
            "--spec",
            str(spec),
            "--ready",
            str(ready),
            "--start",
            str(start),
            "--complete",
            str(complete),
            "--nonce",
            nonce,
        ],
        cwd=tmp_path,
        check=False,
        timeout=10,
        creationflags=0x00000200 if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )

    assert completed.returncode != 0
    time.sleep(2)
    assert ready.is_file()
    assert complete.read_text(encoding="utf-8") == nonce
    assert not sentinel.exists()


def test_launcher_death_contains_a_live_descendant_before_acknowledgement(tmp_path: Path) -> None:
    sentinel = tmp_path / "escaped-descendant.txt"
    agent_ready = tmp_path / "agent-ready.txt"
    grandchild = (
        "import time; from pathlib import Path; time.sleep(2); "
        f"Path({str(sentinel)!r}).write_text('unsafe')"
    )
    agent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        f"open({str(agent_ready)!r}, 'w').write('ready'); "
        "time.sleep(30)"
    )
    spec = tmp_path / "wrapper-death.json"
    ready = tmp_path / "wrapper-ready"
    start = tmp_path / "wrapper-start"
    complete = tmp_path / "wrapper-contained"
    nonce = "wrapper-death-nonce"
    spec.write_text(
        json.dumps(
            {
                "command": [sys.executable, "-c", agent],
                "stdin_path": None,
                "deadline_epoch": time.time() + 20,
            }
        ),
        encoding="utf-8",
    )
    launcher = (
        Path(__file__).parents[2] / "src" / "nyan_shop_bot" / "orchestrator" / "agent_process.py"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(launcher),
            "--spec",
            str(spec),
            "--ready",
            str(ready),
            "--start",
            str(start),
            "--complete",
            str(complete),
            "--nonce",
            nonce,
        ],
        cwd=tmp_path,
        creationflags=0x00000200 if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )
    try:
        deadline = time.monotonic() + 8
        while not ready.is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.read_text(encoding="utf-8") == nonce
        start.write_text("start", encoding="utf-8")
        while not agent_ready.is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert agent_ready.is_file()
        process.kill()
        process.wait(timeout=5)
        while not complete.is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert complete.read_text(encoding="utf-8") == nonce
        time.sleep(2.5)
        assert not sentinel.exists()
    finally:
        if process.poll() is None:
            process.kill()


def test_github_command_uses_remaining_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_timeout: int | None = None

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        nonlocal observed_timeout
        observed_timeout = int(kwargs["timeout"])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("nyan_shop_bot.orchestrator.github.subprocess.run", fake_run)
    client = GitHubClient(
        tmp_path,
        "NhanDuong21/nyan-shop-bot",
        timeout_reader=lambda: 7,
    )

    client.command("version")

    assert observed_timeout == 7


def test_each_git_subprocess_recomputes_remaining_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[int] = []
    remaining = iter((9, 7, 5))

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        observed.append(int(kwargs["timeout"]))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("nyan_shop_bot.orchestrator.gitops.subprocess.run", fake_run)

    assert pending_files(tmp_path, timeout_seconds=60, timeout_reader=lambda: next(remaining)) == []
    assert observed == [9, 7, 5]


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


def test_auto_merge_command_fails_closed_without_atomic_base_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = GitHubClient(tmp_path, "NhanDuong21/nyan-shop-bot")
    captured: tuple[str, ...] = ()

    def command(*arguments: str) -> str:
        nonlocal captured
        captured = arguments
        return ""

    monkeypatch.setattr(client, "command", command)
    with pytest.raises(RuntimeError, match="does not bind the base branch"):
        client.queue_auto_merge(42, expected_head="a" * 40)

    assert captured == ()


def test_owner_confirmation_cannot_mutate_github_auto_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = RunnerService(tmp_path, tmp_path / "state")
    github_constructed = False

    def unexpected_client(*args: object, **kwargs: object) -> object:
        nonlocal github_constructed
        github_constructed = True
        raise AssertionError("GitHub mutation client must not be constructed")

    monkeypatch.setattr("nyan_shop_bot.orchestrator.service.GitHubClient", unexpected_client)

    with pytest.raises(RuntimeError, match="automatic merge is BLOCKED"):
        service.authorize_auto_merge(
            "NhanDuong21/nyan-shop-bot", "explicit-but-insufficient-owner-input"
        )

    assert not github_constructed


def test_interrupted_worker_recovers_explicit_session(tmp_path: Path) -> None:
    task = make_task()
    worktree = tmp_path / "worktree"
    parent = initialize_task_repo(worktree, task)
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="recovery-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha=parent,
        worktree_path=worktree,
        max_workers=2,
    )
    service.store.update_run("recovery-run", worker_parent_sha=parent)
    service.store.transition("recovery-run", RunPhase.WORKER_RUNNING)
    run_dir = service.state_dir / "runs" / "recovery-run"
    run_dir.mkdir(parents=True)
    (run_dir / "worker-initial.events.jsonl").write_text(
        json.dumps({"type": "thread.started", "thread_id": "durable-session"}),
        encoding="utf-8",
    )

    service._recover_interrupted_worker("recovery-run", task, worktree)

    run = service.store.get_run("recovery-run")
    assert run["phase"] == RunPhase.CLAIMED
    assert run["worker_session_id"] == "durable-session"


def test_interrupted_worker_reconciles_existing_runner_commit(tmp_path: Path) -> None:
    task = make_task()
    worktree = tmp_path / "worktree"
    parent = initialize_task_repo(worktree, task)
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="commit-recovery-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha=parent,
        worktree_path=worktree,
        max_workers=2,
    )
    service.store.update_run("commit-recovery-run", worker_parent_sha=parent)
    service.store.transition("commit-recovery-run", RunPhase.WORKER_RUNNING)
    docs = worktree / "docs"
    docs.mkdir()
    (docs / "runner-demo.md").write_text("proof\n", encoding="utf-8")
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
            "summary": "Ready for the runner-owned commit.",
        }
    )
    run_dir = service.state_dir / "runs" / "commit-recovery-run"
    run_dir.mkdir(parents=True)
    (run_dir / "worker-initial.result.json").write_text(result.model_dump_json(), encoding="utf-8")
    (run_dir / "worker-initial.events.jsonl").write_text(
        "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": "commit-session"}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 20,
                            "cached_input_tokens": 5,
                            "output_tokens": 4,
                            "reasoning_output_tokens": 1,
                        },
                    }
                ),
            )
        ),
        encoding="utf-8",
    )
    committed, _ = validate_and_commit_worker_changes(
        worktree,
        task=task,
        expected_parent=parent,
        result=result,
    )

    service._recover_interrupted_worker("commit-recovery-run", task, worktree)

    run = service.store.get_run("commit-recovery-run")
    assert run["phase"] == RunPhase.WORKER_COMPLETE
    assert run["head_sha"] == committed
    assert run["worker_parent_sha"] is None
    assert run["worker_session_id"] == "commit-session"
    assert run["total_tokens"] == 25
    assert git(worktree, "rev-list", "--count", f"{parent}..HEAD") == "1"


def test_worker_recovery_rejects_a_different_persisted_session(tmp_path: Path) -> None:
    task = make_task()
    worktree = tmp_path / "worktree"
    parent = initialize_task_repo(worktree, task)
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="wrong-session-recovery",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha=parent,
        worktree_path=worktree,
        max_workers=2,
    )
    service.store.update_run(
        "wrong-session-recovery",
        worker_parent_sha=parent,
        worker_session_id="expected-session",
    )
    service.store.transition("wrong-session-recovery", RunPhase.WORKER_RUNNING)
    docs = worktree / "docs"
    docs.mkdir()
    (docs / "runner-demo.md").write_text("proof\n", encoding="utf-8")
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
            "summary": "Wrong resumed session must be rejected.",
        }
    )
    run_dir = service.state_dir / "runs" / "wrong-session-recovery"
    run_dir.mkdir(parents=True)
    (run_dir / "worker-initial.result.json").write_text(result.model_dump_json(), encoding="utf-8")
    (run_dir / "worker-initial.events.jsonl").write_text(
        "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": "wrong-session"}),
                json.dumps({"type": "turn.completed", "usage": {}}),
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="persisted session"):
        service._recover_interrupted_worker("wrong-session-recovery", task, worktree)

    run = service.store.get_run("wrong-session-recovery")
    assert run["phase"] == RunPhase.WORKER_RUNNING
    assert run["worker_session_id"] == "expected-session"
    assert run["total_tokens"] == 0


def test_antigravity_terminal_stream_recovers_without_result_file(tmp_path: Path) -> None:
    task_value = task_data()
    task_value.update({"worker": "antigravity", "role": "ui"})
    task = TaskSpec.model_validate(task_value)
    worktree = tmp_path / "worktree"
    parent = initialize_task_repo(worktree, task)
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="antigravity-terminal-recovery",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha=parent,
        worktree_path=worktree,
        max_workers=2,
    )
    service.store.update_run("antigravity-terminal-recovery", worker_parent_sha=parent)
    service.store.transition("antigravity-terminal-recovery", RunPhase.WORKER_RUNNING)
    docs = worktree / "docs"
    docs.mkdir()
    (docs / "runner-demo.md").write_text("proof\n", encoding="utf-8")
    structured = {
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
        "summary": "Recovered from the terminal Antigravity event.",
    }
    run_dir = service.state_dir / "runs" / "antigravity-terminal-recovery"
    run_dir.mkdir(parents=True)
    (run_dir / "worker-initial.events.jsonl").write_text(
        json.dumps(
            {
                "event": "result",
                "result": {
                    "conversation_id": "completed-conversation",
                    "status": "SUCCESS",
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 5,
                        "thinking_tokens": 2,
                        "cache_read_tokens": 3,
                    },
                    "structured_output": structured,
                },
            }
        ),
        encoding="utf-8",
    )

    service._recover_interrupted_worker("antigravity-terminal-recovery", task, worktree)

    run = service.store.get_run("antigravity-terminal-recovery")
    assert run["phase"] == RunPhase.WORKER_COMPLETE
    assert run["worker_session_id"] == "completed-conversation"
    assert run["total_tokens"] == 18
    assert (run_dir / "worker-initial.result.json").is_file()


def test_worker_recovery_accounts_usage_before_enforcing_budget(tmp_path: Path) -> None:
    task = make_task()
    worktree = tmp_path / "worktree"
    parent = initialize_task_repo(worktree, task)
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="over-budget-recovery",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha=parent,
        worktree_path=worktree,
        max_workers=2,
    )
    service.store.update_run("over-budget-recovery", worker_parent_sha=parent)
    service.store.transition("over-budget-recovery", RunPhase.WORKER_RUNNING)
    docs = worktree / "docs"
    docs.mkdir()
    (docs / "runner-demo.md").write_text("proof\n", encoding="utf-8")
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
            "summary": "Ready but over budget.",
        }
    )
    run_dir = service.state_dir / "runs" / "over-budget-recovery"
    run_dir.mkdir(parents=True)
    (run_dir / "worker-initial.result.json").write_text(result.model_dump_json(), encoding="utf-8")
    (run_dir / "worker-initial.events.jsonl").write_text(
        "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": "expensive-session"}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 100_001,
                            "cached_input_tokens": 0,
                            "output_tokens": 0,
                            "reasoning_output_tokens": 0,
                        },
                    }
                ),
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="token ceiling"):
        service._recover_interrupted_worker("over-budget-recovery", task, worktree)

    run = service.store.get_run("over-budget-recovery")
    assert run["phase"] == RunPhase.WORKER_RUNNING
    assert run["worker_session_id"] == "expensive-session"
    assert run["total_tokens"] == 100_001


def test_review_recovery_uses_durable_result_without_duplicate_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task()
    worktree = tmp_path / "worktree"
    head = initialize_task_repo(worktree, task)
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="review-recovery-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha=head,
        worktree_path=worktree,
        max_workers=2,
    )
    service.store.update_run(
        "review-recovery-run",
        head_sha=head,
        pr_number=42,
        agent_invocations=1,
        review_started_head_sha=head,
    )
    service.store.transition("review-recovery-run", RunPhase.REVIEW_RUNNING)
    run_dir = service.state_dir / "runs" / "review-recovery-run"
    run_dir.mkdir(parents=True)
    result = ReviewResult.model_validate(
        {
            "verdict": "PASS",
            "reviewed_head_sha": head,
            "findings": [],
            "tests": [
                {
                    "command": "git diff --check",
                    "result": "PASS",
                    "evidence": "Independent check completed.",
                }
            ],
            "blockers": [],
            "summary": "Exact HEAD passed independent review.",
        }
    )
    (run_dir / "review-0.events.jsonl").write_text(
        "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": "review-session"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": result.model_dump_json(),
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 10,
                            "cached_input_tokens": 0,
                            "output_tokens": 4,
                            "reasoning_output_tokens": 1,
                        },
                    }
                ),
            )
        ),
        encoding="utf-8",
    )

    def duplicate_reviewer(*args: object, **kwargs: object) -> object:
        raise AssertionError("reviewer must not be launched twice")

    monkeypatch.setattr(
        "nyan_shop_bot.orchestrator.service.CodexAdapter.reviewer", duplicate_reviewer
    )

    service._run_review("review-recovery-run", task, worktree, head)

    run = service.store.get_run("review-recovery-run")
    assert run["phase"] == RunPhase.READY_FOR_OWNER
    assert run["agent_invocations"] == 1
    assert run["reviewer_session_id"] == "review-session"
    assert run["reviewed_head_sha"] == head
    assert run["total_tokens"] == 15
    assert (run_dir / "review-0.result.json").is_file()


def test_prepare_launch_refuses_live_orphan_agent(tmp_path: Path) -> None:
    task = make_task()
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="orphan-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    service.store.acquire_process_lease(
        "orphan-run", pid=999_999_999, identity="missing-controller", token="old-owner"
    )
    completion = service.state_dir / "runs" / "orphan-run" / "test.launcher-contained"
    service.store.set_active_agent(
        "orphan-run",
        token="old-owner",
        pid=os.getpid(),
        identity=process_identity(os.getpid()) or "missing",
        completion_path=str(completion),
        nonce="orphan-nonce",
    )

    with pytest.raises(RuntimeError, match="live agent process"):
        service.prepare_process_launch("orphan-run")


def test_agent_finish_rejects_a_spoofed_containment_nonce(tmp_path: Path) -> None:
    task = make_task()
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="spoofed-containment",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    identity = process_identity(os.getpid())
    assert identity is not None
    service.store.acquire_process_lease(
        "spoofed-containment",
        pid=os.getpid(),
        identity=identity,
        token="current-owner",
    )
    service._lease_tokens["spoofed-containment"] = "current-owner"
    completion = service.state_dir / "runs" / "spoofed-containment" / "test.launcher-contained"
    completion.parent.mkdir(parents=True, exist_ok=True)
    completion.write_text("stale-nonce", encoding="utf-8")
    service.store.set_active_agent(
        "spoofed-containment",
        token="current-owner",
        pid=os.getpid(),
        identity=identity,
        completion_path=str(completion),
        nonce="expected-nonce",
    )

    with pytest.raises(RuntimeError, match="durably contained"):
        service._agent_finished(
            "spoofed-containment",
            os.getpid(),
            identity,
            str(completion),
            "expected-nonce",
        )

    assert service.store.get_run("spoofed-containment")["active_agent_pid"] == os.getpid()


def test_pid_reuse_mismatch_is_never_terminated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task()
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="pid-reuse-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    service.store.acquire_process_lease(
        "pid-reuse-run", pid=111, identity="old-controller", token="old-owner"
    )
    completion = service.state_dir / "runs" / "pid-reuse-run" / "test.launcher-contained"
    completion.parent.mkdir(parents=True, exist_ok=True)
    completion.write_text("old-launch", encoding="utf-8")
    service.store.set_active_agent(
        "pid-reuse-run",
        token="old-owner",
        pid=222,
        identity="old-launcher",
        completion_path=str(completion),
        nonce="old-launch",
    )
    monkeypatch.setattr(
        "nyan_shop_bot.orchestrator.service.process_matches",
        lambda pid, identity: False,
    )
    terminated: list[int] = []

    def unexpected_terminate(pid: int, *, expected_identity: str) -> bool:
        terminated.append(pid)
        return True

    monkeypatch.setattr(
        "nyan_shop_bot.orchestrator.service.terminate_process_tree", unexpected_terminate
    )

    service.set_control("pid-reuse-run", DesiredState.STOPPED)

    assert terminated == []
    assert service.store.get_run("pid-reuse-run")["phase"] == RunPhase.STOPPED


def test_unreadable_process_identity_keeps_the_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task()
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="identity-unknown-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    service.store.acquire_process_lease(
        "identity-unknown-run", pid=111, identity="controller", token="old-owner"
    )

    def unreadable(pid: int, identity: str) -> bool:
        raise PermissionError("identity unreadable")

    monkeypatch.setattr("nyan_shop_bot.orchestrator.service.process_matches", unreadable)

    with pytest.raises(PermissionError, match="identity unreadable"):
        service.prepare_process_launch("identity-unknown-run")

    assert [claim["run_id"] for claim in service.store.active_claims()] == ["identity-unknown-run"]


def test_stop_kills_orphan_tree_before_releasing_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task()
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="orphan-stop-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    service.store.acquire_process_lease(
        "orphan-stop-run", pid=111, identity="controller-identity", token="old-owner"
    )
    completion = service.state_dir / "runs" / "orphan-stop-run" / "test.launcher-contained"
    service.store.set_active_agent(
        "orphan-stop-run",
        token="old-owner",
        pid=222,
        identity="agent-identity",
        completion_path=str(completion),
        nonce="orphan-nonce",
    )
    alive = {222}
    terminated: list[int] = []

    monkeypatch.setattr(
        "nyan_shop_bot.orchestrator.service.process_matches",
        lambda pid, identity: pid in alive,
    )

    def terminate(pid: int, *, expected_identity: str) -> bool:
        assert expected_identity == "agent-identity"
        terminated.append(pid)
        alive.discard(pid)
        completion.parent.mkdir(parents=True, exist_ok=True)
        completion.write_text("orphan-nonce", encoding="utf-8")
        return True

    monkeypatch.setattr("nyan_shop_bot.orchestrator.service.terminate_process_tree", terminate)

    service.set_control("orphan-stop-run", DesiredState.STOPPED)

    run = service.store.get_run("orphan-stop-run")
    assert terminated == [222]
    assert run["phase"] == RunPhase.STOPPED
    assert run["pid"] is None
    assert run["active_agent_pid"] is None
    assert service.store.active_claims() == []


def test_failed_orphan_tree_kill_keeps_phase_and_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task()
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="orphan-unsafe-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    service.store.acquire_process_lease(
        "orphan-unsafe-run", pid=111, identity="controller-identity", token="old-owner"
    )
    completion = service.state_dir / "runs" / "orphan-unsafe-run" / "test.launcher-contained"
    service.store.set_active_agent(
        "orphan-unsafe-run",
        token="old-owner",
        pid=222,
        identity="agent-identity",
        completion_path=str(completion),
        nonce="orphan-nonce",
    )
    monkeypatch.setattr(
        "nyan_shop_bot.orchestrator.service.process_matches",
        lambda pid, identity: pid == 222,
    )
    monkeypatch.setattr(
        "nyan_shop_bot.orchestrator.service.terminate_process_tree",
        lambda pid, *, expected_identity: False,
    )

    with pytest.raises(RuntimeError, match="could not be terminated"):
        service.set_control("orphan-unsafe-run", DesiredState.STOPPED)

    run = service.store.get_run("orphan-unsafe-run")
    assert run["phase"] == RunPhase.CREATED
    assert run["active_agent_pid"] == 222
    assert [claim["run_id"] for claim in service.store.active_claims()] == ["orphan-unsafe-run"]


def test_owner_pending_confirmation_can_resume_only_after_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_value = task_data()
    task_value.update({"pr_base": "main", "auto_merge_eligible": True})
    task = TaskSpec.model_validate(task_value)
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="pending-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    service.store.update_run(
        "pending-run",
        head_sha="a" * 40,
        reviewed_head_sha="a" * 40,
        pr_number=42,
    )
    service.store.transition("pending-run", RunPhase.MERGE_PENDING_CONFIRMATION)

    with pytest.raises(RuntimeError, match="automatic merge is BLOCKED"):
        service.resume_run("pending-run")

    monkeypatch.setattr(service, "owner_authorized", lambda repository: True)
    with pytest.raises(RuntimeError, match="automatic merge is BLOCKED"):
        service.resume_run("pending-run")

    assert service.store.get_run("pending-run")["phase"] == RunPhase.MERGE_PENDING_CONFIRMATION


def test_owner_gate_can_be_stopped_and_releases_claim(tmp_path: Path) -> None:
    task = make_task()
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="owner-stop-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    service.store.transition("owner-stop-run", RunPhase.READY_FOR_OWNER)

    service.set_control("owner-stop-run", DesiredState.STOPPED)

    assert service.store.get_run("owner-stop-run")["phase"] == RunPhase.STOPPED
    assert service.store.active_claims() == []


def test_owner_manual_merge_reconciles_exact_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task()
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="owner-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    service.store.update_run(
        "owner-run",
        head_sha="a" * 40,
        reviewed_head_sha="a" * 40,
        pr_number=42,
    )
    service.store.transition("owner-run", RunPhase.READY_FOR_OWNER)
    service.store.update_run("owner-run", deadline_at="2000-01-01T00:00:00+00:00")

    class FakeGitHub:
        def merged_commit_if_exact(
            self, pr_number: int, *, expected_head: str, expected_base: str
        ) -> str:
            assert pr_number == 42
            assert expected_head == "a" * 40
            assert expected_base == task.pr_base
            return "c" * 40

    monkeypatch.setattr(service, "_github_for_run", lambda run_id, frozen_task: FakeGitHub())

    service.resume_run("owner-run")

    run = service.store.get_run("owner-run")
    assert run["phase"] == RunPhase.OWNER_MERGED
    assert run["merge_sha"] == "c" * 40
    assert str(run["deadline_at"]) > "2000-01-01T00:00:00+00:00"


def test_manual_merge_rejects_retargeted_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = GitHubClient(tmp_path, "NhanDuong21/nyan-shop-bot")
    monkeypatch.setattr(
        client,
        "json_command",
        lambda *arguments: {
            "state": "MERGED",
            "headRefOid": "a" * 40,
            "baseRefName": "unexpected-base",
            "mergeCommit": {"oid": "c" * 40},
        },
    )

    with pytest.raises(RuntimeError, match="trusted task base"):
        client.merged_commit_if_exact(
            42,
            expected_head="a" * 40,
            expected_base="nyan/nsb-040-agent-runner",
        )


def test_runner_owns_commit_after_validating_worker_paths(tmp_path: Path) -> None:
    task = make_task()
    worktree = tmp_path / "repo"
    parent = initialize_task_repo(worktree, task)
    docs = worktree / "docs"
    docs.mkdir()
    (docs / "runner-demo.md").write_text("proof\n", encoding="utf-8")
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


def test_codex_completion_parser_rejects_non_terminal_stream(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps({"type": "thread.started", "thread_id": "partial-session"}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="terminal turn.completed"):
        _parse_codex_events(path)


def test_codex_recovery_ignores_result_until_turn_is_terminal(tmp_path: Path) -> None:
    events_path = tmp_path / "review.events.jsonl"
    result_path = tmp_path / "review.result.json"
    events_path.write_text(
        json.dumps({"type": "thread.started", "thread_id": "partial-session"}),
        encoding="utf-8",
    )
    result_path.write_text(
        ReviewResult(
            verdict="PASS",
            reviewed_head_sha="a" * 40,
            findings=[],
            tests=[],
            blockers=[],
            summary="This durable file is not enough without a terminal stream.",
        ).model_dump_json(),
        encoding="utf-8",
    )

    recovered = recover_completed_result(
        events_path=events_path,
        result_path=result_path,
        worker=WorkerKind.CODEX,
        result_model=ReviewResult,
    )

    assert recovered is None


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
