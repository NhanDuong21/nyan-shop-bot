from __future__ import annotations

from pathlib import Path

import pytest

from nyan_shop_bot.orchestrator.models import DesiredState, TaskSpec
from nyan_shop_bot.orchestrator.store import StateStore
from tests.unit.test_orchestrator_models import task_data


def make_task(issue: int, task_id: str, branch: str) -> TaskSpec:
    value = task_data()
    value.update(
        {
            "issue_number": issue,
            "issue_url": f"https://github.com/NhanDuong21/nyan-shop-bot/issues/{issue}",
            "task_id": task_id,
            "branch": branch,
        }
    )
    return TaskSpec.model_validate(value)


def create(store: StateStore, run_id: str, task: TaskSpec, tmp_path: Path) -> None:
    store.create_run(
        run_id=run_id,
        task=task,
        task_path=tmp_path / f"{task.task_id}.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / run_id,
        max_workers=2,
    )


def test_state_and_claim_survive_store_reopen(tmp_path: Path) -> None:
    task = make_task(15, "NSB-041", "nyan/nsb-041-runner-proof")
    store = StateStore(tmp_path / "state")
    create(store, "run-one", task, tmp_path)
    store.set_desired_state("run-one", DesiredState.PAUSED)

    reopened = StateStore(tmp_path / "state")

    assert reopened.get_run("run-one")["desired_state"] == "PAUSED"
    assert reopened.active_claims()[0]["run_id"] == "run-one"


def test_duplicate_issue_claim_is_rejected(tmp_path: Path) -> None:
    task = make_task(15, "NSB-041", "nyan/nsb-041-runner-proof")
    store = StateStore(tmp_path / "state")
    create(store, "run-one", task, tmp_path)

    with pytest.raises(RuntimeError, match="already has active run"):
        create(store, "run-two", task, tmp_path)


def test_global_writer_limit_is_two(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    create(
        store,
        "run-one",
        make_task(15, "NSB-041", "nyan/nsb-041-runner-proof"),
        tmp_path,
    )
    create(
        store,
        "run-two",
        make_task(16, "NSB-042", "nyan/nsb-042-second"),
        tmp_path,
    )

    with pytest.raises(RuntimeError, match="writer limit reached"):
        create(
            store,
            "run-three",
            make_task(17, "NSB-043", "nyan/nsb-043-third"),
            tmp_path,
        )


def test_pause_stop_resume_do_not_create_another_claim(tmp_path: Path) -> None:
    task = make_task(15, "NSB-041", "nyan/nsb-041-runner-proof")
    store = StateStore(tmp_path / "state")
    create(store, "run-one", task, tmp_path)

    store.set_desired_state("run-one", DesiredState.PAUSED)
    store.set_desired_state("run-one", DesiredState.STOPPED)
    store.set_desired_state("run-one", DesiredState.RUNNING)

    assert store.get_run("run-one")["desired_state"] == "RUNNING"
    assert len(store.active_claims()) == 1
