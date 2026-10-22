import asyncio
import socket
import time

import pytest

from cavia.runtime import vision_link
from cavia.runtime.vision_link import FRAME_HEADER, FRAME_PORT_ENV, FrameSender
from cavia.server.__main__ import system_status
from cavia.server.frames import Frame, FrameReceiver

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 1000 + b"\xff\xd9"


def wait_for(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def receiver():
    r = FrameReceiver()
    yield r
    r.close()


def test_sender_delivers_newest_frame_with_latency(receiver):
    sender = FrameSender(receiver.port, min_interval=0)
    sender.offer(JPEG, time.monotonic() - 0.04)
    assert wait_for(lambda: receiver.latest() is not None)
    frame = receiver.latest()
    assert frame.jpeg == JPEG and frame.seq == 1
    fps, latency_ms = receiver.stats()
    assert fps == 1.0 and 30 <= latency_ms <= 1000


def test_rejects_non_jpeg_and_oversize_then_recovers(receiver):
    for bad in (FRAME_HEADER.pack(4, 0.0) + b"GIF8", FRAME_HEADER.pack(50_000_000, 0.0)):
        with socket.create_connection(("127.0.0.1", receiver.port)) as s:
            s.sendall(bad)
            time.sleep(0.1)
    assert receiver.latest() is None
    with socket.create_connection(("127.0.0.1", receiver.port)) as s:
        s.sendall(FRAME_HEADER.pack(len(JPEG), time.monotonic()) + JPEG)
        assert wait_for(lambda: receiver.latest() is not None)


def test_sender_rate_limit_and_size_guard():
    sender = FrameSender(1, min_interval=0.05)  # port 1: nothing listens, sends just fail and retry
    assert sender.wants_frame(time.monotonic())
    sender.offer(JPEG, 0.0)
    assert not sender.wants_frame(time.monotonic())
    assert sender.wants_frame(time.monotonic() + 0.06)
    sender.offer(b"", 0.0)                          # ignored: empty
    sender.offer(b"\xff\xd8" + b"x" * (3 * 1024 * 1024), 0.0)   # ignored: too large


def test_frame_sharing_is_off_unless_launched_by_server(monkeypatch):
    monkeypatch.delenv(FRAME_PORT_ENV, raising=False)
    monkeypatch.setattr(vision_link, "_frame_sender", None)
    assert vision_link.frame_wanted() is False
    vision_link.publish_frame(JPEG, 0.0)            # no-op, must not raise


def test_frame_sharing_on_when_port_given(monkeypatch, receiver):
    monkeypatch.setenv(FRAME_PORT_ENV, str(receiver.port))
    monkeypatch.setattr(vision_link, "_frame_sender", None)
    assert vision_link.frame_wanted() is True
    vision_link.publish_frame(JPEG, time.monotonic())
    assert wait_for(lambda: receiver.latest() is not None)


class StaticFrames:
    def __init__(self, frame):
        self.frame = frame

    def latest(self):
        return self.frame


def test_mjpeg_sends_each_frame_once_and_ends_when_idle():
    from cavia.server.app import mjpeg

    async def collect():
        return [part async for part in mjpeg(StaticFrames(Frame(JPEG, 1, 0.0, 0.0)), idle_s=0.1)]

    parts = asyncio.run(collect())
    assert len(parts) == 1
    assert parts[0].startswith(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 1006\r\n\r\n")
    assert parts[0].endswith(JPEG + b"\r\n")


def test_video_endpoint(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from cavia.server import app as app_module
    from cavia.server.hub import Hub

    assert TestClient(app_module.create_app(Hub())).get("/video").status_code == 503
    empty = StaticFrames(None)
    assert TestClient(app_module.create_app(Hub(), frames=empty)).get("/video").status_code == 503

    monkeypatch.setattr(app_module, "STREAM_IDLE_S", 0.1)
    app = app_module.create_app(Hub(), frames=StaticFrames(Frame(JPEG, 7, 0.0, 0.0)))
    r = TestClient(app).get("/video")
    assert r.status_code == 200
    assert r.headers["content-type"] == "multipart/x-mixed-replace; boundary=frame"
    assert JPEG in r.content


def test_system_status_prefers_real_frame_stats():
    class Feed:
        def status(self):
            return {"camera": {"status": "live", "source": "LAPTOP", "fps": 9.0, "latency_ms": 0},
                    "vision": {"status": "ok", "model": "yolo26n"}}

    class Frames:
        def stats(self):
            return 24.0, 38

    s = system_status(Feed(), Frames())
    assert s["camera"] == {"status": "live", "source": "LAPTOP", "fps": 24.0, "latency_ms": 38}
    assert system_status(Feed(), None)["camera"]["fps"] == 9.0
