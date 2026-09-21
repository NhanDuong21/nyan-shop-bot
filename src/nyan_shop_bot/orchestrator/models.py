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


class UsageNormalization(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


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
    max_worker_tokens: int | None = Field(default=None, ge=1_000, le=1_000_000)
    max_reviewer_tokens: int | None = Field(default=None, ge=1_000, le=1_000_000)
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

    def token_ceiling(self, role: Literal["worker", "reviewer"]) -> int:
        """Resolve a role ceiling, falling back to the version-1 shared field."""

        configured = self.max_worker_tokens if role == "worker" else self.max_reviewer_tokens
        return configured if configured is not None else self.max_total_tokens


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
        if (self.role == "ui") != (self.worker is WorkerKind.ANTIGRAVITY):
            raise ValueError("UI tasks and Antigravity workers must map to each other exactly")
        if self.worker is WorkerKind.ANTIGRAVITY and self.worker_model is None:
            raise ValueError("Antigravity tasks must pin a discovered worker_model")
        if self.role == "ui":
            exact_feature_grant = re.compile(r"^admin/src/features/[a-z0-9][a-z0-9-]*/\*\*$")
            if len(self.allowed_paths) != 1 or not exact_feature_grant.fullmatch(
                self.allowed_paths[0]
            ):
                raise ValueError(
                    "UI worker scope must be one exact admin/src/features/<slug>/** grant"
                )
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


class UsageAccounting(StrictModel):
    """Raw provider telemetry plus the runner's separate enforcement policy value."""

    raw_input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    fresh_input_tokens: int | None = Field(default=None, ge=0)
    raw_output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    raw_provider_total: int | None = Field(default=None, ge=0)
    normalization_state: UsageNormalization
    enforceable_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_normalized_values(self) -> Self:
        if self.normalization_state is UsageNormalization.COMPLETE:
            components = (
                self.raw_input_tokens,
                self.cached_input_tokens,
                self.raw_output_tokens,
                self.reasoning_tokens,
            )
            if any(value is None for value in components):
                raise ValueError("COMPLETE usage requires every raw component")
            assert self.raw_input_tokens is not None
            assert self.cached_input_tokens is not None
            assert self.raw_output_tokens is not None
            expected_fresh = self.raw_input_tokens - self.cached_input_tokens
            expected_enforceable = expected_fresh + self.raw_output_tokens
            if self.fresh_input_tokens != expected_fresh:
                raise ValueError("fresh input does not match raw input minus cached input")
            if self.enforceable_tokens != expected_enforceable:
                raise ValueError("enforceable tokens do not match fresh input plus raw output")
        if self.normalization_state is UsageNormalization.UNKNOWN:
            raw_values = (
                self.raw_input_tokens,
                self.cached_input_tokens,
                self.raw_output_tokens,
                self.reasoning_tokens,
                self.raw_provider_total,
            )
            if any(value is not None for value in raw_values):
                raise ValueError("UNKNOWN usage cannot contain raw provider telemetry")
            if self.fresh_input_tokens is not None or self.enforceable_tokens is not None:
                raise ValueError("UNKNOWN usage cannot contain derived token values")
        return self


class Usage(StrictModel):
    """Nullable raw telemetry; omitted provider fields never become zero."""

    raw_input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    raw_output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    raw_provider_total: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_subset_relationships(self) -> Self:
        if (
            self.raw_input_tokens is not None
            and self.cached_input_tokens is not None
            and self.cached_input_tokens > self.raw_input_tokens
        ):
            raise ValueError("cached input tokens cannot exceed input tokens")
        if (
            self.raw_output_tokens is not None
            and self.reasoning_tokens is not None
            and self.reasoning_tokens > self.raw_output_tokens
        ):
            raise ValueError("reasoning tokens cannot exceed output tokens")
        return self

    def normalize_codex(self) -> UsageAccounting:
        """Apply the repository's Codex enforcement formula to complete telemetry."""

        components = (
            self.raw_input_tokens,
            self.cached_input_tokens,
            self.raw_output_tokens,
            self.reasoning_tokens,
        )
        if all(value is not None for value in components):
            assert self.raw_input_tokens is not None
            assert self.cached_input_tokens is not None
            assert self.raw_output_tokens is not None
            fresh = self.raw_input_tokens - self.cached_input_tokens
            return UsageAccounting(
                **self.model_dump(),
                fresh_input_tokens=fresh,
                normalization_state=UsageNormalization.COMPLETE,
                enforceable_tokens=fresh + self.raw_output_tokens,
            )
        if all(value is None for value in (*components, self.raw_provider_total)):
            return UsageAccounting(normalization_state=UsageNormalization.UNKNOWN)
        partial_fresh: int | None = None
        if self.raw_input_tokens is not None and self.cached_input_tokens is not None:
            partial_fresh = self.raw_input_tokens - self.cached_input_tokens
        return UsageAccounting(
            **self.model_dump(),
            fresh_input_tokens=partial_fresh,
            normalization_state=UsageNormalization.PARTIAL,
        )

    def normalize_cumulative_provider(self) -> UsageAccounting:
        """Retain provider fields while deferring cumulative-delta enforcement to storage."""

        raw_values = (
            self.raw_input_tokens,
            self.cached_input_tokens,
            self.raw_output_tokens,
            self.reasoning_tokens,
            self.raw_provider_total,
        )
        state = (
            UsageNormalization.UNKNOWN
            if all(value is None for value in raw_values)
            else UsageNormalization.PARTIAL
        )
        return UsageAccounting(**self.model_dump(), normalization_state=state)


class AgentInvocation(StrictModel):
    session_id: str
    result_path: str
    events_path: str
    stderr_path: str
    usage: Usage
    activity_delivered: int = Field(default=0, ge=0)
    activity_dropped: int = Field(default=0, ge=0)
    activity_errors: int = Field(default=0, ge=0)
    activity_clean_shutdown: bool = True


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
