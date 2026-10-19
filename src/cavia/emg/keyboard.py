"""Keyboard stand-in for EMG while hardware is unavailable.

Menu mode: one key press = one discrete gesture (W SE up, S SF down, A LF confirm, D LE full menu, E HE back).
Actuation mode: holding A = flexor active (close), holding D = extensor active (open), nothing held = rest.

Mirrors the real EMG rules: one press emits at most one event (no auto-repeat), a gesture started while
another gesture key is still held is ambiguous and becomes INVALID, and A + D together is co-contraction
(INVALID activity). Needs real key-up events, so it is driven by a GUI (see cavia.fsm.sim), not a terminal.
"""

from __future__ import annotations

from cavia.core.contracts import Activity, EmgEvent

GESTURE_KEYS: dict[str, EmgEvent] = {
    "w": EmgEvent.SE,   # previous / up
    "s": EmgEvent.SF,   # next / down
    "a": EmgEvent.LF,   # confirm
    "d": EmgEvent.LE,   # full menu
    "e": EmgEvent.HE,   # back / cancel
}

FLEX_KEY = "a"
EXT_KEY = "d"

HELP = [
    "W  up (SE)        S  down (SF)",
    "A  confirm (LF)   D  full menu (LE)",
    "E  back / cancel (HE)",
    "Actuation: hold A = close, hold D = open, release = hold",
    "After confirming, release A before holding it again to close",
    "M  reload menu (from HOME)   Q / Esc  quit",
]


class KeyboardEmg:
    def __init__(self) -> None:
        self.held: set[str] = set()

    def press(self, key: str) -> EmgEvent | None:
        """Key went down. Returns the discrete gesture, or None for non-gesture keys and repeats."""
        key = key.lower()
        if key not in GESTURE_KEYS or key in self.held:
            return None
        ambiguous = bool(self.held)
        self.held.add(key)
        return EmgEvent.INVALID if ambiguous else GESTURE_KEYS[key]

    def release(self, key: str) -> None:
        self.held.discard(key.lower())

    def release_all(self) -> None:
        """Window lost focus: key-ups will never arrive, so treat everything as released."""
        self.held.clear()

    def activity(self) -> Activity:
        flex = FLEX_KEY in self.held
        ext = EXT_KEY in self.held
        if flex and ext:
            return Activity.INVALID
        if flex:
            return Activity.FLEX_ACTIVE
        if ext:
            return Activity.EXT_ACTIVE
        return Activity.REST
