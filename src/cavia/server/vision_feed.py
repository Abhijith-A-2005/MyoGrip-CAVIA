"""Vision results to the dashboard: poll a source, convert, publish, and report camera status."""

from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from pathlib import Path
from typing import IO, Callable, Protocol

Publish = Callable[[str, dict], None]

STATES = {"NO_OBJECT", "SEARCHING", "LOCKED", "LOST"}
SOURCES = {"XIAO", "LAPTOP"}


class VisionSource(Protocol):
    """What the feed needs from a source: VisionProcess (live) and ReplayVision both fit."""

    def latest(self) -> dict | None: ...

    @property
    def exited(self) -> bool: ...


def _unit(value: object) -> float:
    """A finite number clamped to 0..1, anything else becomes 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0.0
    return min(1.0, max(0.0, float(value)))


def _box(value: object) -> list[float] | None:
    """[x1, y1, x2, y2] normalised and well ordered, or None."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        return None
    x1, y1, x2, y2 = (min(1.0, max(0.0, float(v))) for v in value)
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def to_dashboard(result: dict, frame_seq: int) -> dict | None:
    """Tracker result (docs/interfaces.md section 8) -> dashboard `vision` message (section 9)."""
    state = result.get("state")
    if state not in STATES:
        return None
    detected = state != "NO_OBJECT"
    source = result.get("source")
    message = {
        "ts": result.get("ts", 0.0),
        "frame_seq": result.get("frame_seq", frame_seq),
        "state": state,
        "object": result.get("object") if detected else None,
        "region": result.get("region") if detected else None,
        "region_confidence": _unit(result.get("region_confidence")),
        "det_conf": _unit(result.get("det_conf")),
        "reticle_score": _unit(result.get("reticle_score")),
        "stability": _unit(result.get("stability")),
        "stable": state == "LOCKED",
        "source": source if source in SOURCES else "XIAO",
        "box": _box(result.get("box")) if detected else None,
        "region_box": _box(result.get("region_box")) if detected else None,
    }
    # Older recordings omit targeting. Never infer a new stage from a committed lock.
    if "targeting" in result:
        message["targeting"] = _targeting(result["targeting"])
    return message


def _targeting(value: object) -> dict | None:
    if not isinstance(value, dict) or value.get("stage") not in {"object", "settling", "region"}:
        return None
    size, center = value.get("frame_size"), value.get("center")
    if not all(isinstance(v, (list, tuple)) and len(v) == 2 for v in (size, center)):
        return None
    numbers = [*size, *center, value.get("radius"), value.get("cross_half_size")]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in numbers):
        return None
    w, h = size
    x, y = center
    radius, cross = numbers[-2:]
    if not (w > 0 and h > 0 and 0 <= x <= w and 0 <= y <= h
            and 0 < radius <= min(w, h) / 2 and 0 < cross <= min(w, h) / 2):
        return None
    return {"stage": value["stage"], "frame_size": list(size), "center": list(center),
            "radius": radius, "cross_half_size": cross}


class VisionFeed:
    """Forwards results from `source` to the dashboard and keeps camera/vision health.

    Pass `on_result` to also hand each raw result to the arbitration runtime (integration step 4).
    """

    def __init__(self, source: VisionSource, publish: Publish, *, stale_after: float = 1.0,
                 record: IO[str] | None = None, on_result: Callable[[dict], None] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.source = source
        self._publish = publish
        self._stale_after = stale_after
        self._record = record
        self._on_result = on_result
        self._clock = clock
        self._lock = threading.Lock()
        self._arrivals: deque[float] = deque(maxlen=120)
        self._last_at: float | None = None
        self._last_source = "XIAO"
        self._count = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def poll(self) -> bool:
        """Drain the source once. Returns True if a result was published."""
        result = self.source.latest()
        if result is None:
            return False
        now = self._clock()
        with self._lock:
            self._count += 1
            message = to_dashboard(result, self._count)
            if message is None:
                return False
            self._arrivals.append(now)
            self._last_at = now
            self._last_source = message["source"]
        if self._record is not None:
            self._record.write(json.dumps({"t": now, **result}) + "\n")
        self._publish("vision", message)
        if self._on_result is not None:
            self._on_result(result)
        return True

    def status(self) -> dict:
        """`camera` and `vision` parts of the dashboard `system` message."""
        now = self._clock()
        with self._lock:
            recent = [t for t in self._arrivals if now - t <= 1.0]
            last_at, source = self._last_at, self._last_source
        if self.source.exited:
            camera, vision = "down", "down"
        elif last_at is None:
            camera, vision = "down", "degraded"   # running, no results yet (model loading)
        elif now - last_at > self._stale_after:
            camera, vision = "stale", "degraded"
        else:
            camera, vision = "live", "ok"
        return {
            "camera": {"status": camera, "source": source, "fps": float(len(recent)), "latency_ms": 0},
            "vision": {"status": vision, "model": "yolo26n"},
        }

    def start(self, hz: float = 60.0) -> None:
        def run() -> None:
            while not self._stop.wait(1.0 / hz):
                try:
                    self.poll()
                except Exception:  # noqa: BLE001  a bad packet must not end the feed
                    continue

        self._thread = threading.Thread(target=run, name="vision-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


class ReplayVision:
    """Plays back results recorded with `--record-vision`, at the original pace, looping."""

    def __init__(self, path: Path, *, loop: bool = True, clock: Callable[[], float] = time.monotonic):
        lines = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
        if not lines:
            raise ValueError(f"No recorded results in {path}")
        t0 = lines[0]["t"]
        self._frames = [(r.pop("t") - t0, r) for r in lines]
        self._duration = self._frames[-1][0] + 0.1
        self._loop = loop
        self._clock = clock
        self._start = clock()
        self._next = 0

    @property
    def exited(self) -> bool:
        return not self._loop and self._next >= len(self._frames)

    def latest(self) -> dict | None:
        """Newest frame that is due. Frames left in a cycle are delivered before it loops."""
        latest = None
        elapsed = self._clock() - self._start
        while True:
            while self._next < len(self._frames) and self._frames[self._next][0] <= elapsed:
                latest = self._frames[self._next][1]
                self._next += 1
            if not (self._loop and elapsed >= self._duration):
                break
            cycles = int(elapsed // self._duration)
            self._start += cycles * self._duration
            elapsed -= cycles * self._duration
            self._next = 0
        return None if latest is None else dict(latest, ts=self._clock())
