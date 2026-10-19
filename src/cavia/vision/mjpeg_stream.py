import re
import threading
import time
from urllib.request import ProxyHandler, Request, build_opener

import cv2
import numpy as np


class JPEGBuffer:
    """Extract JPEG images from CameraWebServer's multipart stream."""

    MAX_BYTES = 2 * 1024 * 1024

    def __init__(self):
        self.buffer = bytearray()
        self.pending_length = None

    def feed(self, chunk):
        self.buffer.extend(chunk)
        images = []

        while True:
            if self.pending_length is None:
                end = self.buffer.find(b"\r\n\r\n")
                if end < 0:
                    break

                header = bytes(self.buffer[:end])
                match = re.search(
                    rb"Content-Length:\s*(\d+)", header, re.I
                )

                if match is None:
                    raise ValueError("Stream part has no Content-Length")

                self.pending_length = int(match.group(1))

                if not 0 < self.pending_length <= self.MAX_BYTES:
                    raise ValueError("Invalid JPEG size")

                del self.buffer[:end + 4]

            if len(self.buffer) < self.pending_length:
                break

            images.append(bytes(self.buffer[:self.pending_length]))
            del self.buffer[:self.pending_length]
            self.pending_length = None

        if len(self.buffer) > self.MAX_BYTES:
            raise ValueError("Receive buffer limit exceeded")

        return images


class LatestMJPEGStream:
    """Receive continuously and retain the newest decoded frame."""

    def __init__(self, url, timeout=3.0, retry_delay=1.0):
        self.url = url
        self.timeout = timeout
        self.retry_delay = retry_delay

        self._lock = threading.Lock()
        self._stop = threading.Event()

        self._frame = None
        self._sequence = 0
        self._session = 0
        self._received_at = 0.0
        self._status = "Connecting"

        self._thread = threading.Thread(
            target=self._run, daemon=True
        )

    def start(self):
        self._thread.start()
        return self

    def snapshot(self):
        # A separate copy prevents drawing from modifying stored pixels.
        with self._lock:
            return {
                "frame": (
                    None if self._frame is None
                    else self._frame.copy()
                ),
                "sequence": self._sequence,
                "session": self._session,
                "received_at": self._received_at,
                "status": self._status,
            }

    def _invalidate(self, status):
        with self._lock:
            self._frame = None
            self._received_at = 0.0
            self._status = status

    def _run(self):
        # Contact the local camera directly, bypassing system proxies.
        opener = build_opener(ProxyHandler({}))

        while not self._stop.is_set():
            try:
                request = Request(
                    self.url,
                    headers={"User-Agent": "CAVIA/1.0"},
                )

                with opener.open(
                    request, timeout=self.timeout
                ) as response:
                    content_type = response.headers.get(
                        "Content-Type", ""
                    ).lower()

                    if "multipart/x-mixed-replace" not in content_type:
                        raise ValueError(
                            "Use the MJPEG /stream URL, not the web page"
                        )

                    with self._lock:
                        self._session += 1

                    parser = JPEGBuffer()
                    last_good = time.monotonic()

                    while not self._stop.is_set():
                        # Return available bytes without filling the buffer first.
                        chunk = response.read1(64 * 1024)

                        if not chunk:
                            raise ConnectionError("Camera closed the stream")

                        for jpeg in parser.feed(chunk):
                            frame = cv2.imdecode(
                                np.frombuffer(jpeg, dtype=np.uint8),
                                cv2.IMREAD_COLOR,
                            )

                            if frame is None:
                                continue

                            last_good = time.monotonic()

                            with self._lock:
                                self._frame = frame
                                self._sequence += 1
                                self._received_at = last_good
                                self._status = "Live"

                        if time.monotonic() - last_good > self.timeout:
                            raise ConnectionError(
                                "No decodable frames received"
                            )

            except Exception as error:
                self._invalidate("Disconnected - reconnecting")

                if not self._stop.is_set():
                    print(f"[CAMERA] {error}; retrying...", flush=True)
                    self._stop.wait(self.retry_delay)

        self._invalidate("Stopped")

    def close(self):
        self._stop.set()
        self._thread.join(timeout=self.timeout + 1.0)