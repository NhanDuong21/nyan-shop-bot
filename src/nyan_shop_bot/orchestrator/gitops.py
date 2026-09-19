"""Checked Git operations for isolated writer worktrees."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from nyan_shop_bot.orchestrator.models import SHA_PATTERN, TaskSpec, WorkerResult, WorkerStatus
from nyan_shop_bot.orchestrator.policy import paths_are_allowed

TimeoutReader = Callable[[], int]


def git(
    root: Path,
    *arguments: str,
    check: bool = True,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> str:
    command_timeout = max(1, timeout_seconds)
    if timeout_reader is not None:
        command_timeout = max(1, min(command_timeout, timeout_reader()))
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=command_timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(f"git {' '.join(arguments)} exceeded {command_timeout}s") from error
    if check and completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def resolve_sha(
    root: Path,
    revision: str,
    *,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> str:
    sha = git(
        root,
        "rev-parse",
        "--verify",
        f"{revision}^{{commit}}",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    if not SHA_PATTERN.fullmatch(sha):
        raise RuntimeError(f"revision did not resolve to a full SHA: {revision}")
    return sha


def verify_tracked_task(
    root: Path,
    task_path: Path,
    *,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> Path:
    resolved_root = root.resolve()
    resolved_task = task_path.resolve()
    try:
        relative = resolved_task.relative_to(resolved_root)
    except ValueError as error:
        raise RuntimeError("task spec must be inside the repository") from error
    relative_text = relative.as_posix()
    if not relative_text.startswith("ops/agent_tasks/") or resolved_task.suffix != ".json":
        raise RuntimeError("task spec must be a JSON file under ops/agent_tasks/")
    git(
        root,
        "ls-files",
        "--error-unmatch",
        "--",
        relative_text,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    if git(
        root,
        "status",
        "--porcelain",
        "--",
        relative_text,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    ):
        raise RuntimeError("task spec must be committed and unmodified")
    return resolved_task


def create_worktree(
    root: Path,
    *,
    worktree_path: Path,
    branch: str,
    base_sha: str,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> None:
    if worktree_path.exists():
        actual = Path(
            git(
                worktree_path,
                "rev-parse",
                "--show-toplevel",
                timeout_seconds=timeout_seconds,
                timeout_reader=timeout_reader,
            )
        ).resolve()
        if actual != worktree_path.resolve():
            raise RuntimeError(f"unexpected existing path at {worktree_path}")
        actual_branch = git(
            worktree_path,
            "branch",
            "--show-current",
            timeout_seconds=timeout_seconds,
            timeout_reader=timeout_reader,
        )
        if actual_branch != branch:
            raise RuntimeError(f"existing worktree uses {actual_branch}, expected {branch}")
        return

    local_branch = git(
        root,
        "show-ref",
        "--verify",
        f"refs/heads/{branch}",
        check=False,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    if local_branch:
        raise RuntimeError(f"branch exists without this run's worktree: {branch}")
    remote_branch = git(
        root,
        "ls-remote",
        "--heads",
        "origin",
        f"refs/heads/{branch}",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    if remote_branch:
        raise RuntimeError(f"remote branch already exists before claim: {branch}")
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    git(
        root,
        "worktree",
        "add",
        "-b",
        branch,
        str(worktree_path),
        base_sha,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )


def head_sha(
    worktree: Path,
    *,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> str:
    return resolve_sha(
        worktree,
        "HEAD",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )


def changed_files(
    worktree: Path,
    base_sha: str,
    head: str,
    *,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> list[str]:
    output = git(
        worktree,
        "diff",
        "--name-only",
        f"{base_sha}...{head}",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    return sorted(line.strip().replace("\\", "/") for line in output.splitlines() if line.strip())


def pending_files(
    worktree: Path,
    *,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> list[str]:
    tracked = git(
        worktree,
        "diff",
        "--name-only",
        "HEAD",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    staged = git(
        worktree,
        "diff",
        "--cached",
        "--name-only",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    untracked = git(
        worktree,
        "ls-files",
        "--others",
        "--exclude-standard",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    return sorted(
        {
            line.strip().replace("\\", "/")
            for output in (tracked, staged, untracked)
            for line in output.splitlines()
            if line.strip()
        }
    )


def validate_and_commit_worker_changes(
    worktree: Path,
    *,
    task: TaskSpec,
    expected_parent: str,
    result: WorkerResult,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> tuple[str, list[str]]:
    if result.issue != task.issue_number:
        raise RuntimeError("worker result names a different issue")
    if result.branch != task.branch:
        raise RuntimeError("worker result names a different branch")
    if (
        git(
            worktree,
            "branch",
            "--show-current",
            timeout_seconds=timeout_seconds,
            timeout_reader=timeout_reader,
        )
        != task.branch
    ):
        raise RuntimeError("worker worktree is on a different branch")
    actual_head = head_sha(
        worktree,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    if actual_head != result.head_sha:
        raise RuntimeError(f"worker result HEAD {result.head_sha} != actual {actual_head}")
    if actual_head != expected_parent:
        raise RuntimeError("worker changed Git history; only the runner may commit")
    actual_files = pending_files(
        worktree,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    if not actual_files:
        raise RuntimeError("worker reported success without scoped working-tree changes")
    if sorted(result.changed_files) != actual_files:
        raise RuntimeError("worker changed_files does not match the working tree")
    if not paths_are_allowed(actual_files, task.allowed_paths):
        raise RuntimeError(f"worker changed files outside allowed scope: {actual_files}")
    git(
        worktree,
        "add",
        "--",
        *actual_files,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    staged_files = sorted(
        line.strip().replace("\\", "/")
        for line in git(
            worktree,
            "diff",
            "--cached",
            "--name-only",
            timeout_seconds=timeout_seconds,
            timeout_reader=timeout_reader,
        ).splitlines()
        if line.strip()
    )
    if staged_files != actual_files:
        raise RuntimeError("runner staging did not match the validated worker paths")
    git(
        worktree,
        "commit",
        "-m",
        f"{task.task_id}: automated scoped change",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    committed_head = head_sha(
        worktree,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    if committed_head == expected_parent:
        raise RuntimeError("runner commit did not advance HEAD")
    if git(
        worktree,
        "status",
        "--porcelain=v1",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    ):
        raise RuntimeError("runner-owned commit did not leave a clean worktree")
    return committed_head, actual_files


def validate_recovered_runner_commit(
    worktree: Path,
    *,
    task: TaskSpec,
    expected_parent: str,
    result: WorkerResult,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> tuple[str, list[str]]:
    """Reconcile the single exact runner-owned commit after a controller crash."""

    if result.status is not WorkerStatus.SUCCESS:
        raise RuntimeError("cannot recover a non-success worker result")
    if result.issue != task.issue_number or result.branch != task.branch:
        raise RuntimeError("recovered worker result does not match the trusted task")
    if result.head_sha != expected_parent:
        raise RuntimeError("recovered worker result is not bound to the expected parent")
    if (
        git(
            worktree,
            "branch",
            "--show-current",
            timeout_seconds=timeout_seconds,
            timeout_reader=timeout_reader,
        )
        != task.branch
    ):
        raise RuntimeError("recovered worktree is on a different branch")
    current_head = head_sha(
        worktree,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    parent = resolve_sha(
        worktree,
        "HEAD^",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    if current_head == expected_parent or parent != expected_parent:
        raise RuntimeError("recovered history is not one commit above the expected parent")
    count = git(
        worktree,
        "rev-list",
        "--count",
        f"{expected_parent}..{current_head}",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    if count != "1":
        raise RuntimeError("recovered history contains more than one new commit")
    subject = git(
        worktree,
        "show",
        "-s",
        "--format=%s",
        current_head,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    if subject != f"{task.task_id}: automated scoped change":
        raise RuntimeError("recovered commit was not created by this runner task")
    if git(
        worktree,
        "status",
        "--porcelain=v1",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    ):
        raise RuntimeError("recovered runner commit did not leave a clean worktree")
    files = changed_files(
        worktree,
        expected_parent,
        current_head,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    if files != sorted(result.changed_files) or not paths_are_allowed(files, task.allowed_paths):
        raise RuntimeError("recovered commit paths do not match the validated worker result")
    return current_head, files


def push_branch(
    worktree: Path,
    branch: str,
    *,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> None:
    git(
        worktree,
        "push",
        "--set-upstream",
        "origin",
        branch,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
