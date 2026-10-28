"""Keep vision and keyboard usable while a USB board connects or recovers."""
from __future__ import annotations

import logging
import math
from pathlib import Path
import queue
import threading
import time

from .device_runtime import DeviceDashboardRuntime
from .hub import Hub
from .live_runtime import DashboardRuntime
from .session import participant_id

log = logging.getLogger(__name__)


class _ControllerHub(Hub):
    """Cache each controller's view; only its active view reaches the browser."""

    def __init__(self, parent, owner):
        super().__init__()
        self.parent, self.owner = parent, owner

    def publish(self, kind, data):
        super().publish(kind, data)
        if self.parent.owner == self.owner:
            self.parent.hub.publish(kind, data)


class CombinedDashboardRuntime:
    def __init__(self, hub, session, *, db, device=None, log_file=None, feed=None,
                 detection_control=None, result_timeout=2.0, clock=time.monotonic):
        self.hub, self.session, self.device = hub, session, device
        self.feed, self.clock = feed, clock
        self.owner = "keyboard"
        self._inbox = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread = None
        self._input_epoch = 0
        self._held, self._blocked = set(), set()
        self._paused = {"keyboard": False, "firmware": False}
        self._detection_paused = False
        self._detection_control = detection_control or (lambda paused: None)
        self._vision = None
        self._firmware_error = None
        self._sync_users_needed = False
        self._profile = session.state.participant
        # Simulator selections must not train the real EMG profile.
        path = Path(db)
        self.keyboard_db = (path.with_name(path.stem + "-keyboard" + path.suffix)
                            if device and str(db) != ":memory:" else db)
        self.db = db
        self.keyboard_hub = _ControllerHub(self, "keyboard")
        self.firmware_hub = _ControllerHub(self, "firmware")
        options = dict(log_file=log_file, clock=clock, result_timeout=result_timeout)
        self.keyboard = DashboardRuntime(self.keyboard_hub, session, db=self.keyboard_db,
            detection_control=lambda paused: self._pause("keyboard", paused), **options)
        self.firmware = DeviceDashboardRuntime(self.firmware_hub, session, device=device, db=db,
            detection_control=lambda paused: self._pause("firmware", paused), **options) if device else None
        if self.firmware:
            self.firmware.menus_enabled = False
        for owner, child in (("keyboard", self.keyboard), ("firmware", self.firmware)):
            if child:
                audit = child.audit
                child.audit = lambda event_type, _audit=audit, _owner=owner, **data: _audit(
                    event_type, controller=_owner, **data)

    @property
    def active(self):
        return self.firmware if self.owner == "firmware" else self.keyboard

    @property
    def history_db(self):
        return self.db if self.owner == "firmware" else self.keyboard_db

    def _pause(self, owner, paused):
        self._paused[owner] = paused
        if owner == self.owner and paused != self._detection_paused:
            self._detection_paused = paused
            self._detection_control(paused)

    def audit(self, event, **data):
        self.active.audit(event, **data)

    def key(self, key, down):
        self._inbox.put(("key", self._input_epoch, (key, down)))

    def keyboard_state(self, keys):
        self._inbox.put(("key_state", self._input_epoch, tuple(keys)))

    def release_keys(self):
        self.keyboard_state(())

    def control(self, data):
        self._inbox.put(("control", self._input_epoch, data.copy()))

    def receive_vision(self, result):
        self._vision = result.copy()
        if self.keyboard.app is not None:
            self.keyboard.receive_vision(result)
        if self.firmware:
            self.firmware.receive_vision(result)

    def status(self):
        hand = self.device.status() if self.device else {
            "status": "disconnected", "battery_pct": None, "detail": "No firmware port selected"}
        reason = ""
        if self.device and self.owner == "keyboard":
            reason = self._firmware_error or hand.get("detail", "Firmware unavailable")
        return {"hand_link": hand, "controller": self.owner,
                "emg_source": "device" if self.owner == "firmware" else "keyboard",
                "device_configured": self.device is not None,
                "keyboard_ready": self.firmware.keyboard_ready() if self.firmware else False,
                "calibration_mode": bool(self.firmware and self.firmware.calibration_mode),
                "fallback_reason": reason}

    def open(self):
        self.keyboard.open()
        if self.firmware:
            self.firmware.open()
        self._sync_users()

    def _sync_users(self):
        stores = [self.keyboard._store]
        if self.firmware:
            stores.append(self.firmware.store)
        users = {self.session.state.participant}
        for store in stores:
            users.update(profile["user"] for profile in store.users())
        for store in stores:
            for user in sorted(users):
                store.add_user(user)
        self.keyboard._publish_users()
        if self.firmware:
            self.firmware._publish_users()

    def _activate(self, owner):
        if owner == self.owner:
            return
        previous = self.owner
        self._input_epoch += 1
        self._blocked.update(self._held)
        self.keyboard.app.focus_lost()
        self.keyboard.app.cancel_pending()
        if self.keyboard.app.frozen:
            # A simulated grasp is discarded, never transferred to the board.
            self.keyboard.app.fsm.progress = 0.0
            self.keyboard.app.fsm.reset()
            self.keyboard.app._home()
        if self.firmware:
            self.firmware.release_keys()
            self.firmware._cancel_selection("controller changed")
            self.firmware.menus_enabled = owner == "firmware"
        self.keyboard._publish_state(force=True)
        self.owner = owner
        self._pause(owner, self._paused[owner])
        system = self.hub.latest("system") or {
            "camera": {"status": "down", "source": "XIAO", "fps": 0, "latency_ms": 0},
            "vision": {"status": "down", "model": "Waiting"}}
        self.hub.publish("system", {**system, **self.status()})
        view = self.firmware_hub if owner == "firmware" else self.keyboard_hub
        for kind in ("menu", "fsm", "users"):
            self.hub.publish(kind, view.latest(kind))
        self.hub.publish("emg", {"ts": self.clock(), "source": "keyboard", "activity": "REST"})
        if self._vision is not None:
            self.active.receive_vision(self._vision)
        self.audit("controller_changed", previous=previous, selected=owner)

    def _input(self, kind, epoch, data):
        if kind == "key":
            key, down = data
            if down:
                self._held.add(key)
                if epoch != self._input_epoch:
                    self._blocked.add(key)
                if key not in self._blocked:
                    self.active.key(key, True)
            else:
                self._held.discard(key)
                self._blocked.discard(key)
                self.active.key(key, False)
        elif kind == "key_state":
            # A heartbeat can release a key, never introduce a press.
            self._held.intersection_update(data)
            self._blocked.intersection_update(data)
            self.active.keyboard_state(tuple(self._held - self._blocked))
        elif kind == "control":
            if data.get("action") in {"device_setup", "device_command"}:
                if self.owner != "firmware":
                    self.hub.publish("notice", {"action": data["action"], "ok": False,
                                               "message": "Wait for the firmware connection before calibrating"})
                    return
            if data.get("action") == "add_user":
                # Check both stores before the active adapter performs the edit.
                try:
                    user = participant_id(data.get("user"))
                except ValueError:
                    self.active.control(data)
                    return
                stores = [self.keyboard._store] + ([self.firmware.store] if self.firmware else [])
                if any(user == p["user"] for store in stores for p in store.users()):
                    self.hub.publish("notice", {"action": "add_user", "ok": False,
                                               "message": f"User {user} already exists"})
                    return
            self.active.control(data)
            if data.get("action") == "add_user":
                self._sync_users_needed = True

    def _tick_firmware(self):
        if self.firmware is None:
            return False
        try:
            self.firmware.tick(0.0)
            self._firmware_error = None
            return self.firmware.keyboard_ready()
        except Exception as exc:
            if str(exc) != self._firmware_error:
                log.exception("Firmware adapter unavailable; keyboard continues")
            self._firmware_error = str(exc)
            return False

    def tick(self, dt):
        self._activate("firmware" if self._tick_firmware() else "keyboard")
        while True:
            try:
                self._input(*self._inbox.get_nowait())
            except queue.Empty:
                break
        if self.feed:
            self.feed.poll()
            if self.owner == "keyboard":
                self.keyboard.app.check_source(exited=self.feed.source.exited)
        if self.owner == "firmware":
            if not self._tick_firmware():
                self._activate("keyboard")
                self.keyboard.tick(0.0)
        else:
            self.keyboard.tick(dt)
        if self._profile != self.session.state.participant:
            self._profile = self.session.state.participant
            if self.firmware and self.owner != "firmware":
                self.firmware._reset_context()
            if self.keyboard.app.user != self._profile:
                app = self.keyboard.app
                app.focus_lost()
                app.cancel_pending()
                app.fsm.progress = 0.0
                app.fsm.reset()
                app.frozen = False
                app.set_user(self._profile)
            self._sync_users()
        if self._sync_users_needed:
            self._sync_users()
            self._sync_users_needed = False

    def close(self):
        if self.firmware:
            self.firmware.close()
        self.keyboard.close()

    def start(self, hz=60.0):
        if not math.isfinite(hz) or hz <= 0:
            raise ValueError("Runtime frequency must be positive and finite")
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(hz,), name="cavia-runtime", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self, hz):
        try:
            self.open()
            last = self.clock()
            while not self._stop.wait(1 / hz):
                now = self.clock()
                try:
                    self.tick(now - last)
                except Exception:
                    log.exception("Dashboard runtime tick failed")
                last = now
        finally:
            self.close()
