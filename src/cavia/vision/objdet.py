from ultralytics import YOLO
import cv2
import json
import time
import numpy as np
from camera_source import CameraSettings, CameraSource
from vision_state import RegionTracker, NO_OBJECT, SEARCHING, LOCKED, LOST
from regions import normalize_rect
from detection import (
    TARGET_CLASSES,
    REGION_DISPLAY_CONF_THRESHOLD,
    clamp_box,
    reticle_overlaps_box,
    select_candidate,
)
from cavia.runtime.vision_link import DetectionControl, frame_wanted, publish_frame, publish_result

# Camera window title
WINDOW = "CAVIA - Object Detection"

def vision_window_size():
    """Return half the primary screen dimensions on Windows."""
    import sys

    if sys.platform == "win32":
        import ctypes

        user32 = ctypes.windll.user32
        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)

        if screen_width > 0 and screen_height > 0:
            return screen_width // 2, screen_height // 2

    # Default for other operating systems.
    return 960, 540

# Display colour for each tracking state (OpenCV uses BGR)
STATE_COLORS = {
    NO_OBJECT: (128, 128, 128),
    SEARCHING: (0, 165, 255),
    LOCKED: (0, 255, 0),
    LOST: (0, 0, 255),
}

model = YOLO("yolo26n.pt")    # pretrained on COCO

COLOR_TARGETED = (0, 255, 0)      # green
COLOR_NOT_TARGETED = (0, 165, 255)  # orange

# .env lives beside camera_source.py; mode changes via L / X / A are runtime-only.
camera_settings = CameraSettings.from_env()
MAX_FRAME_AGE = camera_settings.max_frame_age


def normalize_angle(rect):
    """long-axis angle in [0, 180), independent of opencv's minAreaRect convention (fix 6)."""
    (_, _), (w, h), angle = rect
    if w < h:
        angle += 90
    return angle % 180


def get_contour_and_orientation(frame, box):
    """frame must be the RAW frame (nothing drawn on it) (fix 2)."""
    x1, y1, x2, y2 = box
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None, None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    # close small gaps so the contour is one solid outline
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, None

    largest = max(contours, key=cv2.contourArea)
    rect = cv2.minAreaRect(largest)  # (center, (w, h), angle)
    return largest, normalize_angle(rect)


def draw_reticle(frame):
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    size = 20
    color = (0, 0, 255)

    cv2.line(frame, (cx - size, cy), (cx + size, cy), color, 2)
    cv2.line(frame, (cx, cy - size), (cx, cy + size), color, 2)
    return cx, cy

tracker = RegionTracker()
last_sent = None

def overlay(out, candidate, frame_shape):
    """Dashboard overlay for this frame: boxes only when they belong to the reported object/region."""
    box = region_box = None
    if candidate is not None and candidate["object"] == out["object"]:
        box = normalize_rect(candidate["box"], frame_shape)
        if candidate["region"] == out["region"]:
            region_box = normalize_rect(candidate["region_box"], frame_shape)
    return {"box": box, "region_box": region_box}


def emit(out, generation=0, extras=None):
    """Forward every tracker output; keep console printing on changes only.

    `extras` (camera source, frame counter, overlay boxes) travel with the result for the
    dashboard; the arbitration runtime ignores them.
    """
    global last_sent

    # Unchanged locks must still be forwarded as heartbeats.
    publish_result({**out, **(extras or {})}, generation=generation)

    key = (
        out["state"],
        out["object"],
        out["region"],
        round(out["region_confidence"], 1),
    )

    if key != last_sent:
        print(json.dumps(out))
        last_sent = key


last_shared = None


def share_frame(snapshot):
    """Send the raw camera frame (no drawings) to the dashboard server, when it launched us."""
    global last_shared

    frame = snapshot["frame"]
    if frame is None or snapshot["sequence"] == last_shared or not frame_wanted():
        return
    ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if ok:
        last_shared = snapshot["sequence"]
        publish_frame(jpeg.tobytes(), snapshot["received_at"])


def quit_requested():
    key = cv2.waitKey(10) & 0xFF
    if ord("A") <= key <= ord("Z"):
        key += ord("a") - ord("A")
    modes = {ord("l"): "laptop", ord("x"): "xiao", ord("a"): "auto"}
    if key in modes:
        stream.set_mode(modes[key])
    return (key in (ord("q"), 27)
            or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1)


