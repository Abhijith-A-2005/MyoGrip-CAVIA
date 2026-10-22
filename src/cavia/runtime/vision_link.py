"""Optional, local-only result transport. No camera or detector logic lives here."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

PORT_ENV = "CAVIA_RESULT_PORT"
CONTROL_ENV = "CAVIA_CONTROL_STDIN"
_publisher: socket.socket | None = None


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

    def __init__(self, script: Path):
        self.script = script.resolve()

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