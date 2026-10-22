# regions.py

FUNCTIONAL_REGIONS = {
    "cup":        ["body", "handle"],     
    "bottle":     ["body", "cap"],                
    "toothbrush":     ["shank", "handle"],    
    "spoon":      ["handle"],                     
    "cell phone": ["side_edge", "lower_support"], 
    "remote":    ["side_edge", "lower_support"], 
    "book":      ["side_edge", "cover_face"],       
}

def get_candidate_regions(class_name):
   
    return FUNCTIONAL_REGIONS.get(class_name, [])

# --- per-class zone rules ---
# nx, ny: reticle position relative to box center, normalized to roughly -1..1,
# in plain frame coordinates (no rotation compensation).
# ny negative = toward top of box, positive = toward bottom.

def _cup_zone(nx, ny, regions):
    region = "handle" if abs(nx) > 0.5 else "body"
    return region, abs(abs(nx) - 0.5)

def _bottle_zone(nx, ny, regions):
    region = "cap" if ny < -0.5 else "body"
    return region, abs(ny + 0.5)

def _toothbrush_zone(nx, ny, regions):
    region = "shank" if abs(nx) > 0.5 else "handle"
    return region, abs(abs(nx) - 0.5)

def _edge_support_zone(nx, ny, regions):
    margin = min(abs(abs(nx) - 0.5), abs(ny - 0.4))
    if abs(nx) > 0.5:
        return "side_edge", margin
    if ny > 0.4:
        return "lower_support", margin
    return regions[0], margin

def _book_zone(nx, ny, regions):
    region = "side_edge" if abs(nx) > 0.5 else "cover_face"
    return region, abs(abs(nx) - 0.5)

ZONE_RULES = {
    "cup":        _cup_zone,
    "bottle":     _bottle_zone,
    "toothbrush": _toothbrush_zone,
    "book":       _book_zone,
    "cell phone": _edge_support_zone,
    "remote":     _edge_support_zone,
}   # spoon removed: single region, returns early

def get_targeted_region(class_name, box, reticle_point):
    """returns (region, margin). margin = distance from nearest zone boundary."""
    regions = get_candidate_regions(class_name)
    if not regions:
        return None, 0.0
    if len(regions) == 1:
        return regions[0], 1.0      # nothing ambiguous

    x1, y1, x2, y2 = box
    box_w, box_h = x2 - x1, y2 - y1
    cx, cy = x1 + box_w / 2, y1 + box_h / 2
    nx = (reticle_point[0] - cx) / (box_w / 2 + 1e-6)
    ny = (reticle_point[1] - cy) / (box_h / 2 + 1e-6)

    zone_fn = ZONE_RULES.get(class_name)
    return zone_fn(nx, ny, regions) if zone_fn else (regions[0], 0.0)

# --- display geometry (dashboard overlays only; the zone rules above stay the source of truth) ---

# Region drawn as the outer strip on the reticle's side (|nx| > 0.5 in the rules above).
_SIDE_STRIP = {("cup", "handle"), ("toothbrush", "shank"), ("book", "side_edge"),
               ("cell phone", "side_edge"), ("remote", "side_edge")}
# Region drawn as the middle band (|nx| <= 0.5).
_MIDDLE = {("cup", "body"), ("toothbrush", "handle"), ("book", "cover_face")}


def region_rect(class_name, box, region, reticle_point):
    """Pixel rectangle (x1, y1, x2, y2) covered by `region` inside `box`, matching the zone rules."""
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    hw, hh = (x2 - x1) / 2, (y2 - y1) / 2
    key = (class_name, region)
    nx = (reticle_point[0] - cx) / (hw + 1e-6)

    # Phone/remote: the central fallback zone is also named side_edge, so decide by position.
    if key in _SIDE_STRIP and (class_name not in ("cell phone", "remote") or abs(nx) > 0.5):
        if reticle_point[0] >= cx:
            return (cx + 0.5 * hw, y1, x2, y2)
        return (x1, y1, cx - 0.5 * hw, y2)
    if key in _MIDDLE:
        return (cx - 0.5 * hw, y1, cx + 0.5 * hw, y2)
    if key == ("bottle", "cap"):
        return (x1, y1, x2, cy - 0.5 * hh)
    if key == ("bottle", "body"):
        return (x1, cy - 0.5 * hh, x2, y2)
    if class_name in ("cell phone", "remote"):
        if region == "lower_support":
            return (cx - 0.5 * hw, cy + 0.4 * hh, cx + 0.5 * hw, y2)
        # The rule falls back to its first region in the central zone; show that zone.
        return (cx - 0.5 * hw, y1, cx + 0.5 * hw, cy + 0.4 * hh)
    return (x1, y1, x2, y2)   # single-region objects (spoon) and anything unknown


def normalize_rect(rect, frame_shape):
    """Pixel rectangle -> [x1, y1, x2, y2] as fractions of the frame, clamped to 0..1."""
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = rect
    clamp = lambda v: round(min(1.0, max(0.0, v)), 4)  # noqa: E731
    return [clamp(x1 / w), clamp(y1 / h), clamp(x2 / w), clamp(y2 / h)]
