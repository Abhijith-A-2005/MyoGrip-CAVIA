from ultralytics import YOLO
import cv2
import json
from vision_state import RegionTracker, NO_OBJECT, SEARCHING, LOCKED, LOST
from regions import get_targeted_region

model = YOLO("yolo26n.pt")    # pretrained on COCO

# controlled object set, mapped to COCO class names
TARGET_CLASSES = {"cup", "bottle", "cell phone", "remote", "toothbrush", "spoon", "book"}
REGION_DISPLAY_CONF_THRESHOLD = 0.5

COLOR_TARGETED = (0, 255, 0)      # green
COLOR_NOT_TARGETED = (0, 165, 255)  # orange

cap = cv2.VideoCapture(0)  # webcam stand-in for the wrist camera


def clamp_box(box, frame_shape):
    """keep box coordinates inside the frame (fix 5)."""
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = box
    x1 = max(0, min(x1, w - 1))
    x2 = max(0, min(x2, w - 1))
    y1 = max(0, min(y1, h - 1))
    y2 = max(0, min(y2, h - 1))
    return x1, y1, x2, y2


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


def reticle_overlaps_box(reticle_point, box):
    cx, cy = reticle_point
    x1, y1, x2, y2 = box
    return x1 <= cx <= x2 and y1 <= cy <= y2

tracker = RegionTracker()
last_sent = None

def emit(out):
    """handoff to the ranking layer. prints on change only; swap for a socket/queue later."""
    global last_sent
    key = (out["state"], out["object"], out["region"], round(out["region_confidence"], 1))
    if key != last_sent:
        print(json.dumps(out))
        last_sent = key
STATE_COLORS = {NO_OBJECT: (128, 128, 128), SEARCHING: (0, 165, 255),
                LOCKED: (0, 255, 0), LOST: (0, 0, 255)}

fail = 0
while True:
    ret, frame = cap.read()
    if not ret:
        fail += 1
        print("frame read failed", fail)
        emit(tracker.update(None))        # a dead stream lets the lock expire
        if fail > 30:
            cap.release()
            cap = cv2.VideoCapture(0)     # later: the xiao stream
            fail = 0
        continue
    fail = 0

    # frame stays raw; all drawing goes on display_frame
    display_frame = frame.copy()
    reticle_point = draw_reticle(display_frame)

    results = model(frame, verbose=False)[0]

    candidate = None      # reset every frame
    best_area = None

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

        if targeted:
            area = (x2 - x1) * (y2 - y1)
            if best_area is None or area < best_area:
                region, margin = get_targeted_region(cls_name, (x1, y1, x2, y2), reticle_point)
                if region:
                    best_area = area
                    candidate = {
                        "object": cls_name,
                        "region": region,
                        "det_conf": conf,
                        "reticle_score": min(1.0, margin / 0.25),
                    }

    # once per frame, AFTER the box loop
    out = tracker.update(candidate)
    emit(out)

    color = STATE_COLORS[out["state"]]
    cv2.putText(display_frame, out["state"], (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    if out["object"]:
        cv2.putText(display_frame,
                    f"{out['object']} / {out['region']}  conf {out['region_confidence']:.2f}",
                    (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    cv2.imshow("CAVIA - Object Detection", display_frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()