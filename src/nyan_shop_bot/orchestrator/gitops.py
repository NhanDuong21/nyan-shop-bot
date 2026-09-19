"""Checked Git operations for isolated writer worktrees."""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

from nyan_shop_bot.orchestrator.models import SHA_PATTERN, TaskSpec, WorkerResult, WorkerStatus
from nyan_shop_bot.orchestrator.policy import forbidden_ui_worker_paths, paths_are_allowed

TimeoutReader = Callable[[], int]


def git(
    root: Path,
    *arguments: str,
    check: bool = True,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
    raw: bool = False,
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
    return completed.stdout if raw else completed.stdout.strip()


def git_bytes(
    root: Path,
    *arguments: str,
    check: bool = True,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> bytes:
    """Run Git without text decoding so committed binary blobs can be authenticated."""

    command_timeout = max(1, timeout_seconds)
    if timeout_reader is not None:
        command_timeout = max(1, min(command_timeout, timeout_reader()))
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=root,
            check=False,
            capture_output=True,
            timeout=command_timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(f"git {' '.join(arguments)} exceeded {command_timeout}s") from error
    if check and completed.returncode:
        detail = (completed.stderr or completed.stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _nul_paths(output: str) -> list[str]:
    return sorted(value.replace("\\", "/") for value in output.split("\0") if value)


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
        "-z",
        f"{base_sha}...{head}",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
        raw=True,
    )
    return _nul_paths(output)


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
        "-z",
        "HEAD",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
        raw=True,
    )
    staged = git(
        worktree,
        "diff",
        "--cached",
        "--name-only",
        "-z",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
        raw=True,
    )
    untracked = git(
        worktree,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
        raw=True,
    )
    return sorted({path for output in (tracked, staged, untracked) for path in _nul_paths(output)})


def _is_reparse_component(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except (FileNotFoundError, OSError):
        return False
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def validate_changed_path_containment(worktree: Path, changed_files: list[str]) -> None:
    """Reject symlink/path tricks before the runner stages a worker change."""

    root = worktree.resolve()
    for relative in changed_files:
        candidate = root / relative
        try:
            candidate.resolve(strict=False).relative_to(root)
        except ValueError as error:
            raise RuntimeError(f"worker path escapes its worktree: {relative}") from error
        current = candidate
        while current != root and current != current.parent:
            if _is_reparse_component(current):
                raise RuntimeError(f"worker path uses a symlink or reparse point: {relative}")
            current = current.parent


def validate_ui_workspace_control_files(worktree: Path, task: TaskSpec) -> None:
    """Detect ignored or untracked policy/config files hidden inside a UI grant."""

    if task.role != "ui":
        return
    feature_root = worktree / task.allowed_paths[0][:-3]
    if not feature_root.exists():
        return
    if _is_reparse_component(feature_root):
        raise RuntimeError("UI feature root is a symlink or reparse point")
    suspicious: list[str] = []
    for current_root, directories, files in os.walk(feature_root, followlinks=False):
        current = Path(current_root)
        for directory in list(directories):
            candidate = current / directory
            relative = candidate.relative_to(worktree).as_posix()
            if _is_reparse_component(candidate):
                suspicious.append(relative)
                directories.remove(directory)
                continue
            if forbidden_ui_worker_paths([f"{relative}/placeholder"]):
                suspicious.append(relative)
                directories.remove(directory)
        for filename in files:
            candidate = current / filename
            relative = candidate.relative_to(worktree).as_posix()
            if _is_reparse_component(candidate) or forbidden_ui_worker_paths([relative]):
                suspicious.append(relative)
    if suspicious:
        raise RuntimeError(
            f"UI workspace contains coordinator-owned or reparse files: {sorted(suspicious)}"
        )


def validate_ui_prelaunch_workspace(
    worktree: Path,
    task: TaskSpec,
    *,
    timeout_seconds: int = 60,
    timeout_reader: TimeoutReader | None = None,
) -> None:
    """Require a real, tracked Codex skeleton below non-reparse ancestors."""

    if task.role != "ui":
        return
    root = worktree.resolve()
    feature_root = worktree / task.allowed_paths[0][:-3]
    current = worktree
    for part in feature_root.relative_to(worktree).parts:
        current /= part
        if current.exists() and _is_reparse_component(current):
            raise RuntimeError(f"UI skeleton ancestor is a symlink or reparse point: {part}")
    try:
        feature_root.resolve(strict=True).relative_to(root)
    except (FileNotFoundError, ValueError) as error:
        raise RuntimeError(
            "UI feature root must be a real directory inside the worktree"
        ) from error
    if not feature_root.is_dir():
        raise RuntimeError("UI feature root must be a real directory inside the worktree")
    relative_root = feature_root.relative_to(worktree).as_posix()
    tracked = _nul_paths(
        git(
            worktree,
            "ls-files",
            "-z",
            "--",
            f"{relative_root}/",
            timeout_seconds=timeout_seconds,
            timeout_reader=timeout_reader,
            raw=True,
        )
    )
    if not tracked:
        raise RuntimeError("UI feature root has no tracked Codex-owned starter file")
    validate_changed_path_containment(worktree, tracked)
    validate_ui_workspace_control_files(worktree, task)


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
    validate_ui_workspace_control_files(worktree, task)
    if not actual_files:
        raise RuntimeError("worker reported success without scoped working-tree changes")
    if sorted(result.changed_files) != actual_files:
        raise RuntimeError("worker changed_files does not match the working tree")
    validate_changed_path_containment(worktree, actual_files)
    if not paths_are_allowed(actual_files, task.allowed_paths):
        raise RuntimeError(f"worker changed files outside allowed scope: {actual_files}")
    forbidden_ui = forbidden_ui_worker_paths(actual_files) if task.role == "ui" else []
    if forbidden_ui:
        raise RuntimeError(f"UI worker changed coordinator-owned files: {forbidden_ui}")
    git(
        worktree,
        "add",
        "--",
        *actual_files,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    staged_files = _nul_paths(
        git(
            worktree,
            "diff",
            "--cached",
            "--name-only",
            "-z",
            timeout_seconds=timeout_seconds,
            timeout_reader=timeout_reader,
            raw=True,
        )
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
    validate_ui_workspace_control_files(worktree, task)
    files = changed_files(
        worktree,
        expected_parent,
        current_head,
        timeout_seconds=timeout_seconds,
        timeout_reader=timeout_reader,
    )
    validate_changed_path_containment(worktree, files)
    if files != sorted(result.changed_files) or not paths_are_allowed(files, task.allowed_paths):
        raise RuntimeError("recovered commit paths do not match the validated worker result")
    forbidden_ui = forbidden_ui_worker_paths(files) if task.role == "ui" else []
    if forbidden_ui:
        raise RuntimeError(f"recovered UI commit changed coordinator-owned files: {forbidden_ui}")
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
