# vision_state.py
import time
from collections import deque, Counter

NO_OBJECT, SEARCHING, LOCKED, LOST = "NO_OBJECT", "SEARCHING", "LOCKED", "LOST"
# LOST is kept so existing imports do not break. It is no longer emitted.


def make_out(state, obj, region, conf, det=0.0, ret=0.0, stability=0.0):
    # det_conf / reticle_score / stability are the parts of region_confidence (shown on the dashboard).
    return {
        "state": state,
        "object": obj,
        "region": region,
        "region_confidence": round(conf, 2),
        "stable": state == LOCKED,
        "det_conf": round(det, 3),
        "reticle_score": round(ret, 3),
        "stability": round(stability, 3),
    }


def score_window(history, weights):
    """Winning (object, region) pair of a candidate window, with its confidence parts."""
    pair, count = Counter((h["object"], h["region"]) for h in history).most_common(1)[0]
    stability = count / len(history)
    match = [h for h in history if (h["object"], h["region"]) == pair]
    det = sum(h["det_conf"] for h in match) / len(match)
    ret = sum(h["reticle_score"] for h in match) / len(match)
    conf = weights[0] * det + weights[1] * ret + weights[2] * stability
    return pair, stability, conf, det, ret


class RegionTracker:
    """Stage 1: locks a stable (object, region) pair. Once LOCKED the output is frozen until reset()."""

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
        self.out = make_out(self.state, None, None, 0.0)

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

        pair, stability, conf, det, ret = score_window(self.history, self.w)
        enough = len(self.history) >= self.min_frames
        if enough and stability >= self.lock_stability and conf >= self.lock_conf:
            self.state = LOCKED
        else:
            self.state = SEARCHING
        self.out = make_out(self.state, pair[0], pair[1], conf, det, ret, stability)
        return self.out


class RegionSwitchTracker:
    """Stage 2: commits a region lock, then keeps watching so a new region can replace it.

    The committed output never changes frame to frame. A different region has to pass the same lock
    rule (min frames, stability, confidence) before it replaces the committed one.
    """

    def __init__(self, window=8, min_frames=5, lock_stability=0.7,
                 lock_conf=0.6, lost_grace=5, weights=(0.4, 0.2, 0.4)):
        self.window = window
        self.min_frames = min_frames
        self.lock_stability = lock_stability
        self.lock_conf = lock_conf
        self.lost_grace = lost_grace          # missed frames before stale votes are dropped
        self.w = weights
        self.reset()

    def reset(self):
        self.history = deque(maxlen=self.window)
        self.missed = 0
        self.committed = None                 # (object, region) of the current lock
        self.out = None                       # published json of the current lock (None before the first)
        self.display = None                   # provisional json for the on-screen HUD

    def update(self, cand):
        """Returns the committed output, or None until the first region lock."""
        if cand is None:
            self.missed += 1
            if self.missed > self.lost_grace:
                self.history.clear()          # old votes must not decide a later return to the object
            return self.out                   # hold the last lock

        self.missed = 0
        self.history.append(cand)

        pair, stability, conf, det, ret = score_window(self.history, self.w)
        ready = (len(self.history) >= self.min_frames
                 and stability >= self.lock_stability
                 and conf >= self.lock_conf)

        if pair == self.committed:
            self.out = make_out(LOCKED, pair[0], pair[1], conf, det, ret, stability)
        elif ready:
            self.committed = pair             # first lock, or a new region replacing the old one
            self.out = make_out(LOCKED, pair[0], pair[1], conf, det, ret, stability)

        state = LOCKED if pair == self.committed else SEARCHING
        self.display = make_out(state, pair[0], pair[1], conf, det, ret, stability)
        return self.out


class TwoStageTracker:
    """Stage 1: lock the object (region "unknown"). Stage 2: lock its functional region, re-lockable.

    stage 1  circle reticle, object lock          -> json #1 (region unknown)
    settle   circle stays for stage2_delay seconds so the object lock is stable before regions start
    stage 2  cross reticle, region lock           -> json #2, and a new json whenever a new region locks
    Everything returns to stage 1 on reset() (HOME, camera change, stale frame).
    """

    def __init__(self, stage2_delay=1.0, **kw):
        self.kw = kw
        self.stage2_delay = stage2_delay
        self.reset()

    def reset(self):
        self.stage = 1
        self.object_tracker = RegionTracker(**self.kw)
        self.region_tracker = None
        self.locked_object = None
        self.region_start = None
        self.out = self.object_tracker.out        # what gets published
        self.display_out = self.out               # what the HUD shows (includes provisional stage-2 progress)

    def cross_visible(self, now=None):
        """True once stage 2 has started and the settle delay has passed."""
        now = time.monotonic() if now is None else now
        return self.stage == 2 and now >= self.region_start

    def update(self, cand, now=None):
        now = time.monotonic() if now is None else now

        if self.stage == 1:
            out = self.object_tracker.update(cand)
            self.out = self.display_out = out
            if out["state"] == LOCKED:            # json #1 is published now
                self.stage = 2
                self.locked_object = out["object"]
                self.region_start = now + self.stage2_delay
                self.region_tracker = RegionSwitchTracker(**self.kw)
            return self.out

        if now < self.region_start:
            return self.out                       # settling: object lock held, no region work yet

        committed = self.region_tracker.update(cand)
        if self.region_tracker.display is not None:
            self.display_out = self.region_tracker.display
        if committed is not None:
            self.out = committed                  # json #2, then a new json on each region change
        return self.out