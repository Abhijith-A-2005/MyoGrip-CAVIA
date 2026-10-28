"""Vision arbitration and dashboard messages around the actual board FSM."""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
import queue
import threading
import time
import uuid

from cavia.arbitration.contracts import ArbitrationInput
from cavia.arbitration.engine import ArbitrationEngine
from cavia.arbitration.preferences import PreferenceStore
from cavia.core.contracts import Condition
from .device_link import GRIPS, keyboard_line, menu_line, next_keyboard_session
from .session import participant_id

log = logging.getLogger(__name__)
MENU_STATES = {"HOME", "ADAPTIVE", "FULL"}
ACTUATION = {"HOLDING", "CLOSING", "OPENING"}
KEY_BITS = {"w": 1, "a": 2, "s": 4, "d": 8, "e": 16}
PREFERENCE_SAMPLES = 500  # Two seconds at the wire-v3 firmware's 250 Hz rate.


class DeviceDashboardRuntime:
    def __init__(self, hub, session, *, device, db, log_file=None, feed=None,
                 detection_control=None, result_timeout=2.0, clock=time.monotonic):
        if not math.isfinite(result_timeout) or result_timeout <= 0:
            raise ValueError("result_timeout must be positive and finite")
        self.hub, self.session, self.device = hub, session, device
        self.db, self.log_file, self.feed = db, log_file, feed
        self.detection_control = detection_control or (lambda paused: None)
        self.result_timeout, self.clock = result_timeout, clock
        self.store = self.engine = None
        self.snapshot = None
        self.decisions, self.sent_menus = {}, {}
        self.accepted_menus = set()
        self.pending = self.current_key = self.current_menu_id = None
        self.sent_at = self.keyboard_sent_at = -1.0
        self.sent_revision = None
        self.vision = None
        self.resume_after = clock()
        self.frozen = False
        self.calibration_mode = False
        self.keyboard_session = None
        self.keyboard_sequence = self.keyboard_mask = 0
        self.browser_keys_at = clock()
        self.pending_selection = self.latest_selection = None
        self.menu_keyboard_used = False
        self._selection = None
        self._menu_kind = None
        self._generation = None
        self._was_fresh = False
        self._users_dirty = False
        self._activity = None
        self._menu = object()
        self._inbox = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread = None
        self.epoch = uuid.uuid4().hex
        self.log_name = Path(getattr(log_file, "name", self.epoch)).stem

    def audit(self, event_type, **data):
        if event_type == "preference_update":
            self._users_dirty = True
        if self.log_file is not None:
            state = self.session.state
            self.log_file.write(json.dumps({
                "wall": time.time(), "ts": self.clock(), "type": event_type,
                "session": self.log_name, "user": state.participant, "condition": state.condition,
                "trial": state.trial if state.trial_active else None,
                "rest": state.rest if state.rest_active else None, "data": data,
            }, default=str) + "\n")

    def key(self, key, down):
        self._inbox.put(("key", (key, down)))

    def keyboard_state(self, keys):
        self._inbox.put(("key_state", tuple(keys)))

    def release_keys(self):
        self._inbox.put(("release", None))

    def control(self, data):
        self._inbox.put(("control", data))

    def keyboard_ready(self):
        packet = self.snapshot
        return (packet is not None and self.device.status()["status"] == "connected"
                and packet["keyboard_session"] == self.keyboard_session
                and bool(packet["keyboard_connected"]))

    def open(self):
        self.store = PreferenceStore(self.db)
        self.engine = ArbitrationEngine(self.store)
        self.store.add_user(self.session.state.participant)
        self._publish_users()
        self.hub.publish("menu", None)
        self.audit("session_started", source="device", database=str(self.db))

    def close(self):
        self._cancel_selection("runtime closed")
        self.audit("session_closed")
        if self.store is not None:
            self.store.close()
            self.store = self.engine = None

    def start(self, hz=60.0):
        if not math.isfinite(hz) or hz <= 0:
            raise ValueError("Runtime frequency must be positive and finite")
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(hz,),
                                        name="cavia-device-runtime", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self, hz):
        try:
            self.open()
            while not self._stop.wait(1.0 / hz):
                try:
                    self.tick(1.0 / hz)
                except Exception:
                    log.exception("Firmware runtime tick failed")
        finally:
            self.close()

    def tick(self, dt):
        # There is deliberately no local FSM step or progress integration here.
        status = self.device.status()
        fresh = status["status"] == "connected"
        packets = self.device.drain()
        generation = (status.get("connections", 0), packets[-1]["boot"] if packets
                      else self.snapshot["boot"] if self.snapshot else None)
        if fresh and generation != self._generation:
            self._reset_context()
            self._generation = generation
        if not fresh and self._was_fresh:
            self._reset_context()
            self._generation = None
        for packet in packets:
            self._receive_board(packet, fresh=fresh)
        if not fresh:
            self._cancel_selection("stale firmware")
            self.keyboard_mask = 0
            self.keyboard_session = None
        while True:
            try:
                kind, data = self._inbox.get_nowait()
            except queue.Empty:
                break
            self._apply_input(kind, data)
        self._send_keyboard()
        if self.feed is not None:
            self.feed.poll()
        self._offer_menu()
        if self._users_dirty:
            self._publish_users()
        self._was_fresh = fresh

    def _publish_users(self):
        self._users_dirty = False
        self.hub.publish("users", {"current": self.session.state.participant, "users": self.store.users()})

    def _reset_context(self):
        self._cancel_selection("connection changed")
        self.latest_selection = None
        self.decisions.clear()
        self.sent_menus.clear()
        self.accepted_menus.clear()
        self.pending = self.current_key = self.current_menu_id = self.vision = None
        self.keyboard_session = None
        self.keyboard_mask = self.keyboard_sequence = 0
        self.keyboard_sent_at = -1.0
        self.menu_keyboard_used = False
        self.resume_after = self.clock()

    def receive_vision(self, result):
        stamp = result.get("ts")
        if (self.frozen or type(stamp) not in (int, float) or not math.isfinite(stamp)
                or stamp <= self.resume_after or stamp > self.clock() + 0.1):
            return
        if self.vision is None or stamp > self.vision["ts"]:
            self.vision = result.copy()

    def _resume(self):
        self.frozen = False
        self.pending = self.current_key = self.current_menu_id = self.vision = None
        self.resume_after = self.clock()
        self.menu_keyboard_used = False
        self._menu_kind = None
        self.detection_control(False)
        self.audit("vision_resumed", after=self.resume_after)

    def _cancel_selection(self, reason):
        if self.pending_selection is not None:
            self.engine.finish(self.pending_selection, "cancelled")
            self.audit("preference_update", interaction=self.pending_selection,
                       outcome="cancelled", reason=reason)
        self.pending_selection = self._selection = None

    def _keyboard_assisted(self):
        self.menu_keyboard_used = True
        if self.latest_selection is not None:
            self.engine.finish(self.latest_selection, "cancelled")
            self.audit("preference_update", interaction=self.latest_selection,
                       outcome="cancelled", reason="keyboard-assisted interaction")
            self.latest_selection = None
            self.pending_selection = self._selection = None

    def _receive_board(self, packet, *, fresh):
        old = self.snapshot
        new_boot = old is None or packet["boot"] != old["boot"]
        if new_boot:
            self._cancel_selection("board boot changed")
            self.latest_selection = None
            self._activity = None
            self._resume()
        gesture_changed = old is not None and packet["gesture_seq"] != old["gesture_seq"]
        gesture_delta = ((packet["gesture_seq"] - old["gesture_seq"]) & 0xFFFFFFFF) if old else 0

        decision = self.decisions.get(packet["menu_id"])
        sent = self.sent_menus.get(packet["menu_id"])
        if (fresh and packet["loaded"] and decision is not None and sent is not None
                and packet["revision"] != sent[1] and self._matches_menu(packet, decision.proposal)):
            if packet["menu_id"] not in self.accepted_menus:
                self.audit("menu_accepted", menu_id=packet["menu_id"])
                self.menu_keyboard_used = False
            self.accepted_menus.add(packet["menu_id"])
            self.current_key, self.current_menu_id = sent[0], packet["menu_id"]
            if self.pending is not None and self.pending[0].proposal.menu_id == packet["menu_id"]:
                self.pending = None
        elif packet["loaded"] and packet["menu_id"] != self.current_menu_id:
            self.current_key = self.current_menu_id = None

        keyboard_event = gesture_changed and packet["gesture_source"] in {"keyboard", "both"}
        if packet["keyboard_mask"] or keyboard_event:
            self._keyboard_assisted()
        if gesture_changed:
            gesture = "INVALID" if packet["gesture"] == "REJECTED" else packet["gesture"]
            if gesture in {"SF", "SE", "LF", "LE", "HE", "INVALID"}:
                self.hub.publish("emg", {"ts": self.clock(), "source": packet["gesture_source"], "event": gesture})
                self.audit("emg", event=gesture, source=packet["gesture_source"], sequence=packet["gesture_seq"])
        activity = packet["activity"]
        activity = activity if activity in {"REST", "FLEX_ACTIVE", "EXT_ACTIVE", "INVALID"} else "INVALID"
        if activity != self._activity:
            self._activity = activity
            source = "keyboard" if packet["keyboard_mask"] and not packet["armed"] else (
                "both" if packet["keyboard_mask"] else "device")
            self.hub.publish("emg", {"ts": self.clock(), "source": source, "activity": activity})

        confirmed = (old is not None and not new_boot and old["state"] in {"ADAPTIVE", "FULL"}
                     and packet["state"] in ACTUATION)
        if confirmed:
            self._cancel_selection("new confirmation")
            self.latest_selection = None
            self._menu_kind = old["state"] if old["menu_id"] == packet["menu_id"] else None
            self.audit("confirmed", menu_id=packet["menu_id"], grip=GRIPS[packet["active"]],
                       source=packet["gesture_source"])
            if (fresh and gesture_delta == 1 and packet["gesture"] == "LF"
                    and packet["gesture_source"] == "device" and not self.menu_keyboard_used
                    and packet["menu_id"] in self.accepted_menus and decision is not None
                    and self._menu_kind is not None):
                interaction = f"usb-{self.epoch}-{packet['boot']}-{packet['gesture_seq']}"
                self.engine.confirm(packet["menu_id"], GRIPS[packet["active"]], interaction,
                                    from_full_menu=self._menu_kind == "FULL")
                self.pending_selection = self.latest_selection = interaction
                self._selection = {"samples": packet["samples"], "max_progress": 0.0,
                                   "menu_id": packet["menu_id"], "active": packet["active"]}
        if self.pending_selection is not None:
            selection = self._selection
            if (not fresh or packet["state"] not in ACTUATION or packet["returning"]
                    or packet["menu_id"] != selection["menu_id"] or packet["active"] != selection["active"]
                    or gesture_delta > 1 or (gesture_changed and packet["gesture"] == "HE")):
                self._cancel_selection("return, reset or ambiguous telemetry")
            else:
                selection["max_progress"] = max(selection["max_progress"], packet["progress"])
                elapsed = (packet["samples"] - selection["samples"]) & 0xFFFFFFFF
                if PREFERENCE_SAMPLES <= elapsed < 0x80000000 and selection["max_progress"] >= 0.2:
                    self.engine.finish(self.pending_selection, "accepted")
                    self.audit("preference_update", interaction=self.pending_selection, outcome="accepted")
                    self.pending_selection = self._selection = None

        self.snapshot = packet
        if packet["state"] in {"ADAPTIVE", "FULL"}:
            self._menu_kind = packet["state"]
            if old is not None and old["state"] in ACTUATION:
                # Full Menu starts a new selection after a completed return.
                self.latest_selection = None
                self.menu_keyboard_used = False
        if packet["state"] in ACTUATION and not self.frozen:
            self.frozen = True
            self.pending = None
            self.detection_control(True)
            self.audit("vision_paused", menu_id=packet["menu_id"])
        if old is not None and packet["state"] == "HOME" and old["state"] != "HOME":
            self._resume()
            self.latest_selection = None
        menu = self._board_menu(packet)
        if menu != self._menu:
            self._menu = menu
            self.hub.publish("menu", menu)
        self.hub.publish("fsm", self._board_fsm(packet))

    @staticmethod
    def _matches_menu(packet, proposal):
        return (packet["menu_id"] == proposal.menu_id
                and packet["adaptive"][:packet["adaptive_count"]] == list(map(int, proposal.items))
                and packet["full"][:packet["full_count"]] == list(map(int, proposal.full_menu)))

    def _board_menu(self, packet):
        if not packet["loaded"]:
            return None
        decision = self.decisions.get(packet["menu_id"])
        if (decision is not None and packet["menu_id"] in self.accepted_menus
                and self._matches_menu(packet, decision.proposal)):
            return decision.proposal.to_dict()
        adaptive = [GRIPS[g] for g in packet["adaptive"][:packet["adaptive_count"]]]
        full = [GRIPS[g] for g in packet["full"][:packet["full_count"]]]
        return {"ts": 0.0, "menu_id": packet["menu_id"], "condition": Condition.C3_ADAPTIVE.value,
                "context": {"object": None, "region": None, "region_confidence": 0.0},
                "policy": "FULL_COMPATIBLE" if adaptive else "FULL_MENU", "items": adaptive,
                "scores": [0.0] * len(adaptive),
                "confidence": {"vision": 0.0, "evidence_n": 0, "top_share": 0.0, "margin": 0.0},
                "full_menu": full}

    def _board_fsm(self, packet):
        state = packet["state"]
        kind = state if state in {"ADAPTIVE", "FULL"} else self._menu_kind if state in ACTUATION else None
        if state in ACTUATION:
            selected = GRIPS[packet["active"]]
        elif kind is not None:
            selected = GRIPS[packet["adaptive" if kind == "ADAPTIVE" else "full"][packet["selected"]]]
        else:
            selected = None
        return {"ts": self.clock(), "menu_id": packet["menu_id"] if packet["loaded"] else None,
                "state": state, "menu_kind": kind, "selected_index": packet["selected"],
                "selected_grip": selected,
                "active_grip": GRIPS[packet["active"]] if packet["active"] != -1 else None,
                "grip_progress": packet["progress"], "wait_release": bool(packet["gate"]),
                "returning": bool(packet["returning"]), "last_event": packet["gesture"], "source": "device"}

    def _send_keyboard(self, *, force=False):
        if self.snapshot is None or self.device.status()["status"] != "connected":
            self.keyboard_mask = 0
            return
        if self.keyboard_mask and self.clock() - self.browser_keys_at > 0.35:
            self.keyboard_mask = 0
            force = True
        if not force and self.clock() - self.keyboard_sent_at < 0.1:
            return
        if self.keyboard_session is None or self.snapshot["keyboard_session"] > self.keyboard_session:
            self.keyboard_session = next_keyboard_session(self.snapshot)
            self.keyboard_sequence = 0
            self.keyboard_mask = 0
        if self.snapshot["keyboard_session"] != self.keyboard_session:
            sequence, mask = 1, 0  # Retry only the released handshake until its echo arrives.
        else:
            self.keyboard_sequence = max(self.keyboard_sequence, self.snapshot["keyboard_sequence"])
            if not self.snapshot["keyboard_connected"]:
                self.keyboard_mask = 0
            if self.keyboard_sequence == 0xFFFFFFFF:
                self.keyboard_session = next_keyboard_session(self.snapshot)
                self.keyboard_mask = 0
                sequence, mask = 1, 0
            else:
                sequence, mask = self.keyboard_sequence + 1, self.keyboard_mask
        self.device.send(keyboard_line(self.snapshot, self.keyboard_session, sequence, mask))
        self.keyboard_sequence = sequence
        self.keyboard_sent_at = self.clock()

    def _offer_menu(self):
        packet, vision = self.snapshot, self.vision
        if (packet is None or vision is None or self.frozen or self.calibration_mode or not self.keyboard_ready()
                or not packet["menu_ready"] or packet["state"] not in MENU_STATES
                or self.clock() - vision["ts"] > self.result_timeout
                or vision.get("state") != "LOCKED" or vision.get("stable") is not True):
            return
        try:
            request = ArbitrationInput(self.session.state.participant, vision.get("object"),
                                       vision.get("region"), vision.get("region_confidence"))
        except ValueError:
            return
        confidence = request.vision_confidence or 0.0
        config = self.engine.config
        key = (request.user, request.object, request.region,
               confidence >= config.low_vision, confidence >= config.shortcut_vision)
        if (self.current_key and key[1] == self.current_key[1]
                and self.current_key[2] != "unknown" and key[2] == "unknown"):
            return
        if key == self.current_key:
            self.pending = None
            return
        if self.pending is None or self.pending[1] != key:
            decision = self.engine.propose(request)
            # A pre-existing board menu cannot be mistaken for our new acknowledgement.
            if decision.proposal.menu_id == packet["menu_id"]:
                decision = self.engine.propose(request)
            self.decisions[decision.proposal.menu_id] = decision
            self.pending = (decision, key)
            self.sent_revision = None
            self.audit("menu", decision=decision.to_dict())
        if self.sent_revision == packet["revision"] and self.clock() - self.sent_at < 0.5:
            return
        proposal = self.pending[0].proposal
        self.device.send(menu_line(packet, proposal, preserve=bool(packet["loaded"])))
        self.sent_menus[proposal.menu_id] = (key, packet["revision"])
        self.sent_revision, self.sent_at = packet["revision"], self.clock()
        self.audit("menu_proposed", menu_id=proposal.menu_id, revision=packet["revision"])

    def _apply_input(self, kind, data):
        try:
            if kind == "release":
                self.keyboard_mask = 0
                self._send_keyboard(force=True)
            elif kind == "key_state":
                held = sum(KEY_BITS.get(key, 0) for key in set(data))
                before = self.keyboard_mask
                self.keyboard_mask &= held  # A heartbeat never creates a new key press.
                self.browser_keys_at = self.clock()
                if before != self.keyboard_mask:
                    self._send_keyboard(force=True)
            elif kind == "key":
                key, down = data
                if key not in KEY_BITS or type(down) is not bool or not self.keyboard_ready():
                    return
                self.browser_keys_at = self.clock()
                before = self.keyboard_mask
                bit = KEY_BITS[key]
                self.keyboard_mask = before | bit if down else before & ~bit
                if before != self.keyboard_mask:
                    if down:
                        self._keyboard_assisted()
                    self._send_keyboard(force=True)
            elif kind == "control":
                action = data.get("action")
                if action == "device_setup":
                    enabled = data.get("enabled")
                    if type(enabled) is not bool:
                        raise ValueError("Calibration mode must be a boolean")
                    if (self.snapshot is None or self.device.status()["status"] != "connected"
                            or self.snapshot["state"] not in MENU_STATES or self.keyboard_mask):
                        raise ValueError("Start calibration at Home or a menu with keys released")
                    if enabled:
                        # x cancels any capture and resets the firmware to uncalibrated HOME.
                        # A calibration reset is explicit, never part of ordinary startup.
                        self.device.send("x\n")
                    elif self.snapshot["state"] != "HOME":
                        raise ValueError("Resume after firmware returns HOME")
                    self.calibration_mode = enabled
                    self.pending = self.current_key = self.current_menu_id = self.vision = None
                    self.resume_after = self.clock()
                    self.audit("calibration_mode", enabled=enabled)
                elif action == "device_command":
                    command = data.get("command")
                    if command not in {"r", "f", "e", "h", "v", "x", "?"}:
                        raise ValueError("Unknown calibration command")
                    if (not self.calibration_mode or self.snapshot is None
                            or self.snapshot["state"] != "HOME" or self.keyboard_mask):
                        raise ValueError("Calibrate at firmware HOME with keys released")
                    self.device.send(command + "\n")
                elif action == "set_session":
                    if (not self.keyboard_ready() or self.snapshot["state"] not in MENU_STATES
                            or self.frozen or not self.snapshot["menu_ready"] or self.keyboard_mask):
                        raise ValueError("Change participant before confirming a grip, while resting with keys released")
                    if data.get("condition") != Condition.C3_ADAPTIVE.value:
                        raise ValueError("Live arbitration currently supports C3 only")
                    participant_id(data.get("participant"))
                    self.session.control(data)
                    self._reset_context()
                    self.store.add_user(self.session.state.participant)
                    self._publish_users()
                elif action == "add_user":
                    user = participant_id(data.get("user"))
                    if any(profile["user"] == user for profile in self.store.users()):
                        raise ValueError(f"User {user} already exists")
                    self.store.add_user(user)
                    self.audit("user_added", user=user)
                    self._publish_users()
                else:
                    self.session.control(data)
        except ValueError as exc:
            self.audit("control_rejected", action=data.get("action") if kind == "control" else kind,
                       reason=str(exc))
            if kind == "control":
                self.hub.publish("notice", {"action": data.get("action"), "ok": False, "message": str(exc)})
            log.info("Rejected dashboard control: %s", exc)


