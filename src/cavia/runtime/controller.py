"""Dynamic menus around the unchanged reference FSM; LF freezes until HOME."""

from __future__ import annotations

import math
import time

from cavia.arbitration.contracts import ArbitrationInput, user_key
from cavia.arbitration.demo import ArbitrationSimApp
from cavia.core.contracts import EmgEvent, FsmState
from cavia.fsm.machine import ACTUATION_STATES, MENU_STATES


class LiveSimApp(ArbitrationSimApp):
    def __init__(self, engine, user="1", *, result_timeout=2.0, clock=time.monotonic, audit=None):
        if not math.isfinite(result_timeout) or result_timeout <= 0:
            raise ValueError("result_timeout must be positive and finite")
        self.clock = clock
        self.audit = audit or (lambda event, **data: None)
        self.user = user_key(user)
        self.result_timeout = result_timeout
        self.frozen = False
        self.ready = False
        self.manual_full = False
        self.context_key = None
        self.resume_after = clock()
        self.last_stamp = None
        self.last_vision_key = None
        self.vision_status = "Waiting for a fresh LOCKED result"
        super().__init__(engine, ArbitrationInput(self.user, "unknown"))

    def note(self, message):
        super().note(message)
        self.audit("note", message=message)

    def load_menu(self):
        # Also called by the base constructor. Live vision supplies the menu.
        pass

    def set_user(self, user):
        """Future dashboard hook: switch profiles only at HOME with released keys."""
        if self.fsm.state is not FsmState.HOME or self.keys.held:
            raise ValueError("Change user only at HOME with all keys released")
        self.user = user_key(user)
        self._home()

    def _clear_menu(self, reason):
        if self.frozen:
            return
        if self.fsm.state not in (FsmState.HOME, *MENU_STATES) or self.fsm.progress != 0:
            raise RuntimeError("Live replacement is only allowed before confirmation, with the hand open")
        if self.decision is not None:
            self.note(reason)
            self.audit("menu_cleared", reason=reason)
        self.fsm.reset()
        self.decision = None
        self.request = ArbitrationInput(self.user, "unknown")
        self.context_key = None
        self.ready = False
        self.manual_full = False
        self._prev_state = self.fsm.state
        self.vision_status = reason

    def _home(self):
        self.frozen = False
        self.resume_after = self.clock()
        self.last_stamp = None
        self.last_vision_key = None
        self._clear_menu("HOME: waiting for a new vision result and released keys")
        self.audit("vision_resumed", after=self.resume_after)

    def receive(self, result):
        """Accept validated transport packets on the GUI thread only."""
        if self.frozen:
            return
        now = self.clock()
        stamp = result["ts"]
        if stamp <= self.resume_after or (self.last_stamp is not None and stamp <= self.last_stamp):
            return
        self.last_stamp = stamp
        vision_key = (result["state"], result["object"], result["region"], result["region_confidence"])
        if vision_key != self.last_vision_key:
            self.audit("vision", **result)
            self.last_vision_key = vision_key
        if now - stamp > self.result_timeout:
            self._clear_menu("Vision output expired; waiting for a fresh result")
            return
        if result["state"] != "LOCKED" or not result["stable"]:
            self._clear_menu(f"Vision {result['state']}: waiting for a stable target")
            return
        request = ArbitrationInput(
            self.user, result["object"], result["region"], result["region_confidence"],
        )
        self.vision_status = f"LIVE: {request.object} / {request.region} | confidence {request.vision_confidence:.2f}"
        if self.fsm.state is FsmState.HOME and self.keys.held:
            return

        # Confidence changes matter to ranking only when a policy gate changes.
        # Heartbeats and within-band jitter must not create database rows per frame.
        cfg = self.engine.config
        v = request.vision_confidence
        band = (v >= cfg.low_vision, v >= cfg.shortcut_vision)
        key = (request.user, request.object, request.region, band)
        if key == self.context_key:
            return
        same_target = self.context_key is not None and key[:3] == self.context_key[:3]
        selected = self.fsm.selected_grip() if same_target else None
        manual_full = self.manual_full
        decision = self.engine.propose(request)
        self._clear_menu("New vision context")
        # reset/load is confined to this simulator adapter and zero-progress menus.
        # The original FSM's HOME-only load_menu contract remains intact.
        if not self.fsm.load_menu(decision.proposal):
            raise RuntimeError("Could not load live menu from HOME")
        self.manual_full = manual_full
        if manual_full and self.fsm.state is FsmState.ADAPTIVE:
            self.fsm.on_event(EmgEvent.LE)
        items = self.fsm.current_items()
        if selected in items:
            self.fsm.selected = items.index(selected)
        self.request, self.decision, self.context_key = request, decision, key
        self.menu_id = decision.proposal.menu_id
        self._prev_state = self.fsm.state
        self.vision_status = f"LIVE: {request.object} / {request.region} | confidence {v:.2f}"
        self.note(f"Live menu #{self.menu_id}: {request.object}/{request.region}")
        self.audit("menu", decision=decision.to_dict())

    def check_source(self, *, exited=False):
        if self.frozen:
            return
        if exited:
            self._clear_menu("Vision process stopped; restart CAVIA to reconnect")
        elif self.last_stamp is not None and self.clock() - self.last_stamp > self.result_timeout:
            self._clear_menu("No fresh vision output; waiting for recovery")

    def mark_rendered(self):
        self.ready = self.fsm.state in MENU_STATES and self.decision is not None

    def key_down(self, name):
        name = name.lower()
        if name in {"m", "1", "2", "3", "u"}:
            self.note("Live mode: context comes from vision; user is set with --user")
            return
        if name == "a" and self.fsm.state in MENU_STATES and not self.ready:
            self.keys.press(name)
            self.note("Menu just changed: release A, inspect it, then confirm")
            return
        before = self.fsm.state
        self.audit("key_down", key=name, menu_id=self.fsm.menu_id)
        super().key_down(name)
        if before in MENU_STATES and self.fsm.state in ACTUATION_STATES:
            self.frozen = True
            self.vision_status = "FROZEN: vision ignored until HE reaches HOME"
            self.audit("confirmed", menu_id=self.fsm.menu_id, interaction_id=self.pending_id,
                       grip=self.fsm.active_grip.name, context=self.request.__dict__)
        if before is not FsmState.HOME and self.fsm.state is FsmState.HOME:
            self._home()
        if before is FsmState.ADAPTIVE and self.fsm.state is FsmState.FULL:
            self.manual_full = True
            self.ready = False

    def key_up(self, name):
        super().key_up(name)
        self.audit("key_up", key=name)

    def focus_lost(self):
        super().focus_lost()
        self.audit("focus_lost")

    def step(self, dt):
        before = self.fsm.state
        pending = self.pending_id
        super().step(dt)
        if pending is not None and self.pending_id is None:
            self.audit("preference_update", selection=self.engine.store.get_selection(pending))
        if before is not FsmState.HOME and self.fsm.state is FsmState.HOME:
            self._home()
        if before != self.fsm.state:
            self.ready = False
            self.audit("state", state=self.fsm.state.value, progress=self.fsm.progress)

    def cancel_pending(self):
        pending = self.pending_id
        super().cancel_pending()
        if pending is not None:
            self.audit("preference_update", selection=self.engine.store.get_selection(pending))