def camera_status_frame(message):
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(image, message, (15, 40), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (0, 0, 255), 2)
    cv2.putText(image, "L: laptop | X: XIAO | A: auto | Q / Esc: quit",
                (15, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (255, 255, 255), 1)
    return image


stream = CameraSource(camera_settings).start()
detection_control = DetectionControl()

last_control_generation = -1
frame_seq = 0
last_sequence = -1
last_session = None

try:
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

    # Set the initial display size once; manual resizing remains available.
    window_width, window_height = vision_window_size()
    cv2.resizeWindow(WINDOW, window_width, window_height)

    while True:
        paused, generation = detection_control.snapshot()

        if generation != last_control_generation:
            # HOME must not reuse a lock from the previous detection cycle.
            tracker.reset()
            last_sent = None
            last_sequence = -1
            last_session = None
            last_control_generation = generation

        snapshot = stream.snapshot()
        frame = snapshot["frame"]
        stale = time.monotonic() - snapshot["received_at"] > MAX_FRAME_AGE
        if not stale:
            # Before the pause check: the dashboard shows the camera during a grip too.
            share_frame(snapshot)

        if paused:
            # Keep preview responsive while skipping inference and region work.
            display_frame = (
                frame.copy()
                if frame is not None and not stale
                else camera_status_frame(
                    "Camera unavailable; detection paused"
                )
            )

            cv2.putText(
                display_frame,
                "DETECTION PAUSED - return to HOME to resume",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 220, 255),
                2,
            )

            cv2.imshow(WINDOW, display_frame)

            if quit_requested():
                break

            continue

        if frame is None or stale:
            # A camera outage must not carry a previous lock into recovery.
            tracker.reset()
            emit(tracker.out, generation, {"source": snapshot["source"]})
            message = f"{snapshot['source']} / {stream.mode}: {snapshot['status']}"
            cv2.imshow(WINDOW, camera_status_frame(message))
            if quit_requested():
                break
            continue

        # Never carry a lock/history from one camera (or camera session) to another.
        if snapshot["session"] != last_session:
            tracker.reset()
            emit(tracker.out, generation, {"source": snapshot["source"]})
            last_session = snapshot["session"]
            last_sequence = -1
            print(f"[CAMERA] Active: {snapshot['source']}", flush=True)

        # Avoid counting the same received frame as several observations.
        if snapshot["sequence"] == last_sequence:
            if quit_requested():
                break
            continue
        last_sequence = snapshot["sequence"]
        frame_seq += 1

        # frame stays raw; all drawing goes on display_frame
        display_frame = frame.copy()
        reticle_point = draw_reticle(display_frame)

        if detection_control.snapshot() != (False, generation):
            continue

        results = model(frame, verbose=False)[0]

        # Discard work if PAUSE or HOME arrived during inference.
        if detection_control.snapshot() != (False, generation):
            continue

        candidate = select_candidate(
            results.boxes,
            model.names,
            frame.shape,
            reticle_point,
        )

        for box in results.boxes:
            cls_name = model.names[int(box.cls[0])]
            conf = float(box.conf[0])

            if cls_name not in TARGET_CLASSES or conf <= REGION_DISPLAY_CONF_THRESHOLD:
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            x1, y1, x2, y2 = clamp_box((x1, y1, x2, y2), frame.shape)
            if x2 <= x1 or y2 <= y1:
                continue

            targeted = reticle_overlaps_box(reticle_point, (x1, y1, x2, y2))
            box_color = COLOR_TARGETED if targeted else COLOR_NOT_TARGETED

            cv2.rectangle(display_frame, (x1, y1), (x2, y2), box_color, 2)
            cv2.putText(display_frame, f"{cls_name} {conf:.2f}", (x1, max(y1 - 8, 15)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2)

            contour, orientation = get_contour_and_orientation(frame, (x1, y1, x2, y2))
            if contour is not None and orientation is not None:
                cv2.drawContours(display_frame, [contour + [x1, y1]], -1, (255, 0, 0), 1)
                cv2.putText(display_frame, f"{orientation:.0f} deg", (x1, max(y1 - 30, 30)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)


        # Suppress a result if this frame expired or the camera reconnected
        # while YOLO was running. This does not change region/lock algorithms.
        current = stream.snapshot()
        if (current["frame"] is None
                or current["session"] != snapshot["session"]
                or time.monotonic() - snapshot["received_at"] > MAX_FRAME_AGE):
            tracker.reset()
            emit(tracker.out, generation, {"source": snapshot["source"]})
            display_frame = camera_status_frame("STALE / DISCONNECTED")
            cv2.imshow(WINDOW, display_frame)
            if quit_requested():
                break
            continue

        # once per fresh camera frame, AFTER the box loop
        if detection_control.snapshot() != (False, generation):
            continue

        out = tracker.update(candidate)
        emit(out, generation, {
            "source": snapshot["source"],
            "frame_seq": frame_seq,
            **overlay(out, candidate, frame.shape),
        })

        color = STATE_COLORS[out["state"]]
        cv2.putText(display_frame, out["state"], (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        if out["object"]:
            cv2.putText(display_frame,
                        f"{out['object']} / {out['region']}  conf {out['region_confidence']:.2f}",
                        (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)


        cv2.putText(display_frame,
                    f"{snapshot['source']} | {stream.mode.upper()} | L laptop / X XIAO / A auto",
                    (10, display_frame.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        cv2.imshow(WINDOW, display_frame)
        if quit_requested():
            break
except KeyboardInterrupt:
    pass
finally:
    stream.close()
    cv2.destroyAllWindows()
