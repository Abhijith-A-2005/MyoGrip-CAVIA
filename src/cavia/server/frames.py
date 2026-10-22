"""Camera frames from the vision process, for the dashboard's /video stream."""

from __future__ import annotations

import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from statistics import median

from cavia.runtime.vision_link import FRAME_HEADER, FRAME_MAX_BYTES

JPEG_MAGIC = b"\xff\xd8"


@dataclass(frozen=True)
class Frame:
    jpeg: bytes
    seq: int
    captured_at: float   # time.monotonic() when vision received it from the camera
    received_at: float   # time.monotonic() when it reached the server


def _recv_exact(conn: socket.socket, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


class FrameReceiver:
    """Accepts the vision process's frame connection on 127.0.0.1 and keeps the newest frame.

    Malformed frames close the connection; vision reconnects by itself.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._seq = 0
        self._recent: deque[tuple[float, float]] = deque(maxlen=120)   # (received_at, latency_s)
        self._closed = threading.Event()
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self._server.settimeout(0.5)
        threading.Thread(target=self._accept_loop, name="frame-receiver", daemon=True).start()

    @property
    def port(self) -> int:
        return self._server.getsockname()[1]

    def latest(self) -> Frame | None:
        with self._lock:
            return self._latest

    def stats(self) -> tuple[float, int] | None:
        """(fps over the last second, median latency in ms), or None if no frame in the last second."""
        now = self._clock()
        with self._lock:
            recent = [(t, lat) for t, lat in self._recent if now - t <= 1.0]
        if not recent:
            return None
        return float(len(recent)), round(median(lat for _, lat in recent) * 1000)

    def close(self) -> None:
        self._closed.set()
        self._server.close()

    def _accept_loop(self) -> None:
        while not self._closed.is_set():
            try:
                conn, _ = self._server.accept()
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(5.0)
                self._read(conn)

    def _read(self, conn: socket.socket) -> None:
        while not self._closed.is_set():
            try:
                header = _recv_exact(conn, FRAME_HEADER.size)
                if header is None:
                    return
                length, captured_at = FRAME_HEADER.unpack(header)
                if not 0 < length <= FRAME_MAX_BYTES:
                    return
                jpeg = _recv_exact(conn, length)
            except OSError:
                return
            if jpeg is None or not jpeg.startswith(JPEG_MAGIC):
                return
            now = self._clock()
            with self._lock:
                self._seq += 1
                self._latest = Frame(jpeg, self._seq, captured_at, now)
                self._recent.append((now, max(0.0, now - captured_at)))
