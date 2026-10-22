import io
import json
from pathlib import Path

import pytest

from cavia.server.vision_feed import ReplayVision, VisionFeed, to_dashboard

SAMPLE = Path(__file__).resolve().parents[2] / "data/vision/samples/synthetic-cup-handle.jsonl"

LOCKED = {
    "ts": 12.5, "state": "LOCKED", "object": "cup", "region": "handle", "region_confidence": 0.87,
    "stable": True, "det_conf": 0.91, "reticle_score": 0.64, "stability": 0.9, "source": "LAPTOP",
    "frame_seq": 40, "box": [0.15, 0.2, 0.55, 0.84], "region_box": [0.45, 0.2, 0.55, 0.84],
    "generation": 0,
}


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class FakeSource:
    def __init__(self, results=()):
        self.queue = list(results)
        self.exited = False

    def latest(self):
        return self.queue.pop(0) if self.queue else None


def test_converts_tracker_result_to_dashboard_message():
    msg = to_dashboard(LOCKED, frame_seq=1)
    assert msg == {
        "ts": 12.5, "frame_seq": 40, "state": "LOCKED", "object": "cup", "region": "handle",
        "region_confidence": 0.87, "det_conf": 0.91, "reticle_score": 0.64, "stability": 0.9,
        "stable": True, "source": "LAPTOP", "box": [0.15, 0.2, 0.55, 0.84],
        "region_box": [0.45, 0.2, 0.55, 0.84],
    }


def test_old_style_result_without_overlay_fields_still_works():
    old = {k: LOCKED[k] for k in ("ts", "state", "object", "region", "region_confidence", "stable")}
    msg = to_dashboard(old, frame_seq=7)
    assert msg["frame_seq"] == 7 and msg["box"] is None and msg["source"] == "XIAO"
    assert (msg["det_conf"], msg["reticle_score"], msg["stability"]) == (0.0, 0.0, 0.0)


@pytest.mark.parametrize("box", [[0.5, 0.2, 0.4, 0.8], [0.1, 0.2, 0.3], "box", [0.1, float("nan"), 0.3, 0.4],
                                 [0.1, True, 0.3, 0.4]])
def test_rejects_malformed_boxes(box):
    assert to_dashboard({**LOCKED, "box": box}, 1)["box"] is None


def test_clamps_values_and_drops_object_when_nothing_detected():
    msg = to_dashboard({**LOCKED, "region_confidence": 3, "det_conf": float("inf"), "box": [-1, 0, 2, 1]}, 1)
    assert msg["region_confidence"] == 1.0 and msg["det_conf"] == 0.0 and msg["box"] == [0.0, 0.0, 1.0, 1.0]
    empty = to_dashboard({**LOCKED, "state": "NO_OBJECT", "stable": False}, 1)
    assert empty["object"] is None and empty["box"] is None and empty["stable"] is False
    assert to_dashboard({**LOCKED, "state": "WEIRD"}, 1) is None


def test_feed_publishes_records_and_forwards():
    published, forwarded, record = [], [], io.StringIO()
    clock = Clock()
    feed = VisionFeed(FakeSource([LOCKED]), lambda k, d: published.append((k, d)), record=record,
                      on_result=forwarded.append, clock=clock)
    assert feed.poll() is True
    assert feed.poll() is False
    assert published[0][0] == "vision" and published[0][1]["region"] == "handle"
    assert forwarded == [LOCKED]
    line = json.loads(record.getvalue())
    assert line["t"] == 100.0 and line["state"] == "LOCKED"


def test_status_tracks_camera_health():
    clock = Clock()
    source = FakeSource()
    feed = VisionFeed(source, lambda k, d: None, clock=clock)
    assert feed.status()["camera"]["status"] == "down"          # running, nothing yet
    assert feed.status()["vision"]["status"] == "degraded"
    for i in range(15):
        source.queue.append({**LOCKED, "ts": i})
        clock.t += 1 / 15
        feed.poll()
    s = feed.status()
    assert s["camera"] == {"status": "live", "source": "LAPTOP", "fps": 15.0, "latency_ms": 0}
    assert s["vision"]["status"] == "ok"
    clock.t += 1.5
    assert feed.status()["camera"]["status"] == "stale"
    source.exited = True
    assert feed.status()["camera"]["status"] == "down"


def test_replay_keeps_pace_and_loops(tmp_path):
    path = tmp_path / "rec.jsonl"
    path.write_text("\n".join(json.dumps({"t": 50 + t, "state": "SEARCHING", "n": t}) for t in (0, 1, 2)))
    clock = Clock()
    replay = ReplayVision(path, clock=clock)
    assert replay.latest()["n"] == 0
    assert replay.latest() is None                  # nothing new until time passes
    clock.t += 1.5
    assert replay.latest()["n"] == 1
    clock.t += 0.55                                  # 2.05 s: last frame of a 2.1 s cycle
    r = replay.latest()
    assert r["n"] == 2 and r["ts"] == clock.t      # stamped with the replay clock
    clock.t += 0.2                                   # past the end: loops back to the start
    assert replay.latest()["n"] == 0
    clock.t += 2.1 * 3 + 1.0                         # several cycles later: still in step
    assert replay.latest()["n"] == 1
    assert replay.exited is False


def test_replay_once_reports_exit(tmp_path):
    path = tmp_path / "rec.jsonl"
    path.write_text(json.dumps({"t": 0, "state": "NO_OBJECT"}))
    replay = ReplayVision(path, loop=False, clock=Clock())
    assert replay.latest() is not None and replay.exited is True


def test_recording_replays_identically(tmp_path):
    record_path = tmp_path / "rec.jsonl"
    clock = Clock()
    with record_path.open("w") as record:
        feed = VisionFeed(FakeSource([LOCKED, {**LOCKED, "region": "body"}]), lambda k, d: None,
                          record=record, clock=clock)
        feed.poll()
        clock.t += 0.5
        feed.poll()
    replay = ReplayVision(record_path, clock=clock)
    assert replay.latest()["region"] == "handle"
    clock.t += 0.5
    assert replay.latest()["region"] == "body"


def test_sample_recording_is_valid():
    lines = [json.loads(line) for line in SAMPLE.read_text().splitlines()]
    states = {r["state"] for r in lines}
    assert {"NO_OBJECT", "SEARCHING", "LOCKED", "LOST"} <= states
    assert all(to_dashboard(r, 1) is not None for r in lines)
    assert [r["t"] for r in lines] == sorted(r["t"] for r in lines)
