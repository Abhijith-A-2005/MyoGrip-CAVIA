"""Arbitration + FSM for the dashboard: browser keys in, menus, FSM state and EMG events out.

Runs the same controller as `python -m cavia --user 1` (cavia.runtime.controller.LiveSimApp), but takes
its keys from the dashboard instead of a pygame window. The controller, its SQLite preference store and
vision polling all live on one runtime thread: LiveSimApp and VisionProcess are single-threaded by
design, and SQLite connections only work on the thread that opened them. Other threads talk to the
runtime only through `key()` and `control()`, which queue work for that thread.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import IO, Callable

from cavia.arbitration.engine import ArbitrationEngine
from cavia.arbitration.preferences import PreferenceStore
from cavia.core.contracts import Activity, Condition, FsmState
from cavia.runtime.controller import LiveSimApp
from keyboard_sim.fsm.machine import ACTUATION_STATES

from .hub import Hub
from .session import Session, participant_id
from .vision_feed import VisionFeed

log = logging.getLogger(__name__)

# The arbitration engine implements Adaptive CAVIA only; C1/C2 need engine support first.
LIVE_CONDITIONS = frozenset({Condition.C3_ADAPTIVE.value})
FSM_MIN_INTERVAL = 1 / 30   # progress-only updates at most 30 times a second


class DashboardRuntime:
    def __init__(
        self,
        hub: Hub,
        session: Session,
        *,
        db: str | Path,
        log_file: IO[str] | None = None,
        feed: VisionFeed | None = None,
        detection_control: Callable[[bool], None] | None = None,
        result_timeout: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.hub = hub
        self.session = session
        self.db = db
        self.feed = feed
        self.detection_control = detection_control
        self.result_timeout = result_timeout
        self.clock = clock
        self._log_file = log_file
        self._log_name = Path(getattr(log_file, "name", "session")).stem
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.app: LiveSimApp | None = None
        self._store: PreferenceStore | None = None
        self._in_key = False
        self._emg_events: list = []
        self._menu_id: object = object()      # sentinel: nothing published yet
        self._fsm_key: tuple | None = None
        self._fsm_at = -1.0
        self._last_progress: float | None = None
        self._activity = Activity.REST
        self._users_dirty = False

    # ---- any thread ---------------------------------------------------------

    def key(self, key: str, down: bool) -> None:
        self._inbox.put(("key", key, down))

    def control(self, data: dict) -> None:
        self._inbox.put(("control", data))

    def audit(self, event: str, **data) -> None:
        """Session log record (docs/interfaces.md section 6), written on the runtime thread."""
        if event == "preference_update":
            self._users_dirty = True          # selection counts changed
        if self._log_file is None:
            return
        s = self.session.state
        record = {
            "wall": time.time(), "ts": self.clock(), "session": self._log_name,
            "user": self.app.user if self.app is not None else s.participant,
            "condition": s.condition, "trial": s.trial if s.trial_active else None,
            "type": event, "data": data,
        }
        self._log_file.write(json.dumps(record, default=str) + "\n")

    def start(self, hz: float = 60.0) -> None:
        self._thread = threading.Thread(target=self._run, args=(hz,), name="cavia-runtime", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # ---- runtime thread -----------------------------------------------------

    def open(self) -> None:
        """Create the store, engine and controller on the calling thread (the runtime thread)."""
        self._store = PreferenceStore(self.db)
        self.app = LiveSimApp(
            ArbitrationEngine(self._store),
            self.session.state.participant,
            result_timeout=self.result_timeout,
            clock=self.clock,
            audit=self.audit,
            detection_control=self.detection_control,
        )
        fsm_on_event = self.app.fsm.on_event

        def on_event(event):
            # Record only gestures that reached the FSM from a real key press, not the
            # controller's own internal calls (e.g. reopening the Full Menu after a reload).
            if self._in_key:
                self._emg_events.append(event)
            return fsm_on_event(event)

        self.app.fsm.on_event = on_event
        self.audit("session_started", user=self.app.user, database=str(self.db))
        self._publish_users()
        self._publish_state(force=True)

    def close(self) -> None:
        if self.app is not None:
            try:
                self.app.cancel_pending()     # an unfinished grip is not learned
                self.audit("session_closed")
            finally:
                if self._store is not None:
                    self._store.close()
                self.app = None

    def tick(self, dt: float) -> None:
        app = self.app
        while True:
            try:
                item = self._inbox.get_nowait()
            except queue.Empty:
                break
            if item[0] == "key":
                self._apply_key(item[1], item[2])
            else:
                self._apply_control(item[1])

        if self._users_dirty:
            self._publish_users()
        if self.feed is not None:
            self.feed.poll()                  # publishes vision, then hands results to app.receive
            app.check_source(exited=self.feed.source.exited)
        app.step(dt)
        self._publish_state()
        app.mark_rendered()                   # the menu has gone out, so LF may confirm it

    def receive_vision(self, result: dict) -> None:
        """VisionFeed `on_result` hook; called from `tick` on the runtime thread."""
        if self.app is not None:
            self.app.receive(result)

    def _run(self, hz: float) -> None:
        try:
            self.open()
        except Exception:  # noqa: BLE001
            log.exception("Could not start the arbitration runtime")
            return
        period = 1.0 / hz
        last = self.clock()
        try:
            while not self._stop.wait(period):
                now = self.clock()
                try:
                    self.tick(now - last)
                except Exception:  # noqa: BLE001  keep serving; the log shows what went wrong
                    log.exception("Runtime tick failed")
                last = now
        finally:
            self.close()

    def _apply_key(self, key: str, down: bool) -> None:
        if not down:
            self.app.key_up(key)
            return
        self._in_key = True
        try:
            self.app.key_down(key)
        finally:
            self._in_key = False
        # Ordering rule (section 9): the gesture goes out before the FSM update it causes.
        for event in self._emg_events:
            self.hub.publish("emg", {"ts": self.clock(), "source": "keyboard", "event": event.value})
        self._emg_events.clear()

    def _apply_control(self, data: dict) -> None:
        try:
            if data.get("action") == "set_session":
                if data.get("condition") not in LIVE_CONDITIONS:
                    raise ValueError("Live mode serves Adaptive CAVIA only (C1/C2 need engine support)")
                if self.app.fsm.state is not FsmState.HOME or self.app.keys.held:
                    raise ValueError("Change the session at CAVIA Home with all keys released")
                self.session.control(data)
                self.app.set_user(self.session.state.participant)
                self._store.add_user(self.app.user)
                self._publish_users()
            elif data.get("action") == "add_user":
                user = participant_id(data.get("user"))
                if any(u["user"] == user for u in self._store.users()):
                    raise ValueError(f"User {user} already exists")
                self._store.add_user(user)
                self.audit("user_added", user=user)
                self._publish_users()
            else:
                self.session.control(data)
        except ValueError as err:
            log.info("Rejected %s: %s", data.get("action"), err)
            self.audit("control_rejected", action=data.get("action"), reason=str(err))
            self.hub.publish("notice", {"action": data.get("action"), "ok": False, "message": str(err)})

    def _publish_users(self) -> None:
        """Every known profile; the current user is listed even before it has any history."""
        self._users_dirty = False
        users = self._store.users()
        if not any(u["user"] == self.app.user for u in users):
            users.append({"user": self.app.user, "created_at": None, "selections": 0, "accepted": 0,
                          "last_used": None})
        self.hub.publish("users", {"current": self.app.user, "users": users})

    def _publish_state(self, force: bool = False) -> None:
        app = self.app
        now = self.clock()

        # Activity matters only in actuation; leaving it always reports a rest.
        activity = app.keys.activity() if app.fsm.state in ACTUATION_STATES else Activity.REST
        if activity is not self._activity:
            self._activity = activity
            self.hub.publish("emg", {"ts": now, "source": "keyboard", "activity": activity.value})

        menu_id = app.decision.proposal.menu_id if app.decision is not None else None
        if force or menu_id != self._menu_id:
            self._menu_id = menu_id
            self.hub.publish("menu", app.decision.proposal.to_dict() if app.decision is not None else None)

        status = app.fsm.status(now).to_dict()
        status["returning"] = app.fsm.returning
        key = tuple(v for k, v in status.items() if k not in ("ts", "grip_progress"))
        progress_only = key == self._fsm_key and status["grip_progress"] != self._last_progress
        if (force or key != self._fsm_key
                or (progress_only and now - self._fsm_at >= FSM_MIN_INTERVAL)):
            self._fsm_key, self._fsm_at = key, now
            self._last_progress = status["grip_progress"]
            self.hub.publish("fsm", status)
