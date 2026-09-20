from __future__ import annotations

import pytest
from pydantic import ValidationError

from nyan_shop_bot.orchestrator.models import (
    ReviewResult,
    TaskSpec,
    WorkerResult,
)


def task_data() -> dict[str, object]:
    return {
        "schema_version": 1,
        "task_id": "NSB-041",
        "issue_number": 15,
        "issue_url": "https://github.com/NhanDuong21/nyan-shop-bot/issues/15",
        "repository": "NhanDuong21/nyan-shop-bot",
        "title": "Runner proof",
        "base_ref": "nyan/nsb-040-agent-runner",
        "pr_base": "nyan/nsb-040-agent-runner",
        "branch": "nyan/nsb-041-runner-proof",
        "worker": "codex",
        "role": "backend",
        "risk": "low",
        "queue_phase": "demo",
        "queue_eligible": False,
        "trusted_prompt": "Create the bounded runner proof document and nothing else.",
        "acceptance_criteria": ["Document all control commands."],
        "allowed_paths": ["docs/runner-demo.md"],
        "required_checks": ["ci-gate"],
        "dependencies": [],
        "auto_merge_eligible": False,
        "budget": {
            "max_agent_invocations": 5,
            "max_total_tokens": 100000,
            "max_elapsed_seconds": 3600,
            "max_fix_rounds": 3,
            "ci_timeout_seconds": 1200,
            "poll_initial_seconds": 2,
            "poll_max_seconds": 30,
        },
    }


def test_task_spec_rejects_silent_ui_worker_substitution() -> None:
    value = task_data()
    value.update({"role": "ui", "worker": "codex"})

    with pytest.raises(ValidationError, match="map to each other exactly"):
        TaskSpec.model_validate(value)


def test_ui_task_rejects_admin_wide_scope_before_adapter_launch() -> None:
    value = task_data()
    value.update(
        {
            "worker": "antigravity",
            "worker_model": "gemini-3.8-flash-low",
            "role": "ui",
            "allowed_paths": ["admin/**"],
        }
    )

    with pytest.raises(ValidationError, match="admin/src/features"):
        TaskSpec.model_validate(value)


@pytest.mark.parametrize(
    "allowed_paths",
    [
        ["admin/src/features/**"],
        ["admin/src/features/*/**"],
        [
            "admin/src/features/catalog-proof/**",
            "admin/src/features/second-proof/**",
        ],
    ],
)
def test_ui_task_rejects_broad_or_multi_root_grants(allowed_paths: list[str]) -> None:
    value = task_data()
    value.update(
        {
            "worker": "antigravity",
            "worker_model": "gemini-3.8-flash-low",
            "role": "ui",
            "allowed_paths": allowed_paths,
        }
    )

    with pytest.raises(ValidationError, match="one exact"):
        TaskSpec.model_validate(value)


def test_antigravity_worker_requires_ui_role_and_pinned_model() -> None:
    backend = task_data()
    backend.update({"worker": "antigravity", "worker_model": "gemini-3.8-flash-low"})
    with pytest.raises(ValidationError, match="map to each other exactly"):
        TaskSpec.model_validate(backend)

    unpinned = task_data()
    unpinned.update(
        {
            "worker": "antigravity",
            "role": "ui",
            "allowed_paths": ["admin/src/features/catalog-proof/**"],
        }
    )
    with pytest.raises(ValidationError, match="pin a discovered"):
        TaskSpec.model_validate(unpinned)


def test_task_spec_rejects_untrusted_path_escape() -> None:
    value = task_data()
    value["allowed_paths"] = ["../outside"]

    with pytest.raises(ValidationError, match="unsafe allowed path"):
        TaskSpec.model_validate(value)


def test_worker_success_requires_tests_and_exact_shape() -> None:
    with pytest.raises(ValidationError, match="test evidence"):
        WorkerResult.model_validate(
            {
                "status": "SUCCESS",
                "issue": 15,
                "branch": "nyan/nsb-041-runner-proof",
                "head_sha": "a" * 40,
                "changed_files": ["docs/runner-demo.md"],
                "tests": [],
                "blockers": [],
                "summary": "done",
            }
        )


def test_review_pass_cannot_hide_findings() -> None:
    with pytest.raises(ValidationError, match="PASS cannot include"):
        ReviewResult.model_validate(
            {
                "verdict": "PASS",
                "reviewed_head_sha": "a" * 40,
                "findings": [
                    {
                        "severity": "low",
                        "file": None,
                        "line": None,
                        "message": "unresolved",
                        "evidence": "present",
                    }
                ],
                "tests": [],
                "blockers": [],
                "summary": "incorrect pass",
            }
        )


def test_review_pass_cannot_hide_failed_test_evidence() -> None:
    with pytest.raises(ValidationError, match="PASS cannot include a failed test"):
        ReviewResult.model_validate(
            {
                "verdict": "PASS",
                "reviewed_head_sha": "a" * 40,
                "findings": [],
                "tests": [
                    {
                        "command": "pytest",
                        "result": "FAIL",
                        "evidence": "One regression failed.",
                    }
                ],
                "blockers": [],
                "summary": "incorrect pass",
            }
        )


def test_generated_schemas_forbid_unknown_fields() -> None:
    worker_schema = WorkerResult.model_json_schema()
    review_schema = ReviewResult.model_json_schema()

    assert worker_schema["additionalProperties"] is False
    assert review_schema["additionalProperties"] is False
    finding_schema = review_schema["$defs"]["Finding"]
    assert set(finding_schema["required"]) == {
        "severity",
        "file",
        "line",
        "message",
        "evidence",
    }
