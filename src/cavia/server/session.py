"""Experimenter session state driven by the dashboard drawer (docs/interfaces.md section 9)."""

from __future__ import annotations

import re
import threading
from dataclasses import asdict, dataclass
from typing import Callable

from cavia.core.contracts import Condition

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


class Session:
    """Applies drawer controls, publishes the result and records it through `audit`."""

    def __init__(self, publish: Callable[[str, dict], None], audit: Audit | None = None,
                 participant: str = "P01", condition: Condition = Condition.C3_ADAPTIVE):
        self._lock = threading.Lock()
        self._publish = publish
        self._audit = audit or (lambda event, **data: None)
        self.state = SessionState(participant=participant, condition=condition.value)

    def announce(self) -> None:
        self._publish("session", asdict(self.state))

    def control(self, data: dict) -> None:
        """Apply one `control` message. Invalid requests are rejected with ValueError."""
        action = data.get("action")
        with self._lock:
            s = self.state
            if action == "set_session":
                if s.trial_active:
                    raise ValueError("End the current trial before changing the session")
                # Validate everything before changing anything, so a rejected request has no effect.
                participant = participant_id(data.get("participant"))
                condition = Condition(data.get("condition")).value
                s.participant, s.condition = participant, condition
                self._audit("session_start", participant=s.participant, condition=s.condition)
            elif action == "start_trial":
                if s.trial_active:
                    raise ValueError("A trial is already running")
                s.trial += 1
                s.trial_active = True
                self._audit("trial_start", trial=s.trial)
            elif action == "end_trial":
                if not s.trial_active:
                    raise ValueError("No trial is running")
                s.trial_active = False
                self._audit("trial_end", trial=s.trial, grasp_success=bool(data.get("grasp_success")),
                            notes=str(data.get("notes", ""))[:2000])
            else:
                raise ValueError(f"Unknown control action: {action}")
            snapshot = asdict(s)
        self._publish("session", snapshot)
