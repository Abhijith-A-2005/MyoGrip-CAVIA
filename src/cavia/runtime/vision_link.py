"""Optional, local-only result transport. No camera or detector logic lives here."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time

PORT_ENV = "CAVIA_RESULT_PORT"
CONTROL_ENV = "CAVIA_CONTROL_STDIN"
FRAME_PORT_ENV = "CAVIA_FRAME_PORT"
_publisher: socket.socket | None = None

# Camera frames for the dashboard: [uint32 length][float64 capture time (time.monotonic)][JPEG].
FRAME_HEADER = struct.Struct("!Id")
FRAME_MAX_BYTES = 2 * 1024 * 1024
FRAME_MIN_INTERVAL = 0.05   # at most ~20 frames per second to the dashboard


def publish_result(result: dict, *, generation: int = 0) -> None:
    """Forward tracker output when launched by the live simulator.

    Standalone vision has no result port configured, so this becomes a no-op.
    """
    global _publisher

    port = os.environ.get(PORT_ENV)
    if not port:
        return

    if _publisher is None:
        _publisher = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _publisher.setblocking(False)

    packet = dict(
        result,
        ts=time.monotonic(),
        generation=generation,
    )

    try:
        _publisher.sendto(
            json.dumps(packet, allow_nan=False).encode(),
            ("127.0.0.1", int(port)),
        )
    except (OSError, ValueError):
        # Never stall the detector because the receiver is shutting down.
        pass


def decode_result(raw: bytes, now: float) -> dict | None:
    """Reject malformed/future packets; preserve vision confidence unchanged."""
    try:
        p = json.loads(raw)

        if not isinstance(p, dict):
            return None

        stamp = p["ts"]
        confidence = p["region_confidence"]
        generation = p.get("generation", 0)

        if type(generation) is not int or generation < 0:
            return None

        p["generation"] = generation

        for value in (stamp, confidence):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                return None

        if stamp < 0 or stamp > now or not 0 <= confidence <= 1:
            return None

        if (
            p["state"] not in {"NO_OBJECT", "SEARCHING", "LOCKED", "LOST"}
            or type(p["stable"]) is not bool
        ):
            return None

        if p["stable"] != (p["state"] == "LOCKED"):
            return None

        for field in ("object", "region"):
            if p[field] is not None and (
                not isinstance(p[field], str)
                or not p[field].strip()
            ):
                return None

        if p["stable"] and p["object"] is None:
            return None

        return p

    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        return None



class FrameSender:
    """Sends the newest camera frame to the dashboard server on a background thread.

    Holds a single slot: a frame waiting to be sent is replaced by a newer one, so a slow or
    absent server can never delay detection. Reconnects once a second if the server goes away.
    """

    def __init__(self, port: int, min_interval: float = FRAME_MIN_INTERVAL):
        self._port = port
        self._min_interval = min_interval
        self._cond = threading.Condition()
        self._slot: tuple[bytes, float] | None = None
        self._last_offer = -math.inf
        threading.Thread(target=self._run, name="frame-sender", daemon=True).start()

    def wants_frame(self, now: float) -> bool:
        return now - self._last_offer >= self._min_interval

    def offer(self, jpeg: bytes, captured_at: float) -> None:
        if not jpeg or len(jpeg) > FRAME_MAX_BYTES:
            return
        with self._cond:
            self._slot = (jpeg, captured_at)
            self._last_offer = time.monotonic()
            self._cond.notify()

    def _run(self) -> None:
        sock = None
        while True:
            with self._cond:
                while self._slot is None:
                    self._cond.wait()
                jpeg, captured_at = self._slot
                self._slot = None
            try:
                if sock is None:
                    sock = socket.create_connection(("127.0.0.1", self._port), timeout=1.0)
                sock.sendall(FRAME_HEADER.pack(len(jpeg), captured_at) + jpeg)
            except OSError:
                if sock is not None:
                    sock.close()
                sock = None
                time.sleep(1.0)


_frame_sender: FrameSender | None = None


def frame_wanted(now: float | None = None) -> bool:
    """True when launched by the dashboard server and a new frame is due (rate limit).

    Lets the detector skip JPEG encoding entirely when nobody is listening.
    """
    global _frame_sender

    if _frame_sender is None:
        port = os.environ.get(FRAME_PORT_ENV)
        if not port:
            return False
        _frame_sender = FrameSender(int(port))
    return _frame_sender.wants_frame(time.monotonic() if now is None else now)


def publish_frame(jpeg: bytes, captured_at: float) -> None:
    """Hand a JPEG-encoded camera frame to the server. No-op when not launched by it."""
    if _frame_sender is not None:
        _frame_sender.offer(jpeg, captured_at)


class DetectionControl:
    """Read parent commands without blocking the camera/GUI thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._paused = False
        self._generation = 0

        if os.environ.get(CONTROL_ENV) == "1":
            threading.Thread(
                target=self._read,
                args=(sys.stdin,),
                daemon=True,
            ).start()

    def snapshot(self) -> tuple[bool, int]:
        with self._lock:
            return self._paused, self._generation

    def _read(self, source):
        for line in source:
            try:
                command = json.loads(line)
                paused = command["paused"]
                generation = command["generation"]

                if (
                    type(paused) is not bool
                    or type(generation) is not int
                    or generation < 0
                ):
                    continue

                with self._lock:
                    if generation > self._generation:
                        self._paused = paused
                        self._generation = generation

            except (ValueError, TypeError, KeyError):
                continue


class VisionProcess:
    """Own the vision child process and receive its newest valid result."""

    def __init__(self, script: Path, extra_env: dict[str, str] | None = None):
        self.script = script.resolve()
        self.extra_env = dict(extra_env or {})

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)

        self.process: subprocess.Popen | None = None
        self.last_stamp = -1.0
        self.generation = 0
        self.paused = False
        self.control_error = None

    def start(self) -> None:
        env = os.environ.copy()
        env[PORT_ENV] = str(self.sock.getsockname()[1])
        env[CONTROL_ENV] = "1"
        env.update(self.extra_env)

        # Retain the vision directory for .env and YOLO weights.
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(self.script)],
            cwd=self.script.parent,
            env=env,
            stdin=subprocess.PIPE,
            text=True,
        )

    def set_paused(self, paused: bool) -> None:
        """Advance generation so old in-flight results cannot be reused."""
        self.generation += 1
        self.paused = paused

        command = {
            "paused": paused,
            "generation": self.generation,
        }

        try:
            if (
                self.process is None
                or self.process.stdin is None
                or self.exited
            ):
                raise OSError("vision process is not running")

            self.process.stdin.write(json.dumps(command) + "\n")
            self.process.stdin.flush()
            self.control_error = None

        except (OSError, ValueError) as error:
            self.control_error = str(error)

    def latest(self) -> dict | None:
        latest = None

        for _ in range(256):
            try:
                raw = self.sock.recv(8192)
            except BlockingIOError:
                break

            p = decode_result(raw, time.monotonic())

            if (
                p is not None
                and not self.paused
                and p["generation"] == self.generation
                and p["ts"] > self.last_stamp
            ):
                self.last_stamp = p["ts"]
                latest = p

        return latest

    @property
    def exited(self) -> bool:
        return (
            self.process is not None
            and self.process.poll() is not None
        )

    def close(self) -> None:
        try:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()

                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)

        finally:
            if self.process is not None and self.process.stdin is not None:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass

            self.sock.close()