"""GitHub reconciliation and exact-SHA CI evidence using the authenticated gh CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nyan_shop_bot.orchestrator.models import SHA_PATTERN, CiEvidence, DesiredState, TaskSpec

ControlReader = Callable[[], DesiredState]


class PauseRequested(RuntimeError):
    """Raised at a safe wait checkpoint after an owner pause request."""


class StopRequested(RuntimeError):
    """Raised at a safe wait checkpoint after an owner stop request."""


class PullRequestOpen(RuntimeError):
    """Raised when an exact PR is valid but has not merged yet."""


class GitHubClient:
    def __init__(
        self,
        root: Path,
        repository: str,
        *,
        timeout_reader: Callable[[], int] | None = None,
    ) -> None:
        executable = shutil.which("gh")
        if executable is None:
            raise RuntimeError("GitHub CLI is not installed")
        self.executable = executable
        self.root = root
        self.repository = repository
        self.timeout_reader = timeout_reader

    def command(self, *arguments: str, input_text: str | None = None) -> str:
        timeout_seconds = 60
        if self.timeout_reader is not None:
            timeout_seconds = max(1, min(60, self.timeout_reader()))
        try:
            completed = subprocess.run(
                (self.executable, *arguments),
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                input=input_text,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError(f"gh {' '.join(arguments)} exceeded {timeout_seconds}s") from error
        if completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"gh {' '.join(arguments)} failed: {detail}")
        return completed.stdout.strip()

    def json_command(self, *arguments: str) -> Any:
        output = self.command(*arguments)
        return json.loads(output) if output else None

    def validate_issue(self, task: TaskSpec) -> None:
        issue = self.json_command(
            "issue",
            "view",
            str(task.issue_number),
            "--repo",
            self.repository,
            "--json",
            "number,title,state,url",
        )
        if not isinstance(issue, dict):
            raise RuntimeError("GitHub issue response was not an object")
        if issue.get("number") != task.issue_number or issue.get("url") != task.issue_url:
            raise RuntimeError("task spec does not match the GitHub issue")
        if issue.get("state") != "OPEN":
            raise RuntimeError("runner only claims open issues")
        if task.task_id not in str(issue.get("title", "")):
            raise RuntimeError("GitHub issue title does not contain the trusted task ID")

    def issue_state(self, issue_number: int) -> str:
        issue = self.json_command(
            "issue",
            "view",
            str(issue_number),
            "--repo",
            self.repository,
            "--json",
            "state",
        )
        if not isinstance(issue, dict) or issue.get("state") not in {"OPEN", "CLOSED"}:
            raise RuntimeError(f"cannot resolve state for issue {issue_number}")
        return str(issue["state"])

    def ensure_claim(self, task: TaskSpec, run_id: str, base_sha: str) -> None:
        issue = self.json_command(
            "issue",
            "view",
            str(task.issue_number),
            "--repo",
            self.repository,
            "--json",
            "labels",
        )
        labels: set[str] = set()
        if isinstance(issue, dict) and isinstance(issue.get("labels"), list):
            labels = {
                str(label["name"])
                for label in issue["labels"]
                if isinstance(label, dict) and isinstance(label.get("name"), str)
            }
        arguments = [
            "issue",
            "edit",
            str(task.issue_number),
            "--repo",
            self.repository,
        ]
        for label in sorted(item for item in labels if item.startswith("status:")):
            if label != "status:in-progress":
                arguments.extend(("--remove-label", label))
        if "status:in-progress" not in labels:
            arguments.extend(("--add-label", "status:in-progress"))
        if len(arguments) > 6:
            self.command(*arguments)

        marker = f"<!-- nyan-run:{run_id} -->"
        comments = self.json_command(
            "api",
            "--paginate",
            f"repos/{self.repository}/issues/{task.issue_number}/comments?per_page=100",
        )
        existing = False
        if isinstance(comments, list):
            existing = any(
                isinstance(comment, dict) and marker in str(comment.get("body", ""))
                for comment in comments
            )
        if not existing:
            body = (
                f"{marker}\nRunner claim `{run_id}`\n\n"
                f"- Branch: `{task.branch}`\n"
                f"- Base SHA: `{base_sha}`\n"
                f"- Worker: `{task.worker}` / `{task.role}`\n"
                "- Source: trusted version-controlled task spec; issue text is metadata only\n"
                "- Auto-merge: not authorized by this claim"
            )
            self.command(
                "issue",
                "comment",
                str(task.issue_number),
                "--repo",
                self.repository,
                "--body",
                body,
            )

    def mark_in_review(self, task: TaskSpec) -> None:
        self._set_status_label(task.issue_number, "status:in-review")

    def mark_blocked(self, task: TaskSpec, run_id: str, reason: str) -> None:
        self._set_status_label(task.issue_number, "status:blocked")
        self.command(
            "issue",
            "comment",
            str(task.issue_number),
            "--repo",
            self.repository,
            "--body",
            f"<!-- nyan-run-blocked:{run_id} -->\n"
            "Runner state is BLOCKED. Inspect the authenticated local `status` output for the "
            "full reason; error text is intentionally not copied to public GitHub.",
        )

    def _set_status_label(self, issue_number: int, status: str) -> None:
        issue = self.json_command(
            "issue",
            "view",
            str(issue_number),
            "--repo",
            self.repository,
            "--json",
            "labels",
        )
        labels: set[str] = set()
        if isinstance(issue, dict) and isinstance(issue.get("labels"), list):
            labels = {
                str(label["name"])
                for label in issue["labels"]
                if isinstance(label, dict) and isinstance(label.get("name"), str)
            }
        arguments = [
            "issue",
            "edit",
            str(issue_number),
            "--repo",
            self.repository,
        ]
        for label in sorted(item for item in labels if item.startswith("status:")):
            if label != status:
                arguments.extend(("--remove-label", label))
        if status not in labels:
            arguments.extend(("--add-label", status))
        if len(arguments) > 6:
            self.command(*arguments)

    def ensure_pull_request(self, task: TaskSpec, head_sha: str, run_id: str) -> dict[str, Any]:
        values = self.json_command(
            "pr",
            "list",
            "--repo",
            self.repository,
            "--state",
            "all",
            "--head",
            task.branch,
            "--json",
            "number,state,url,headRefOid,baseRefName",
        )
        if isinstance(values, list) and values:
            if len(values) != 1 or not isinstance(values[0], dict):
                raise RuntimeError("ambiguous existing pull requests for branch")
            pull = values[0]
            if pull.get("state") != "OPEN":
                raise RuntimeError("existing pull request is not open; refusing duplicate")
            if pull.get("baseRefName") != task.pr_base:
                raise RuntimeError("existing pull request has an unexpected base")
            if pull.get("headRefOid") != head_sha:
                raise RuntimeError("existing pull request HEAD has not caught up to local HEAD")
            return pull

        body = (
            f"Closes #{task.issue_number}\n\n"
            f"Orchestrator run: `{run_id}`\n"
            f"Exact initial HEAD: `{head_sha}`\n\n"
            "This PR remains open for exact-SHA CI and independent review. "
            "No live supplier/payment operation or production deployment is authorized."
        )
        url = self.command(
            "pr",
            "create",
            "--repo",
            self.repository,
            "--base",
            task.pr_base,
            "--head",
            task.branch,
            "--title",
            f"[{task.task_id}] {task.title}",
            "--body",
            body,
        )
        pull = self.json_command(
            "pr",
            "view",
            url,
            "--repo",
            self.repository,
            "--json",
            "number,state,url,headRefOid,baseRefName",
        )
        if not isinstance(pull, dict) or pull.get("headRefOid") != head_sha:
            raise RuntimeError("created PR does not point at the expected HEAD")
        return pull

    def wait_for_ci(
        self,
        *,
        task: TaskSpec,
        head_sha: str,
        control: ControlReader,
        timeout_seconds: int,
    ) -> CiEvidence:
        deadline = time.monotonic() + timeout_seconds
        delay = task.budget.poll_initial_seconds
        seen_run = False
        while time.monotonic() < deadline:
            self._check_control(control)
            runs = self.json_command(
                "run",
                "list",
                "--repo",
                self.repository,
                "--branch",
                task.branch,
                "--event",
                "pull_request",
                "--limit",
                "20",
                "--json",
                "databaseId,headSha,status,conclusion,url,workflowName,createdAt",
            )
            matches = [
                item
                for item in (runs if isinstance(runs, list) else [])
                if isinstance(item, dict) and item.get("headSha") == head_sha
            ]
            matches.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
            for run in matches[:1]:
                seen_run = True
                run_id = int(run["databaseId"])
                detail = self.json_command(
                    "run",
                    "view",
                    str(run_id),
                    "--repo",
                    self.repository,
                    "--json",
                    "status,conclusion,url,headSha,jobs",
                )
                if not isinstance(detail, dict) or detail.get("headSha") != head_sha:
                    continue
                jobs = detail.get("jobs")
                checks = {
                    str(job.get("name")): str(job.get("conclusion") or job.get("status"))
                    for job in (jobs if isinstance(jobs, list) else [])
                    if isinstance(job, dict)
                }
                missing = [name for name in task.required_checks if name not in checks]
                pending = [
                    name
                    for name in task.required_checks
                    if checks.get(name) in {"queued", "in_progress", "waiting", "pending"}
                ]
                failed = [
                    name
                    for name in task.required_checks
                    if name in checks
                    and checks[name]
                    not in {"success", "queued", "in_progress", "waiting", "pending"}
                ]
                if failed:
                    raise RuntimeError(
                        f"required CI failed for {head_sha}: {failed} ({detail['url']})"
                    )
                if (
                    not missing
                    and not pending
                    and all(checks[name] == "success" for name in task.required_checks)
                ):
                    return CiEvidence(
                        head_sha=head_sha,
                        run_id=run_id,
                        run_url=str(detail["url"]),
                        checks={name: checks[name] for name in task.required_checks},
                    )
            self._controlled_sleep(control, min(delay, max(1, int(deadline - time.monotonic()))))
            delay = min(task.budget.poll_max_seconds, delay * 2)
        qualifier = "after observing a run" if seen_run else "before any exact-HEAD run appeared"
        raise TimeoutError(f"CI timed out for {head_sha} {qualifier}")

    @staticmethod
    def _check_control(control: ControlReader) -> None:
        desired = control()
        if desired is DesiredState.PAUSED:
            raise PauseRequested("pause requested while waiting for CI")
        if desired is DesiredState.STOPPED:
            raise StopRequested("stop requested while waiting for CI")

    @classmethod
    def _controlled_sleep(cls, control: ControlReader, seconds: int) -> None:
        for _ in range(seconds):
            cls._check_control(control)
            time.sleep(1)

    def enable_repository_auto_merge(self) -> None:
        self.command("repo", "edit", self.repository, "--enable-auto-merge")
        value = self.json_command("repo", "view", self.repository, "--json", "autoMergeAllowed")
        if not isinstance(value, dict) or value.get("autoMergeAllowed") is not True:
            raise RuntimeError("GitHub did not confirm auto-merge is enabled")

    def queue_auto_merge(self, pr_number: int, *, expected_head: str) -> None:
        self.command(
            "pr",
            "merge",
            str(pr_number),
            "--repo",
            self.repository,
            "--auto",
            "--squash",
            "--match-head-commit",
            expected_head,
        )

    def merged_commit_if_exact(self, pr_number: int, *, expected_head: str) -> str:
        """Reconcile a manual owner merge without trusting a changed PR head."""

        pull = self.json_command(
            "pr",
            "view",
            str(pr_number),
            "--repo",
            self.repository,
            "--json",
            "state,headRefOid,mergeCommit,url",
        )
        if not isinstance(pull, dict) or pull.get("headRefOid") != expected_head:
            raise RuntimeError("owner merge PR HEAD does not match the reviewed exact SHA")
        state = pull.get("state")
        if state == "OPEN":
            raise PullRequestOpen("owner merge is not complete; PR is still open")
        if state != "MERGED":
            raise RuntimeError(f"owner merge PR entered unexpected state {state}")
        commit = pull.get("mergeCommit")
        merge_sha = commit.get("oid") if isinstance(commit, dict) else None
        if not isinstance(merge_sha, str) or not SHA_PATTERN.fullmatch(merge_sha):
            raise RuntimeError("owner-merged PR did not expose a full merge commit SHA")
        return merge_sha

    def wait_for_merge(
        self,
        *,
        pr_number: int,
        expected_head: str,
        control: ControlReader,
        timeout_seconds: int,
        poll_initial_seconds: int,
        poll_max_seconds: int,
    ) -> str:
        deadline = time.monotonic() + timeout_seconds
        delay = poll_initial_seconds
        while time.monotonic() < deadline:
            self._check_control(control)
            pull = self.json_command(
                "pr",
                "view",
                str(pr_number),
                "--repo",
                self.repository,
                "--json",
                "state,headRefOid,mergeCommit,url",
            )
            if not isinstance(pull, dict) or pull.get("headRefOid") != expected_head:
                raise RuntimeError("auto-merge PR HEAD changed after exact-SHA approval")
            if pull.get("state") == "MERGED":
                commit = pull.get("mergeCommit")
                if not isinstance(commit, dict) or not isinstance(commit.get("oid"), str):
                    raise RuntimeError("merged PR did not expose a merge commit")
                return str(commit["oid"])
            if pull.get("state") != "OPEN":
                raise RuntimeError(f"auto-merge PR entered unexpected state {pull.get('state')}")
            self._controlled_sleep(control, min(delay, max(1, int(deadline - time.monotonic()))))
            delay = min(poll_max_seconds, delay * 2)
        raise TimeoutError("GitHub auto-merge did not complete within the task limit")

    def wait_for_main_delivery(
        self,
        *,
        commit_sha: str,
        control: ControlReader,
        timeout_seconds: int,
        poll_initial_seconds: int,
        poll_max_seconds: int,
    ) -> CiEvidence:
        """Require the trusted main push gate and GHCR publish for the merge commit."""

        required = ("ci-gate", "Publish trusted main images")
        deadline = time.monotonic() + timeout_seconds
        delay = poll_initial_seconds
        while time.monotonic() < deadline:
            self._check_control(control)
            runs = self.json_command(
                "run",
                "list",
                "--repo",
                self.repository,
                "--branch",
                "main",
                "--event",
                "push",
                "--limit",
                "20",
                "--json",
                "databaseId,headSha,status,conclusion,url,createdAt",
            )
            matches = [
                item
                for item in (runs if isinstance(runs, list) else [])
                if isinstance(item, dict) and item.get("headSha") == commit_sha
            ]
            matches.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
            for run in matches[:1]:
                run_id = int(run["databaseId"])
                detail = self.json_command(
                    "run",
                    "view",
                    str(run_id),
                    "--repo",
                    self.repository,
                    "--json",
                    "status,conclusion,url,headSha,jobs",
                )
                if not isinstance(detail, dict) or detail.get("headSha") != commit_sha:
                    continue
                jobs = detail.get("jobs")
                checks = {
                    str(job.get("name")): str(job.get("conclusion") or job.get("status"))
                    for job in (jobs if isinstance(jobs, list) else [])
                    if isinstance(job, dict)
                }
                failed = [
                    name
                    for name in required
                    if name in checks
                    and checks[name]
                    not in {"success", "queued", "in_progress", "waiting", "pending"}
                ]
                if failed:
                    raise RuntimeError(
                        f"trusted main delivery failed for {commit_sha}: {failed} ({detail['url']})"
                    )
                if all(checks.get(name) == "success" for name in required):
                    return CiEvidence(
                        head_sha=commit_sha,
                        run_id=run_id,
                        run_url=str(detail["url"]),
                        checks={name: checks[name] for name in required},
                    )
            self._controlled_sleep(control, min(delay, max(1, int(deadline - time.monotonic()))))
            delay = min(poll_max_seconds, delay * 2)
        raise TimeoutError("trusted main CI/GHCR delivery did not complete for the merge commit")
