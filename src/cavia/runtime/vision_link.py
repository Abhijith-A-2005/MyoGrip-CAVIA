"""Optional, local-only result transport. No camera or detector logic lives here."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

PORT_ENV = "CAVIA_RESULT_PORT"
_publisher: socket.socket | None = None


def publish_result(result: dict) -> None:
    """Called for every tracker output, including unchanged locks and lost targets.

    Standalone vision has no port configured, so this becomes a no-op.
    """
    global _publisher
    port = os.environ.get(PORT_ENV)
    if not port:
        return
    if _publisher is None:
        _publisher = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _publisher.setblocking(False)
    packet = dict(result, ts=time.monotonic())
    try:
        _publisher.sendto(json.dumps(packet, allow_nan=False).encode(), ("127.0.0.1", int(port)))
    except (OSError, ValueError):
        # The receiver may be shutting down. Never stall the detector for a menu.
        pass


def decode_result(raw: bytes, now: float) -> dict | None:
    """Reject malformed/future packets; preserve vision's confidence unchanged."""
    try:
        p = json.loads(raw)
        if not isinstance(p, dict):
            return None
        stamp, confidence = p["ts"], p["region_confidence"]
        for value in (stamp, confidence):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return None
        if stamp < 0 or stamp > now or not 0 <= confidence <= 1:
            return None
        if p["state"] not in {"NO_OBJECT", "SEARCHING", "LOCKED", "LOST"} or type(p["stable"]) is not bool:
            return None
        if p["stable"] != (p["state"] == "LOCKED"):
            return None
        for field in ("object", "region"):
            if p[field] is not None and (not isinstance(p[field], str) or not p[field].strip()):
                return None
        if p["stable"] and p["object"] is None:
            return None
        return p
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        return None


class VisionProcess:
    """One launcher owns one child and a bounded, newest-result UDP receiver."""

    def __init__(self, script: Path):
        self.script = script.resolve()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)
        self.process: subprocess.Popen | None = None
        self.last_stamp = -1.0

    def start(self) -> None:
        env = os.environ.copy()
        env[PORT_ENV] = str(self.sock.getsockname()[1])
        # Retain the original working directory for .env and YOLO weights.
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(self.script)], cwd=self.script.parent, env=env,
        )

    def latest(self) -> dict | None:
        latest = None
        for _ in range(256):
            try:
                raw = self.sock.recv(8192)
            except BlockingIOError:
                break
            p = decode_result(raw, time.monotonic())
            if p is not None and p["ts"] > self.last_stamp:
                self.last_stamp = p["ts"]
                latest = p
        return latest

    @property
    def exited(self) -> bool:
        return self.process is not None and self.process.poll() is not None

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
            self.sock.close()