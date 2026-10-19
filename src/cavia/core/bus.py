"""Minimal in-process publish/subscribe bus, safe to publish from worker threads."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable

Handler = Callable[[str, Any], None]

# Well-known topics
VISION = "vision"
MENU = "menu"
EMG = "emg"
FSM = "fsm"


class Bus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> Callable[[], None]:
        """Register a handler; `topic="*"` receives every message. Returns an unsubscribe callable."""
        with self._lock:
            self._handlers[topic].append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._handlers[topic]:
                    self._handlers[topic].remove(handler)

        return unsubscribe

    def publish(self, topic: str, message: Any) -> None:
        # Copy under the lock so handlers can (un)subscribe while being called.
        with self._lock:
            handlers = [*self._handlers[topic], *self._handlers["*"]]
        for handler in handlers:
            handler(topic, message)