def main():
    """Test vision-menu arbitration against a real board without launching the UI."""
    import argparse
    from .device_link import DeviceLink
    from .hub import Hub
    from .session import Session
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--seconds", type=float, default=8)
    parser.add_argument("--object", default="cup")
    parser.add_argument("--region", default="handle")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 60:
        parser.error("--seconds must be between 1 and 60")
    hub = Hub()
    link = DeviceLink(args.port)
    runtime = DeviceDashboardRuntime(hub, Session(hub.publish), device=link, db=":memory:")
    link.start()
    runtime.open()
    try:
        deadline = time.monotonic() + args.seconds
        supplied = False
        while time.monotonic() < deadline:
            runtime.tick(0.02)
            if runtime.keyboard_ready() and not supplied:
                runtime.receive_vision({"ts": time.monotonic(), "state": "LOCKED", "stable": True,
                                        "object": args.object, "region": args.region, "region_confidence": 0.9})
                supplied = True
            time.sleep(0.02)
        packet = runtime.snapshot
        if (link.status()["status"] != "connected" or packet is None
                or packet["menu_id"] not in runtime.accepted_menus):
            print("FAIL:", link.status(), "board state:", packet)
            return 1
        print("PASS: dashboard vision menu acknowledged by firmware")
        print(f"Menu={packet['menu_id']}, state={packet['state']}, "
              f"selected={hub.latest('fsm')['selected_grip']}, calibrated={packet['calibrated']}")
        return 0
    finally:
        runtime.close()
        link.close()


if __name__ == "__main__":
    raise SystemExit(main())
