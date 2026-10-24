# vision_state.py
from collections import deque, Counter

NO_OBJECT, SEARCHING, LOCKED, LOST = "NO_OBJECT", "SEARCHING", "LOCKED", "LOST"
# LOST is kept so existing imports don't break; it is no longer emitted.


class RegionTracker:
    """locks a stable (object, region) pair. once LOCKED the output is frozen until reset()."""

    def __init__(self, window=8, min_frames=5, lock_stability=0.7,
                 lock_conf=0.6, lost_grace=5, weights=(0.4, 0.2, 0.4)):
        self.window = window
        self.min_frames = min_frames
        self.lock_stability = lock_stability
        self.lock_conf = lock_conf
        self.lost_grace = lost_grace          # missed frames tolerated while still SEARCHING
        self.w = weights
        self.reset()

    def reset(self):
        self.history = deque(maxlen=self.window)
        self.state = NO_OBJECT
        self.missed = 0
        self.out = self._make_out(None, None, 0.0)

    def _make_out(self, obj, region, conf, det=0.0, ret=0.0, stability=0.0):
        # det_conf / reticle_score / stability are the parts of region_confidence (dashboard).
        return {
            "state": self.state,
            "object": obj,
            "region": region,
            "region_confidence": round(conf, 2),
            "stable": self.state == LOCKED,
            "det_conf": round(det, 3),
            "reticle_score": round(ret, 3),
            "stability": round(stability, 3),
        }

    def update(self, cand):
        """cand = None or {"object", "region", "det_conf", "reticle_score", ...}"""
        if self.state == LOCKED:
            return self.out                   # hard lock: no flicker

        if cand is None:
            self.missed += 1
            if self.missed > self.lost_grace:
                self.reset()
            return self.out

        self.missed = 0
        self.history.append(cand)

        pair, count = Counter((h["object"], h["region"]) for h in self.history).most_common(1)[0]
        stability = count / len(self.history)
        match = [h for h in self.history if (h["object"], h["region"]) == pair]
        det = sum(h["det_conf"] for h in match) / len(match)
        ret = sum(h["reticle_score"] for h in match) / len(match)
        conf = self.w[0] * det + self.w[1] * ret + self.w[2] * stability

        enough = len(self.history) >= self.min_frames
        if enough and stability >= self.lock_stability and conf >= self.lock_conf:
            self.state = LOCKED
        else:
            self.state = SEARCHING
        self.out = self._make_out(pair[0], pair[1], conf, det, ret, stability)
        return self.out


class TwoStageTracker:
    """stage 1: lock the object (region = "unknown"). stage 2: lock its functional region."""

    def __init__(self, **kw):
        self.kw = kw
        self.reset()

    def reset(self):
        """back to stage 1. HOME / camera change / stale frame all land here."""
        self.stage = 1
        self.object_tracker = RegionTracker(**self.kw)
        self.region_tracker = None
        self.locked_object = None
        self.out = self.object_tracker.out        # what gets published
        self.display_out = self.out               # what the HUD shows (includes stage-2 progress)

    def update(self, cand):
        if self.stage == 1:
            out = self.object_tracker.update(cand)
            self.out = self.display_out = out
            if out["state"] == LOCKED:            # json #1 is published now
                self.stage = 2
                self.locked_object = out["object"]
                self.region_tracker = RegionTracker(**self.kw)
        else:
            self.display_out = self.region_tracker.update(cand)
            if self.region_tracker.state == LOCKED:
                self.out = self.display_out       # json #2
            # until then the published output stays json #1 (object locked, region unknown)
        return self.out