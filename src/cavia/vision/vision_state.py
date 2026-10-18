# vision_state.py
from collections import deque, Counter

NO_OBJECT, SEARCHING, LOCKED, LOST = "NO_OBJECT", "SEARCHING", "LOCKED", "LOST"

class RegionTracker:
    def __init__(self, window=8, min_frames=5, lock_stability=0.7,
                 lock_conf=0.6, unlock_stability=0.5, lost_grace=5,
                 weights=(0.4, 0.2, 0.4)):
        self.window = window
        self.min_frames = min_frames
        self.lock_stability = lock_stability
        self.lock_conf = lock_conf
        self.unlock_stability = unlock_stability   # hysteresis: easier to keep a lock than to get one
        self.lost_grace = lost_grace
        self.w = weights
        self.reset()

    def reset(self):
        """call this on FSM 'Back/Cancel' to clear the lock."""
        self.history = deque(maxlen=self.window)
        self.state = NO_OBJECT
        self.locked_pair = None
        self.missed = 0
        self.out = self._make_out(None, None, 0.0)

    def _make_out(self, obj, region, conf):
        return {
            "state": self.state,
            "object": obj,
            "region": region,
            "region_confidence": round(conf, 2),
            "stable": self.state == LOCKED,
        }

    def update(self, cand):
        """cand = None or {"object", "region", "det_conf", "reticle_score"}"""
        if cand is None:
            self.missed += 1
            if self.state in (LOCKED, LOST) and self.missed <= self.lost_grace:
                self.state = LOST                    # hold last answer briefly
                self.out = self._make_out(self.out["object"], self.out["region"],
                                          self.out["region_confidence"])
            else:
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
            self.state, self.locked_pair = LOCKED, pair
        elif self.state in (LOCKED, LOST) and pair == self.locked_pair \
                and stability >= self.unlock_stability:
            self.state = LOCKED                      # keep the lock through small wobbles
        else:
            self.state, self.locked_pair = SEARCHING, None

        self.out = self._make_out(pair[0], pair[1], conf)
        return self.out