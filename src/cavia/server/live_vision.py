"""Camera preview and inference inside the dashboard server."""

from collections import deque
import logging
from pathlib import Path
import threading
import time

from .frames import Frame


class LiveVision:
    def __init__(self, preview_fps=20, jpeg_quality=75):
        self.preview_fps = preview_fps
        self.jpeg_quality = jpeg_quality

        self._lock = threading.Lock()
        self._stop = threading.Event()

        # Each slot contains only the newest value.
        self._snapshot = None
        self._frame = None
        self._result = None

        self._recent = deque(maxlen=120)
        self._generation = 0
        self._threads = []

        self.paused = False
        self.error = None
        self._loaded = False

    def start(self):
        from cavia.vision.camera_source import (
            CameraSettings,
            CameraSource,
        )

        self.settings = CameraSettings.from_env()
        self.stream = CameraSource(self.settings).start()

        for target in (self._preview, self._detect):
            thread = threading.Thread(
                target=target,
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

        return self

    def set_paused(self, paused):
        """Invalidate old inference work whenever the detection cycle changes."""
        with self._lock:
            self.paused = paused
            self._generation += 1
            self._result = None

    def latest(self):
        """Return the newest detection once, without queuing old results."""
        with self._lock:
            result = self._result
            self._result = None

            return None if self.paused else result

    def latest_frame(self):
        """Return a JPEG only while its camera frame is still fresh."""
        with self._lock:
            frame = self._frame

        if frame is None:
            return None

        age = time.monotonic() - frame.captured_at

        if age > self.settings.max_frame_age:
            return None

        return frame

    @property
    def exited(self):
        return self.error is not None or self._stop.is_set()

    def status(self):
        now = time.monotonic()

        with self._lock:
            snapshot = self._snapshot
            fps = sum(now - stamp <= 1 for stamp in self._recent)
            paused = self.paused
            error = self.error
            loaded = self._loaded

        fresh = (
            snapshot is not None
            and snapshot["frame"] is not None
            and now - snapshot["received_at"]
            <= self.settings.max_frame_age
        )

        if error:
            vision_status = "down"
        elif paused:
            vision_status = "paused"
        elif loaded and fresh:
            vision_status = "ok"
        else:
            vision_status = "degraded"

        return {
            "camera": {
                "status": "live" if fresh else "down",
                "source": snapshot["source"] if snapshot else "XIAO",
                "fps": float(fps) if fresh else 0.0,
                # End-to-end latency is not measured here.
                "latency_ms": 0,
            },
            "vision": {
                "status": vision_status,
                "model": error or (
                    "yolo26n" if loaded else "Loading yolo26n"
                ),
            },
        }

    def _preview(self):
        """Read camera snapshots and encode preview JPEGs independently."""
        last_sequence = None
        preview_sequence = 0

        try:
            import cv2

            while not self._stop.is_set():
                started = time.monotonic()

                # Only this worker calls CameraSource.snapshot().
                snapshot = self.stream.snapshot()

                with self._lock:
                    self._snapshot = snapshot

                has_new_frame = (
                    snapshot["frame"] is not None
                    and snapshot["sequence"] != last_sequence
                )

                if has_new_frame:
                    last_sequence = snapshot["sequence"]

                    ok, jpeg = cv2.imencode(
                        ".jpg",
                        snapshot["frame"],
                        [
                            cv2.IMWRITE_JPEG_QUALITY,
                            self.jpeg_quality,
                        ],
                    )

                    if ok:
                        preview_sequence += 1
                        now = time.monotonic()

                        with self._lock:
                            self._frame = Frame(
                                jpeg.tobytes(),
                                preview_sequence,
                                snapshot["received_at"],
                                now,
                            )
                            self._recent.append(now)

                elapsed = time.monotonic() - started
                delay = max(0, 1 / self.preview_fps - elapsed)
                self._stop.wait(delay)

        except Exception as error:
            self.error = str(error)
            logging.exception("Camera preview worker failed")

    def _detect(self):
        """Run the existing detector and tracker on the latest raw frame."""
        try:
            from ultralytics import YOLO

            from cavia.vision.detection import select_candidate
            from cavia.vision.regions import normalize_rect
            from cavia.vision.vision_state import RegionTracker

            weights = (
                Path(__file__).resolve().parents[1]
                / "vision"
                / "yolo26n.pt"
            )

            model = YOLO(str(weights))
            tracker = RegionTracker()
            self._loaded = True

            previous_generation = None
            previous_session = None
            last_sequence = None
            result_sequence = 0

            while not self._stop.wait(0.01):
                with self._lock:
                    snapshot = self._snapshot
                    generation = self._generation
                    paused = self.paused

                if generation != previous_generation:
                    tracker.reset()
                    previous_generation = generation
                    previous_session = None
                    last_sequence = None

                if paused or snapshot is None:
                    continue

                fresh = (
                    snapshot["frame"] is not None
                    and time.monotonic() - snapshot["received_at"]
                    <= self.settings.max_frame_age
                )

                if not fresh:
                    tracker.reset()
                    last_sequence = None

                    self._publish(
                        {
                            **tracker.out,
                            "source": snapshot["source"],
                            "box": None,
                            "region_box": None,
                        },
                        generation,
                    )

                    self._stop.wait(0.1)
                    continue

                if snapshot["session"] != previous_session:
                    tracker.reset()
                    previous_session = snapshot["session"]
                    last_sequence = None

                if snapshot["sequence"] == last_sequence:
                    continue

                last_sequence = snapshot["sequence"]
                frame = snapshot["frame"]
                height, width = frame.shape[:2]
                reticle = (width // 2, height // 2)

                result = model(frame, verbose=False)[0]

                candidate = select_candidate(
                    result.boxes,
                    model.names,
                    frame.shape,
                    reticle,
                )

                # Confirmation or HOME may have happened while YOLO ran.
                with self._lock:
                    current = self._snapshot
                    valid = (
                        not self.paused
                        and generation == self._generation
                    )

                if not valid:
                    continue

                expired = (
                    current is None
                    or current["frame"] is None
                    or current["session"] != snapshot["session"]
                    or time.monotonic() - snapshot["received_at"]
                    > self.settings.max_frame_age
                )

                if expired:
                    tracker.reset()
                    continue

                output = tracker.update(candidate)

                object_box = None
                functional_region_box = None

                if candidate and candidate["object"] == output["object"]:
                    object_box = normalize_rect(
                        candidate["box"],
                        frame.shape,
                    )

                    if candidate["region"] == output["region"]:
                        functional_region_box = normalize_rect(
                            candidate["region_box"],
                            frame.shape,
                        )

                result_sequence += 1

                self._publish(
                    {
                        **output,
                        "source": snapshot["source"],
                        "frame_seq": result_sequence,
                        "box": object_box,
                        "region_box": functional_region_box,
                    },
                    generation,
                )

        except Exception as error:
            self.error = str(error)
            logging.exception("Vision inference worker failed")

    def _publish(self, result, generation):
        with self._lock:
            if not self.paused and generation == self._generation:
                self._result = {
                    **result,
                    "ts": time.monotonic(),
                    "generation": generation,
                }

    def close(self):
        self._stop.set()

        for thread in self._threads:
            thread.join(timeout=3)

        self.stream.close()


class PreviewFrames:
    """Expose the newest JPEG to the existing /video endpoint."""

    def __init__(self, vision):
        self.vision = vision

    def latest(self):
        return self.vision.latest_frame()