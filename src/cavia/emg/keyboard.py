"""Keyboard stand-in for EMG while hardware is unavailable.

Terminals do not report key-up, so actuation activity is latched (toggle) rather than held.
"""

from __future__ import annotations

import os
import sys
import time

from cavia.core.contracts import Activity, EmgEvent, EmgInput

EVENT_KEYS = {
    "1": EmgEvent.SF,
    "2": EmgEvent.SE,
    "3": EmgEvent.LF,
    "4": EmgEvent.LE,
    "5": EmgEvent.HE,
}

ACTIVITY_KEYS = {
    "f": Activity.FLEX_ACTIVE,
    "e": Activity.EXT_ACTIVE,
    " ": Activity.REST,
    "x": Activity.INVALID,
}

HELP = (
    "EMG keys  1 SF next | 2 SE prev | 3 LF confirm | 4 LE full menu | 5 HE back\n"
    "Actuation f flex (close) | e extend (open) | space rest (hold) | x invalid\n"
    "Sim       m load mock menu (from HOME) | q quit"
)


def key_to_input(key: str, ts: float) -> EmgInput | None:
    if key in EVENT_KEYS:
        return EmgInput(ts=ts, source="keyboard", event=EVENT_KEYS[key])
    if key.lower() in ACTIVITY_KEYS:
        return EmgInput(ts=ts, source="keyboard", activity=ACTIVITY_KEYS[key.lower()])
    return None


class KeyReader:
    """Non-blocking single-key reader: termios on Linux/macOS, msvcrt on Windows."""

    def __enter__(self) -> KeyReader:
        if os.name != "nt":
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc: object) -> None:
        if os.name != "nt":
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)

    def read(self, timeout: float) -> str | None:
        """Return one key, or None if nothing was pressed within `timeout` seconds."""
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + timeout
            while True:
                if msvcrt.kbhit():
                    return msvcrt.getwch()
                if time.monotonic() >= deadline:
                    return None
                time.sleep(0.005)

        import select

        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if ready else None
