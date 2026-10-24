"""Object and region candidate selection shared by both vision entry points."""

if __package__:
    from .regions import get_targeted_region, region_rect
else:
    from regions import get_targeted_region, region_rect
import math

if __package__:
    from .regions import get_targeted_region, region_rect, UNKNOWN_REGION
else:
    from regions import get_targeted_region, region_rect, UNKNOWN_REGION

CIRCLE_AREA_FRAC = 0.5        # stage-1 circle covers ~half the frame area


TARGET_CLASSES = {
    "cup",
    "bottle",
    "cell phone",
    "remote",
    "toothbrush",
    "spoon",
    "book",
}

REGION_DISPLAY_CONF_THRESHOLD = 0.5


def circle_radius(frame_shape):
    h, w = frame_shape[:2]
    r = int(math.sqrt(CIRCLE_AREA_FRAC * w * h / math.pi))
    return min(r, min(w, h) // 2 - 2)          # never larger than the frame


def box_center_in_circle(box, center, radius):
    x1, y1, x2, y2 = box
    return math.hypot((x1 + x2) / 2 - center[0], (y1 + y2) / 2 - center[1]) <= radius


def select_object_candidate(boxes, names, frame_shape, center, radius):
    """stage 1: valid object whose box center is inside the circle; nearest to the center wins."""
    candidate = None
    best_dist = None

    for box in boxes:
        name = names[int(box.cls[0])]
        confidence = float(box.conf[0])

        if name not in TARGET_CLASSES or confidence <= REGION_DISPLAY_CONF_THRESHOLD:
            continue

        rectangle = clamp_box(tuple(map(int, box.xyxy[0])), frame_shape)
        x1, y1, x2, y2 = rectangle
        if x2 <= x1 or y2 <= y1:
            continue

        dist = math.hypot((x1 + x2) / 2 - center[0], (y1 + y2) / 2 - center[1])
        if dist > radius or (best_dist is not None and dist >= best_dist):
            continue

        best_dist = dist
        candidate = {
            "object": name,
            "region": UNKNOWN_REGION,
            "det_conf": confidence,
            "reticle_score": max(0.0, 1.0 - dist / radius),   # how central the object is
            "box": rectangle,
            "region_box": None,
        }

    return candidate

def clamp_box(box, frame_shape):
    """Keep a detection rectangle inside the camera frame."""
    height, width = frame_shape[:2]
    x1, y1, x2, y2 = box

    return (
        max(0, min(x1, width - 1)),
        max(0, min(y1, height - 1)),
        max(0, min(x2, width - 1)),
        max(0, min(y2, height - 1)),
    )


def reticle_overlaps_box(point, box):
    """Check whether the centre reticle lies inside a detection."""
    x1, y1, x2, y2 = box

    return (
        x1 <= point[0] <= x2
        and y1 <= point[1] <= y2
    )


def select_candidate(boxes, names, frame_shape, point,only_object=None):
    """Choose the smallest valid object under the reticle."""
    candidate = None
    best_area = None

    for box in boxes:
        name = names[int(box.cls[0])]
        confidence = float(box.conf[0])

        if (
            name not in TARGET_CLASSES
            or confidence <= REGION_DISPLAY_CONF_THRESHOLD
            or (only_object is not None and name != only_object)
        ):
            continue

        rectangle = clamp_box(
            tuple(map(int, box.xyxy[0])),
            frame_shape,
        )

        x1, y1, x2, y2 = rectangle

        if (
            x2 <= x1
            or y2 <= y1
            or not reticle_overlaps_box(point, rectangle)
        ):
            continue

        area = (x2 - x1) * (y2 - y1)

        if best_area is not None and area >= best_area:
            continue

        region, margin = get_targeted_region(
            name,
            rectangle,
            point,
        )

        if not region:
            continue

        best_area = area

        candidate = {
            "object": name,
            "region": region,
            "det_conf": confidence,
            "reticle_score": min(1.0, margin / 0.25),
            "box": rectangle,
            "region_box": region_rect(
                name,
                rectangle,
                region,
                point,
            ),
        }

    return candidate