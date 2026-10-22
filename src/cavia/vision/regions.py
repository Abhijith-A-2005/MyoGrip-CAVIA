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