"""Exercise the real dashboard adapter with model-style detections, without camera hardware."""

from types import SimpleNamespace
import sys

import pytest

from cavia.server.live_vision import LiveVision, TwoStagePipeline
from cavia.server.vision_feed import to_dashboard
from cavia.vision.detection import circle_radius

SHAPE = (480, 640, 3)
NAMES = {0: "cup", 1: "bottle"}


def box(rect=(200, 100, 440, 400), cls=0):
    return SimpleNamespace(cls=[cls], conf=[0.95], xyxy=[rect])


def lock_object(pipeline):
    for i in range(5):
        out = pipeline.process([box()], NAMES, SHAPE, i * 0.1)
    return out


def test_dashboard_object_settle_region_switch_and_reset():
    p = TwoStagePipeline()
    searching = p.process([box()], NAMES, SHAPE, -0.1)
    assert searching["targeting"]["stage"] == "object"
    locked = lock_object(p)
    assert (locked["object"], locked["region"], locked["state"]) == ("cup", "unknown", "LOCKED")
    assert locked["region_box"] is None
    assert locked["targeting"] == {
        "stage": "settling", "frame_size": [640, 480], "center": [320, 240],
        "radius": circle_radius(SHAPE), "cross_half_size": 20,
    }
    assert p.process([box()], NAMES, SHAPE, 1)["region"] == "unknown"
    # Reticle is near the right edge of this cup: handle region.
    for i in range(8):
        handle = p.process([box((100, 80, 340, 400))], NAMES, SHAPE, 3 + i * .1)
    assert handle["region"] == "handle" and handle["targeting"]["stage"] == "region"
    assert handle["region_box"] is not None
    for i in range(10):
        body = p.process([box()], NAMES, SHAPE, 5 + i * .1)
    assert body["region"] == "body"
    lost = p.process([], NAMES, SHAPE, 7)
    assert lost["region"] == "body" and lost["box"] is None
    # Another class cannot steal the object selection during stage 2.
    for i in range(10):
        other = p.process([box(cls=1)], NAMES, SHAPE, 8 + i * .1)
    assert other["object"] == "cup" and other["region"] == "body"
    p.reset()
    fresh = p.process([], NAMES, SHAPE, 10)
    assert fresh["targeting"]["stage"] == "object" and fresh["object"] is None


@pytest.mark.parametrize("shape", [(240, 320, 3), SHAPE, (720, 1280, 3)])
def test_geometry_and_message_transport(shape):
    out = TwoStagePipeline().process([], NAMES, shape, 0)
    h, w = shape[:2]
    assert out["targeting"]["center"] == [w // 2, h // 2]
    assert out["targeting"]["radius"] == circle_radius(shape)
    assert to_dashboard(out, 1)["targeting"] == out["targeting"]


@pytest.mark.parametrize("bad", [None, {}, {"stage": "invalid"},
    {"stage": "object", "frame_size": [640, 480], "center": [320, 240],
     "radius": float("nan"), "cross_half_size": 20}])
def test_invalid_geometry_is_not_forwarded(bad):
    assert to_dashboard({"state": "NO_OBJECT", "targeting": bad}, 1)["targeting"] is None


@pytest.mark.parametrize("change", ["pause", "home", "camera", "stale"])
def test_worker_rejects_inference_when_context_changes(monkeypatch, change):
    vision = LiveVision()
    now = [100.0]
    monkeypatch.setattr("cavia.server.live_vision.time.monotonic", lambda: now[0])
    vision.settings = SimpleNamespace(max_frame_age=1)
    vision._snapshot = dict(frame=SimpleNamespace(shape=SHAPE), received_at=100.0,
                            sequence=1, session=1, source="XIAO")

    class Model:
        names = NAMES

        def __init__(self, weights):
            pass

        def __call__(self, frame, verbose=False):
            if change == "pause":
                vision.set_paused(True)
            elif change == "home":
                vision.set_paused(False)
            elif change == "camera":
                vision._snapshot = {**vision._snapshot, "session": 2}
            else:
                now[0] += 2
            vision._stop.set()
            return [SimpleNamespace(boxes=[box()])]

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=Model))
    vision._detect()
    assert vision.error is None and vision.latest() is None


def test_paused_worker_does_not_run_inference(monkeypatch):
    vision = LiveVision()
    vision.paused = True
    calls = []

    class Model:
        def __init__(self, weights):
            pass

        def __call__(self, *args, **kwargs):
            calls.append(True)

    class Stop:
        def __init__(self):
            self.polls = 0

        def wait(self, delay):
            self.polls += 1
            return self.polls > 3

    vision._stop = Stop()
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=Model))
    vision._detect()
    assert vision.error is None and calls == []
