"""XIAO/laptop camera selection for CAVIA"""

from dataclasses import dataclass
import os
from pathlib import Path
import threading
import time

import cv2

# Support both package imports and the standalone vision script.
if __package__:
    from .mjpeg_stream import LatestMJPEGStream
else:
    from mjpeg_stream import LatestMJPEGStream


@dataclass
class CameraSettings:
    mode: str = "auto"
    ip: str = ""
    port: int = 81
    laptop_index: int = 0
    max_frame_age: float = 1.0
    return_delay: float = 2.0

    def __post_init__(self):
        self.mode = self.mode.strip().lower()
        self.ip = self.ip.strip()
        if self.mode not in {"auto", "xiao", "laptop"}:
            raise ValueError("CAMERA_MODE must be auto, xiao or laptop")
        if self.mode != "laptop" and not self.ip:
            raise ValueError("Set CAVIA_CAMERA_IP in .env")
        if any(c in self.ip for c in "/:\\"):
            raise ValueError("CAVIA_CAMERA_IP needs only an IP/hostname, without http:// or port")
        if not 1 <= self.port <= 65535 or self.laptop_index < 0:
            raise ValueError("Invalid camera port or laptop camera index")
        if not 0 < self.max_frame_age <= 10 or not 0 <= self.return_delay <= 30:
            raise ValueError("Invalid frame-age limit or XIAO return delay")

    @property
    def url(self):
        return f"http://{self.ip}:{self.port}/stream"

    @classmethod
    def from_env(cls, env_path=None):
        from dotenv import load_dotenv

        env_path = Path(env_path) if env_path else Path(__file__).with_name(".env")
        # .env overrides the earlier PowerShell IP value if it is still set.
        load_dotenv(env_path, override=True, encoding="utf-8-sig")
        return cls(
            mode=os.getenv("CAMERA_MODE", "auto"),
            ip=os.getenv("CAVIA_CAMERA_IP", ""),
            port=int(os.getenv("CAVIA_CAMERA_PORT", "81")),
            laptop_index=int(os.getenv("LAPTOP_CAMERA_INDEX", "0")),
            max_frame_age=float(os.getenv("CAMERA_MAX_FRAME_AGE", "1.0")),
            return_delay=float(os.getenv("XIAO_RETURN_DELAY", "2.0")),
        )


class LaptopCamera:
    """Keep USB camera opening/reading outside the GUI/inference thread."""

    def __init__(self, index):
        self.index = index
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._enabled = threading.Event()
        self._frame = None
        self._sequence = 0
        self._session = 0
        self._received_at = 0.0
        self._status = "Laptop camera paused"
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _invalidate(self, status):
        with self._lock:
            self._frame = None
            self._received_at = 0.0
            self._status = status

    def set_enabled(self, enabled):
        if enabled:
            self._enabled.set()
        else:
            self._enabled.clear()
            self._invalidate("Laptop camera paused")

    def snapshot(self):
        with self._lock:
            return {
                "frame": None if self._frame is None else self._frame.copy(),
                "sequence": self._sequence,
                "session": self._session,
                "received_at": self._received_at,
                "status": self._status,
            }

    def _run(self):
        cap = None
        try:
            while not self._stop.is_set():
                if not self._enabled.is_set():
                    if cap is not None:
                        cap.release()
                        cap = None
                    self._enabled.wait(0.1)
                    continue

                try:
                    if cap is None:
                        self._invalidate("Opening laptop camera")
                        cap = cv2.VideoCapture(self.index)
                        if not cap.isOpened():
                            cap.release()
                            cap = None
                            self._invalidate("Laptop camera unavailable - retrying")
                            self._stop.wait(1.0)
                            continue
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        with self._lock:
                            self._session += 1

                    ok, frame = cap.read()
                    if not ok:
                        cap.release()
                        cap = None
                        self._invalidate("Laptop frame failed - retrying")
                        self._stop.wait(0.5)
                        continue
                    if not self._enabled.is_set():
                        continue
                    with self._lock:
                        self._frame = frame
                        self._sequence += 1
                        self._received_at = time.monotonic()
                        self._status = "Live"
                except Exception as error:
                    if cap is not None:
                        cap.release()
                        cap = None
                    self._invalidate(f"Laptop camera error - retrying: {error}")
                    self._stop.wait(1.0)
        except Exception as error:
            self._invalidate(f"Laptop camera error: {error}")
        finally:
            if cap is not None:
                cap.release()

    def close(self):
        self._stop.set()
        self._enabled.set()
        self._thread.join(timeout=1.0)


class CameraSource:
    """auto prefers XIAO, falls back to laptop and returns after stable recovery.

    Manual laptop/xiao modes pin that camera. XIAO keeps retrying in the
    background so the user can switch back without opening its web page.
    """

    def __init__(self, settings):
        self.settings = settings
        self.mode = settings.mode
        self._xiao = LatestMJPEGStream(settings.url) if settings.ip else None
        self._laptop = LaptopCamera(settings.laptop_index)
        self._xiao_since = None
        self._last_xiao_session = None
        self._selected = None
        self._last_key = None
        self._session = 0

    def start(self):
        if self._xiao is not None:
            self._xiao.start()
        self._laptop.start()
        return self

    def set_mode(self, mode):
        if mode not in {"auto", "xiao", "laptop"}:
            raise ValueError("Unknown camera mode")
        if mode != "laptop" and self._xiao is None:
            print("[CAMERA] Set CAVIA_CAMERA_IP in .env and restart first.")
            return
        self.mode = mode
        print(f"[CAMERA] Mode: {mode}", flush=True)

    def _fresh(self, snapshot, now):
        return (snapshot["frame"] is not None
                and now - snapshot["received_at"] <= self.settings.max_frame_age)

    def snapshot(self):
        now = time.monotonic()
        xiao = self._xiao.snapshot() if self._xiao else {
            "frame": None, "sequence": 0, "session": 0,
            "received_at": 0.0, "status": "XIAO IP is not configured",
        }
        good = self._fresh(xiao, now)
        if good:
            if self._xiao_since is None or xiao["session"] != self._last_xiao_session:
                self._xiao_since = now
        else:
            self._xiao_since = None
        self._last_xiao_session = xiao["session"]

        if self.mode == "auto":
            recovered = good and now - self._xiao_since >= self.settings.return_delay
            selected = "xiao" if good and (self._selected == "xiao" or recovered) else "laptop"
        else:
            selected = self.mode

        self._laptop.set_enabled(selected == "laptop")
        data = xiao if selected == "xiao" else self._laptop.snapshot()
        key = (selected, data["session"])
        if key != self._last_key:
            self._session += 1
            self._last_key = key
        self._selected = selected

        output = dict(data)
        output["source"] = selected.upper()
        output["session"] = self._session
        output["sequence"] = (self._session, data["sequence"])
        if not self._fresh(data, now):
            output["frame"] = None
            if data["frame"] is not None:
                output["status"] = "Stale camera frame"
        return output

    def close(self):
        self._laptop.close()
        if self._xiao is not None:
            self._xiao.close()
