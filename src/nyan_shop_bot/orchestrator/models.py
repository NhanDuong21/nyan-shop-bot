"""Validated contracts used at every orchestrator trust boundary."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
TASK_PATTERN = re.compile(r"^NSB-[0-9]{3}$")
BRANCH_PATTERN = re.compile(r"^nyan/[a-z0-9][a-z0-9._/-]*$")


class StrictModel(BaseModel):
    """Reject fields the runner does not understand."""

    model_config = ConfigDict(extra="forbid")


class WorkerKind(StrEnum):
    CODEX = "codex"
    ANTIGRAVITY = "antigravity"


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class WorkerStatus(StrEnum):
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"


class ReviewVerdict(StrEnum):
    PASS = "PASS"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    BLOCKED = "BLOCKED"


class RunPhase(StrEnum):
    CREATED = "CREATED"
    CLAIMED = "CLAIMED"
    WORKER_RUNNING = "WORKER_RUNNING"
    WORKER_COMPLETE = "WORKER_COMPLETE"
    CI_WAITING = "CI_WAITING"
    REVIEW_RUNNING = "REVIEW_RUNNING"
    FIX_REQUESTED = "FIX_REQUESTED"
    READY_FOR_OWNER = "READY_FOR_OWNER"
    MERGE_PENDING_CONFIRMATION = "MERGE_PENDING_CONFIRMATION"
    MERGE_AUTHORIZED = "MERGE_AUTHORIZED"
    OWNER_MERGED = "OWNER_MERGED"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"


class DesiredState(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


class TestEvidence(StrictModel):
    command: str = Field(min_length=1, max_length=500)
    result: EvidenceResult
    evidence: str = Field(min_length=1, max_length=2000)


class Finding(StrictModel):
    severity: Literal["critical", "high", "medium", "low"]
    file: str | None = Field(max_length=500)
    line: int | None = Field(ge=1)
    message: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def line_requires_file(self) -> Self:
        if self.line is not None and self.file is None:
            raise ValueError("finding line requires a file")
        return self


class Budget(StrictModel):
    max_agent_invocations: int = Field(default=5, ge=2, le=8)
    max_total_tokens: int = Field(default=300_000, ge=1_000, le=1_000_000)
    max_elapsed_seconds: int = Field(default=7_200, ge=60, le=43_200)
    max_fix_rounds: int = Field(default=3, ge=0, le=3)
    ci_timeout_seconds: int = Field(default=3_600, ge=60, le=14_400)
    poll_initial_seconds: int = Field(default=5, ge=1, le=60)
    poll_max_seconds: int = Field(default=60, ge=1, le=300)

    @model_validator(mode="after")
    def validate_backoff(self) -> Self:
        if self.poll_initial_seconds > self.poll_max_seconds:
            raise ValueError("poll_initial_seconds cannot exceed poll_max_seconds")
        return self


class TaskSpec(StrictModel):
    schema_version: Literal[1]
    task_id: str
    issue_number: int = Field(ge=1)
    issue_url: str
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    title: str = Field(min_length=1, max_length=200)
    base_ref: str = Field(min_length=1, max_length=200)
    pr_base: str = Field(min_length=1, max_length=200)
    branch: str
    worker: WorkerKind
    worker_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]+$")
    reviewer_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]+$")
    role: Literal["backend", "ui"]
    risk: Risk
    queue_phase: Literal["M0", "M1", "M2", "demo"]
    queue_eligible: bool = False
    trusted_prompt: str = Field(min_length=20, max_length=12_000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=30)
    allowed_paths: list[str] = Field(min_length=1, max_length=30)
    required_checks: list[str] = Field(default_factory=lambda: ["ci-gate"], min_length=1)
    dependencies: list[int] = Field(default_factory=list, max_length=30)
    auto_merge_eligible: bool = False
    budget: Budget = Field(default_factory=Budget)

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        if not TASK_PATTERN.fullmatch(value):
            raise ValueError("task_id must look like NSB-041")
        return value

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, value: str) -> str:
        if not BRANCH_PATTERN.fullmatch(value) or value.endswith("/") or ".." in value:
            raise ValueError("branch must be a safe nyan/* branch")
        if value in {"nyan/main", "nyan/master"}:
            raise ValueError("protected branch names are forbidden")
        return value

    @field_validator("allowed_paths")
    @classmethod
    def validate_allowed_paths(cls, values: list[str]) -> list[str]:
        for value in values:
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts or value.startswith(".git"):
                raise ValueError(f"unsafe allowed path: {value}")
        return values

    @model_validator(mode="after")
    def validate_identity_and_policy(self) -> Self:
        expected = f"https://github.com/{self.repository}/issues/{self.issue_number}"
        if self.issue_url != expected:
            raise ValueError(f"issue_url must equal {expected}")
        if self.role == "ui" and self.worker is not WorkerKind.ANTIGRAVITY:
            raise ValueError("UI tasks must not silently substitute another worker")
        if self.queue_eligible and self.queue_phase == "demo":
            raise ValueError("demo tasks cannot enter the automatic queue")
        if self.auto_merge_eligible and self.risk is not Risk.LOW:
            raise ValueError("only low-risk tasks can request auto-merge eligibility")
        return self


class WorkerResult(StrictModel):
    status: WorkerStatus
    issue: int = Field(ge=1, description="GitHub issue number, not the task ID suffix")
    branch: str
    head_sha: str = Field(
        description="Exact 40-character lowercase HEAD observed before the runner-owned commit"
    )
    changed_files: list[str]
    tests: list[TestEvidence]
    blockers: list[str]
    summary: str = Field(min_length=1, max_length=4000)

    @field_validator("head_sha")
    @classmethod
    def validate_sha(cls, value: str) -> str:
        if not SHA_PATTERN.fullmatch(value):
            raise ValueError("head_sha must be a lowercase 40-character Git SHA")
        return value

    @field_validator("branch")
    @classmethod
    def validate_result_branch(cls, value: str) -> str:
        if not BRANCH_PATTERN.fullmatch(value):
            raise ValueError("worker branch must be a safe nyan/* branch")
        return value

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.status is WorkerStatus.SUCCESS:
            if self.blockers:
                raise ValueError("SUCCESS cannot include blockers")
            if not self.changed_files:
                raise ValueError("SUCCESS must include at least one changed file")
            if not self.tests:
                raise ValueError("SUCCESS must include test evidence")
            if any(test.result is EvidenceResult.FAIL for test in self.tests):
                raise ValueError("SUCCESS cannot include a failed test")
        elif not self.blockers:
            raise ValueError("BLOCKED must explain at least one blocker")
        return self


class ReviewResult(StrictModel):
    verdict: ReviewVerdict
    reviewed_head_sha: str
    findings: list[Finding]
    tests: list[TestEvidence]
    blockers: list[str]
    summary: str = Field(min_length=1, max_length=4000)

    @field_validator("reviewed_head_sha")
    @classmethod
    def validate_sha(cls, value: str) -> str:
        if not SHA_PATTERN.fullmatch(value):
            raise ValueError("reviewed_head_sha must be a lowercase 40-character Git SHA")
        return value

    @model_validator(mode="after")
    def validate_verdict(self) -> Self:
        if self.verdict is ReviewVerdict.PASS:
            if self.findings or self.blockers:
                raise ValueError("PASS cannot include findings or blockers")
            if any(test.result is EvidenceResult.FAIL for test in self.tests):
                raise ValueError("PASS cannot include a failed test")
        if self.verdict is ReviewVerdict.CHANGES_REQUESTED and not self.findings:
            raise ValueError("CHANGES_REQUESTED must include findings")
        if self.verdict is ReviewVerdict.BLOCKED and not self.blockers:
            raise ValueError("BLOCKED must include blockers")
        return self


class Usage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_output_tokens: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.reasoning_output_tokens


class AgentInvocation(StrictModel):
    session_id: str
    result_path: str
    events_path: str
    stderr_path: str
    usage: Usage


class CiEvidence(StrictModel):
    head_sha: str
    run_id: int = Field(ge=1)
    run_url: str
    checks: dict[str, str]

    @field_validator("head_sha")
    @classmethod
    def validate_sha(cls, value: str) -> str:
        if not SHA_PATTERN.fullmatch(value):
            raise ValueError("CI head must be a lowercase 40-character Git SHA")
        return value
