"""Checked Git operations for isolated writer worktrees."""

from __future__ import annotations

import subprocess
from pathlib import Path

from nyan_shop_bot.orchestrator.models import SHA_PATTERN, TaskSpec, WorkerResult
from nyan_shop_bot.orchestrator.policy import paths_are_allowed


def git(root: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def resolve_sha(root: Path, revision: str) -> str:
    sha = git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if not SHA_PATTERN.fullmatch(sha):
        raise RuntimeError(f"revision did not resolve to a full SHA: {revision}")
    return sha


def verify_tracked_task(root: Path, task_path: Path) -> Path:
    resolved_root = root.resolve()
    resolved_task = task_path.resolve()
    try:
        relative = resolved_task.relative_to(resolved_root)
    except ValueError as error:
        raise RuntimeError("task spec must be inside the repository") from error
    relative_text = relative.as_posix()
    if not relative_text.startswith("ops/agent_tasks/") or resolved_task.suffix != ".json":
        raise RuntimeError("task spec must be a JSON file under ops/agent_tasks/")
    git(root, "ls-files", "--error-unmatch", "--", relative_text)
    if git(root, "status", "--porcelain", "--", relative_text):
        raise RuntimeError("task spec must be committed and unmodified")
    return resolved_task


def create_worktree(
    root: Path,
    *,
    worktree_path: Path,
    branch: str,
    base_sha: str,
) -> None:
    if worktree_path.exists():
        actual = Path(git(worktree_path, "rev-parse", "--show-toplevel")).resolve()
        if actual != worktree_path.resolve():
            raise RuntimeError(f"unexpected existing path at {worktree_path}")
        actual_branch = git(worktree_path, "branch", "--show-current")
        if actual_branch != branch:
            raise RuntimeError(f"existing worktree uses {actual_branch}, expected {branch}")
        return

    local_branch = git(root, "show-ref", "--verify", f"refs/heads/{branch}", check=False)
    if local_branch:
        raise RuntimeError(f"branch exists without this run's worktree: {branch}")
    remote_branch = git(root, "ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    if remote_branch:
        raise RuntimeError(f"remote branch already exists before claim: {branch}")
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    git(root, "worktree", "add", "-b", branch, str(worktree_path), base_sha)


def head_sha(worktree: Path) -> str:
    return resolve_sha(worktree, "HEAD")


def changed_files(worktree: Path, base_sha: str, head: str) -> list[str]:
    output = git(worktree, "diff", "--name-only", f"{base_sha}...{head}")
    return sorted(line.strip().replace("\\", "/") for line in output.splitlines() if line.strip())


def validate_worker_git_state(
    worktree: Path,
    *,
    task: TaskSpec,
    base_sha: str,
    result: WorkerResult,
) -> list[str]:
    if result.issue != task.issue_number:
        raise RuntimeError("worker result names a different issue")
    if result.branch != task.branch:
        raise RuntimeError("worker result names a different branch")
    actual_head = head_sha(worktree)
    if actual_head != result.head_sha:
        raise RuntimeError(f"worker result HEAD {result.head_sha} != actual {actual_head}")
    if actual_head == base_sha:
        raise RuntimeError("worker reported success without a new commit")
    status = git(worktree, "status", "--porcelain=v1")
    if status:
        raise RuntimeError("worker left uncommitted or untracked files")
    actual_files = changed_files(worktree, base_sha, actual_head)
    if sorted(result.changed_files) != actual_files:
        raise RuntimeError("worker changed_files does not match the committed diff")
    if not paths_are_allowed(actual_files, task.allowed_paths):
        raise RuntimeError(f"worker changed files outside allowed scope: {actual_files}")
    return actual_files


def push_branch(worktree: Path, branch: str) -> None:
    git(worktree, "push", "--set-upstream", "origin", branch)
