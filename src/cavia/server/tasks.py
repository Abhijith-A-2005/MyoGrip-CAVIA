"""Trial tasks the experimenter picks in the drawer: one object region and the grip the participant is asked to use.

The list is configuration (`config/tasks.json`, or `--tasks PATH`), so the study's task set changes without code.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from cavia.arbitration.candidates import REGION_GRIPS
from cavia.core.grips import full_menu

DEFAULT_TASKS = Path("config/tasks.json")
TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,15}")


@dataclass(frozen=True)
class Task:
    id: str
    object: str
    region: str
    target_grip: str

    def to_dict(self) -> dict:
        return asdict(self)


def parse_tasks(raw: object) -> list[Task]:
    """Validate a `{"tasks": [...]}` document. Every task names a known object region and a calibrated grip."""
    items = raw.get("tasks") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ValueError('Tasks file must be an object with a "tasks" list')
    grips = {g.name for g in full_menu()}
    tasks: list[Task] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Task {i + 1} must be an object")
        field = lambda key: str(item.get(key, "")).strip()  # noqa: E731
        task = Task(field("id"), field("object").lower(), field("region").lower(), field("target_grip").upper())
        if not TASK_ID.fullmatch(task.id):
            raise ValueError(f"Task {i + 1}: id must be 1-16 letters, digits, - or _")
        if any(t.id == task.id for t in tasks):
            raise ValueError(f"Task {task.id}: duplicate id")
        if task.region not in REGION_GRIPS.get(task.object, {}):
            raise ValueError(f"Task {task.id}: unknown object region {task.object}/{task.region}")
        if task.target_grip not in grips:
            raise ValueError(f"Task {task.id}: {task.target_grip} is not a calibrated grip")
        tasks.append(task)
    return tasks


def load_tasks(path: str | Path) -> list[Task]:
    with Path(path).open(encoding="utf-8") as f:
        return parse_tasks(json.load(f))
