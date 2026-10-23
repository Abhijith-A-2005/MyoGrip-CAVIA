"""Experimenter session state driven by the dashboard drawer (docs/interfaces.md section 9)."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable

from cavia.core.contracts import Condition

from .tasks import Task

Audit = Callable[..., None]

PARTICIPANT_ID = re.compile(r"[A-Z0-9][A-Z0-9_-]{0,23}")


def participant_id(value: object) -> str:
    """Normalised participant / user ID: upper case, letters, digits, - and _, up to 24 characters."""
    result = str(value if value is not None else "").strip().upper()
    if not result:
        raise ValueError("participant is required")
    if not PARTICIPANT_ID.fullmatch(result):
        raise ValueError("Use letters, digits, - or _ (up to 24 characters) for the participant ID")
    return result


@dataclass
class SessionState:
    participant: str = "P01"
    condition: str = Condition.C3_ADAPTIVE.value
    trial: int = 0
    trial_active: bool = False
    task: dict | None = None        # the running trial's task (Task.to_dict), None for a free trial
    practice: bool = False          # the running trial is practice (excluded from analysis)
    rest: int = 0                   # rest windows started so far
    rest_active: bool = False


class Session:
    """Applies drawer controls, publishes the result and records it through `audit`."""

    def __init__(self, publish: Callable[[str, dict], None], audit: Audit | None = None,
                 participant: str = "P01", condition: Condition = Condition.C3_ADAPTIVE,
                 tasks: list[Task] | None = None, clock: Callable[[], float] = time.monotonic):
        self._lock = threading.Lock()
        self._publish = publish
        self._audit = audit or (lambda event, **data: None)
        self._clock = clock
        self._rest_started = 0.0
        self.tasks = {t.id: t for t in tasks or []}
        self.state = SessionState(participant=participant, condition=condition.value)

    def announce(self) -> None:
        self._publish("tasks", {"tasks": [t.to_dict() for t in self.tasks.values()]})
        self._publish("session", asdict(self.state))

    def control(self, data: dict) -> None:
        """Apply one `control` message. Invalid requests are rejected with ValueError."""
        action = data.get("action")
        with self._lock:
            s = self.state
            if action == "set_session":
                if s.trial_active or s.rest_active:
                    raise ValueError("End the current trial or rest before changing the session")
                # Validate everything before changing anything, so a rejected request has no effect.
                participant = participant_id(data.get("participant"))
                condition = Condition(data.get("condition")).value
                s.participant, s.condition = participant, condition
                self._audit("session_start", participant=s.participant, condition=s.condition)
            elif action == "start_trial":
                if s.trial_active:
                    raise ValueError("A trial is already running")
                if s.rest_active:
                    raise ValueError("End the rest window before starting a trial")
                task_id = data.get("task_id")
                if task_id is not None and task_id not in self.tasks:
                    raise ValueError(f"Unknown task: {task_id}")
                task = self.tasks[task_id].to_dict() if task_id is not None else None
                s.trial += 1
                s.trial_active = True
                s.task = task
                s.practice = bool(data.get("practice"))
                # Task fields are always present (None for a free trial), so logs have one shape.
                self._audit("trial_start", trial=s.trial, task_id=task_id,
                            object=task and task["object"], region=task and task["region"],
                            target_grip=task and task["target_grip"], practice=s.practice)
            elif action == "end_trial":
                if not s.trial_active:
                    raise ValueError("No trial is running")
                s.trial_active = False
                self._audit("trial_end", trial=s.trial, grasp_success=bool(data.get("grasp_success")),
                            notes=str(data.get("notes", ""))[:2000])
                s.task, s.practice = None, False
            elif action == "start_rest":
                if s.trial_active:
                    raise ValueError("End the trial before starting a rest window")
                if s.rest_active:
                    raise ValueError("A rest window is already running")
                s.rest += 1
                s.rest_active = True
                self._rest_started = self._clock()
                self._audit("rest_start", rest=s.rest)
            elif action == "end_rest":
                if not s.rest_active:
                    raise ValueError("No rest window is running")
                s.rest_active = False
                self._audit("rest_end", rest=s.rest, duration_s=round(self._clock() - self._rest_started, 3))
            else:
                raise ValueError(f"Unknown control action: {action}")
            snapshot = asdict(s)
        self._publish("session", snapshot)
