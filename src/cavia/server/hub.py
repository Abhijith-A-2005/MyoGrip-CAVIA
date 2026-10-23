"""Latest dashboard state plus the connected browsers (docs/interfaces.md section 9)."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import Any

STATE_KINDS = ("vision", "menu", "fsm", "system", "session", "users", "tasks")
KINDS = frozenset((*STATE_KINDS, "emg", "notice"))   # emg and notice are events, not state

EMG_KEEP = 40
CLIENT_QUEUE = 256


class Hub:
    """Holds the latest message of each kind and fans updates out to every browser.

    `publish` is safe from any thread (vision and the runtime loop run on their own threads).
    A slow browser loses its oldest queued updates rather than ever blocking the runtime.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, Any] = dict.fromkeys(STATE_KINDS)
        self._emg: deque[dict] = deque(maxlen=EMG_KEEP)
        self._clients: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once the server's event loop is running."""
        self._loop = loop

    def publish(self, kind: str, data: Any) -> None:
        if kind not in KINDS:
            raise ValueError(f"Unknown dashboard message type: {kind}")
        with self._lock:
            if kind == "emg":
                self._emg.append(data)
            elif kind != "notice":
                self._state[kind] = data
            clients = list(self._clients)
            loop = self._loop
        if loop is None or not clients:
            return
        message = {"type": kind, "data": data}
        try:
            loop.call_soon_threadsafe(_deliver, clients, message)
        except RuntimeError:
            pass  # loop already closed during shutdown

    def snapshot(self) -> dict:
        with self._lock:
            return {**self._state, "emg_recent": list(self._emg)}

    def latest(self, kind: str) -> Any:
        with self._lock:
            return self._state[kind]

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def add_client(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE)
        with self._lock:
            self._clients.add(queue)
        return queue

    def remove_client(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._clients.discard(queue)


def _deliver(clients: list[asyncio.Queue], message: dict) -> None:
    for queue in clients:
        if queue.full():
            queue.get_nowait()  # drop the oldest update for a client that is falling behind
        queue.put_nowait(message)
