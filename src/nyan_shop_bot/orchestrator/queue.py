"""Pure trusted-backlog selection policy."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from nyan_shop_bot.orchestrator.models import TaskSpec

PHASE_ORDER = {"M0": 0, "M1": 1, "M2": 2}


def select_ready_task(
    tasks: Iterable[TaskSpec],
    *,
    issue_state: Callable[[int], str],
    task_has_run: Callable[[str], bool],
) -> TaskSpec | None:
    """Pick the first trusted M0-M2 task whose issue is open and dependencies closed."""

    candidates = sorted(
        (
            task
            for task in tasks
            if task.queue_eligible
            and task.queue_phase in PHASE_ORDER
            and not task_has_run(task.task_id)
        ),
        key=lambda task: (PHASE_ORDER[task.queue_phase], task.task_id),
    )
    for task in candidates:
        if issue_state(task.issue_number) != "OPEN":
            continue
        if all(issue_state(number) == "CLOSED" for number in task.dependencies):
            return task
    return None
