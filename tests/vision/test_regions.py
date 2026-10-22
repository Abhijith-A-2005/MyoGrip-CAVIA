import sys
from pathlib import Path

import pytest

# The vision scripts import each other as top-level modules (they run from their own folder).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/cavia/vision"))

from regions import FUNCTIONAL_REGIONS, get_targeted_region, normalize_rect, region_rect  # noqa: E402
from vision_state import LOCKED, LOST, RegionTracker  # noqa: E402

BOX = (100, 50, 300, 450)  # 200 x 400 px


def inside(point, rect):
    x, y = point
    x1, y1, x2, y2 = rect
    return x1 - 1e-6 <= x <= x2 + 1e-6 and y1 - 1e-6 <= y <= y2 + 1e-6


@pytest.mark.parametrize("class_name", sorted(FUNCTIONAL_REGIONS))
def test_reticle_lies_inside_the_rect_of_the_region_it_was_assigned(class_name):
    # Sweep the reticle across the box: whatever region the rules choose must contain the reticle.
    for fx in [0.05, 0.2, 0.4, 0.5, 0.6, 0.8, 0.95]:
        for fy in [0.05, 0.2, 0.5, 0.65, 0.8, 0.95]:
            point = (BOX[0] + fx * 200, BOX[1] + fy * 400)
            region, _ = get_targeted_region(class_name, BOX, point)
            rect = region_rect(class_name, BOX, region, point)
            assert inside(point, rect), (class_name, region, point, rect)
            assert inside((rect[0], rect[1]), BOX) and inside((rect[2], rect[3]), BOX)


def test_handle_strip_follows_the_reticle_side():
    right = region_rect("cup", BOX, "handle", (290, 250))
    left = region_rect("cup", BOX, "handle", (110, 250))
    assert right == (250.0, 50, 300, 450)
    assert left == (100, 50, 150.0, 450)


def test_normalize_rect_clamps_to_frame():
    assert normalize_rect((-10, 0, 320, 240), (480, 640, 3)) == [0.0, 0.0, 0.5, 0.5]
    assert normalize_rect((600, 400, 700, 500), (480, 640, 3)) == [0.9375, 0.8333, 1.0, 1.0]


def test_tracker_reports_evidence_and_keeps_it_while_lost():
    t = RegionTracker()
    cand = {"object": "cup", "region": "handle", "det_conf": 0.9, "reticle_score": 0.6}
    for _ in range(6):
        out = t.update(cand)
    assert out["state"] == LOCKED
    assert (out["det_conf"], out["reticle_score"], out["stability"]) == (0.9, 0.6, 1.0)
    lost = t.update(None)
    assert lost["state"] == LOST
    assert (lost["det_conf"], lost["reticle_score"], lost["stability"]) == (0.9, 0.6, 1.0)
    t.reset()
    assert (t.out["det_conf"], t.out["reticle_score"], t.out["stability"]) == (0.0, 0.0, 0.0)
