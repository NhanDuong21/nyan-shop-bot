from __future__ import annotations

from nyan_shop_bot.orchestrator.models import TaskSpec
from nyan_shop_bot.orchestrator.policy import (
    auto_merge_policy,
    paths_are_allowed,
    protected_paths,
)
from tests.unit.test_orchestrator_models import task_data


def make_task(**updates: object) -> TaskSpec:
    value = task_data()
    value.update(updates)
    return TaskSpec.model_validate(value)


def test_worker_scope_is_fail_closed() -> None:
    assert paths_are_allowed(["docs/runner-demo.md"], ["docs/runner-demo.md"])
    assert not paths_are_allowed(
        ["docs/runner-demo.md", ".github/workflows/ci.yml"],
        ["docs/runner-demo.md"],
    )


def test_runner_and_workflow_paths_are_protected() -> None:
    assert protected_paths(
        ["src/nyan_shop_bot/orchestrator/service.py", ".github/workflows/ci.yml"]
    ) == ["src/nyan_shop_bot/orchestrator/service.py", ".github/workflows/ci.yml"]


def test_auto_merge_remains_closed_even_for_an_otherwise_eligible_task() -> None:
    eligible = make_task(
        auto_merge_eligible=True,
        pr_base="main",
        base_ref="main",
        queue_phase="M1",
        queue_eligible=True,
    )

    assert not auto_merge_policy(eligible, ["docs/runner-demo.md"], owner_authorized=True)
    assert not auto_merge_policy(eligible, ["AGENTS.md"], owner_authorized=True)
    assert not auto_merge_policy(eligible, ["docs/runner-demo.md"], owner_authorized=False)
    assert not auto_merge_policy(
        make_task(auto_merge_eligible=False),
        ["docs/runner-demo.md"],
        owner_authorized=True,
    )
