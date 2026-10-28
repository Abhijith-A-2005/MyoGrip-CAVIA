"""Dashboard uses acknowledged board state, never a locally stepped FSM."""
from collections import deque
from copy import deepcopy
import io
import json
from types import SimpleNamespace

import pytest

from cavia.server.device_link import parse_snapshot
from cavia.server.device_runtime import DeviceDashboardRuntime
from cavia.server.hub import Hub
from cavia.server.session import Session


def home(**changes):
    packet = dict(v=1, wire=3, keyboard_wire=2, boot=7, revision=1, samples=100,
                  keyboard_session=0, keyboard_sequence=0, keyboard_mask=0, keyboard_connected=0,
                  rest=63, menu_ready=1, calibrated=1, armed=1, activity="REST", gesture="NONE",
                  gesture_source="device", gesture_seq=0, state="HOME", menu_id=0, loaded=0,
                  selected=0, active=-1, progress=0, gate=0, returning=0,
                  adaptive_count=0, adaptive=[0, 0, 0, 0], full_count=0, full=[0, 0, 0, 0])
    packet.update(changes)
    return packet


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


class Board:
    def __init__(self):
        self.packet = home()
        self.packets = deque([deepcopy(self.packet)])
        self.sent = []
        self.fresh = True
        self.connections = 1

    def status(self):
        return {"status": "connected" if self.fresh else "stale", "connections": self.connections}

    def drain(self):
        packets = list(self.packets)
        self.packets.clear()
        return packets

    def send(self, line):
        if not self.fresh:
            raise ValueError("No fresh telemetry")
        self.sent.append(line)

    def emit(self, **changes):
        packet = {**deepcopy(self.packet), "samples": self.packet["samples"] + 25, **changes}
        assert parse_snapshot("MGSTATE " + json.dumps(packet)) is not None, packet
        self.packet = packet
        self.packets.append(deepcopy(packet))

    @property
    def menus(self):
        return [line for line in self.sent if line.startswith("@")]

    @property
    def keys(self):
        return [line for line in self.sent if line.startswith("K")]


@pytest.fixture
def rt():
    board, clock, hub, paused, audit = Board(), Clock(), Hub(), [], io.StringIO()
    runtime = DeviceDashboardRuntime(hub, Session(hub.publish), device=board, db=":memory:",
                                     clock=clock, detection_control=paused.append, log_file=audit)
    runtime.test = SimpleNamespace(board=board, clock=clock, hub=hub, paused=paused, audit=audit)
    runtime.open()
    runtime.tick(0)
    yield runtime
    runtime.close()


def ready(rt):
    values = list(map(int, rt.test.board.keys[-1].split()[1:]))
    rt.test.clock.now += 0.1
    rt.test.board.emit(keyboard_session=values[1], keyboard_sequence=values[2],
                       keyboard_mask=0, keyboard_connected=1)
    rt.tick(0)
    assert rt.keyboard_ready()


def lock(rt, object="cup", region="handle", confidence=0.9):
    rt.test.clock.now += 0.1
    rt.receive_vision(dict(ts=rt.clock(), state="LOCKED", stable=True, object=object,
                           region=region, region_confidence=confidence))
    rt.tick(0)


def acknowledge(rt):
    values = list(map(int, rt.test.board.menus[-1].split()[1:]))
    rt.test.clock.now += 0.1
    rt.test.board.emit(menu_id=values[2], revision=rt.snapshot["revision"] + 1, loaded=1,
                       state="FULL" if values[3] & 1 or not values[4] else "ADAPTIVE",
                       adaptive_count=values[4], adaptive=values[5:9],
                       full_count=values[9], full=values[10:14])
    rt.tick(0)


def prepare_menu(rt):
    ready(rt)
    lock(rt)
    acknowledge(rt)


def confirm(rt, source="device", delta=1):
    packet = rt.snapshot
    name = "full" if packet["state"] == "FULL" else "adaptive"
    grip = packet[name][packet["selected"]]
    rt.test.clock.now += 0.1
    rt.test.board.emit(state="CLOSING", menu_ready=0, active=grip, progress=0.025,
                       gesture="LF", gesture_source=source,
                       gesture_seq=packet["gesture_seq"] + delta, revision=packet["revision"] + 1)
    rt.tick(0)


def test_initial_release_handshake_precedes_any_menu(rt):
    assert rt.test.board.keys == ["K 7 1 1 0\n"]
    lock(rt)
    assert rt.test.board.menus == []
    assert rt.test.hub.latest("menu") is None
    assert not hasattr(rt, "app")


def test_menu_is_published_only_after_exact_board_acknowledgement(rt):
    ready(rt)
    lock(rt)
    proposal = rt.pending[0].proposal
    assert rt.test.hub.latest("menu") is None
    assert len(rt.test.board.menus) == 1
    acknowledge(rt)
    assert rt.test.hub.latest("menu")["menu_id"] == proposal.menu_id
    assert rt.test.hub.latest("menu")["items"] == [grip.name for grip in proposal.items]
    assert rt.current_key is not None and rt.pending is None


def test_ticks_do_not_invent_progress_or_confirmation(rt):
    prepare_menu(rt)
    rt.key("a", True)
    rt.tick(10)
    assert rt.test.board.keys[-1].strip().endswith(" 2")
    assert rt.test.hub.latest("fsm")["state"] == "ADAPTIVE"
    assert rt.test.hub.latest("fsm")["grip_progress"] == 0
    confirm(rt, source="keyboard")
    before = rt.test.hub.latest("fsm")["grip_progress"]
    rt.tick(100)
    assert rt.test.hub.latest("fsm")["grip_progress"] == before
    assert rt.store.history() == []


def test_confirmation_freezes_vision_until_board_returns_home(rt):
    prepare_menu(rt)
    confirm(rt)
    assert rt.frozen and rt.test.paused[-1] is True
    before = len(rt.test.board.menus)
    lock(rt, object="cell phone", region="body")
    assert len(rt.test.board.menus) == before
    rt.test.board.emit(**home(samples=rt.snapshot["samples"] + 25, revision=rt.snapshot["revision"] + 1,
                              keyboard_session=rt.keyboard_session, keyboard_sequence=rt.keyboard_sequence,
                              keyboard_connected=1))
    rt.tick(0)
    assert not rt.frozen and rt.test.paused[-1] is False and rt.vision is None


def test_only_observed_emg_confirmation_with_board_progress_becomes_eligible(rt):
    prepare_menu(rt)
    confirm(rt)
    interaction = rt.pending_selection
    assert interaction is not None
    assert rt.store.get_selection(interaction)["status"] == "pending"
    rt.test.clock.now += 2
    rt.tick(2)
    assert rt.store.get_selection(interaction)["status"] == "pending"
    rt.test.board.emit(samples=rt.snapshot["samples"] + 500, progress=0.3)
    rt.tick(0)
    assert rt.store.get_selection(interaction)["status"] == "accepted"
    assert sum(rt.store.counts("P01", "cup").values()) == 1


def test_late_keyboard_use_revokes_an_eligible_emg_preference(rt):
    prepare_menu(rt)
    confirm(rt)
    interaction = rt.pending_selection
    rt.test.board.emit(samples=rt.snapshot["samples"] + 500, progress=0.3)
    rt.tick(0)
    rt.key("d", True)
    rt.tick(0)
    assert rt.store.get_selection(interaction)["status"] == "cancelled"
    assert rt.store.counts("P01", "cup") == {}


@pytest.mark.parametrize("delta,source", [(2, "device"), (1, "keyboard"), (1, "both")])
def test_ambiguous_or_keyboard_confirmations_do_not_train_emg_preferences(rt, delta, source):
    prepare_menu(rt)
    confirm(rt, source=source, delta=delta)
    assert rt.store.history() == []


def test_early_he_cancels_pending_learning(rt):
    prepare_menu(rt)
    confirm(rt)
    interaction = rt.pending_selection
    rt.test.board.emit(state="OPENING", returning=1, gesture="HE",
                       gesture_seq=rt.snapshot["gesture_seq"] + 1, progress=0.02)
    rt.tick(0)
    assert rt.store.get_selection(interaction)["status"] == "cancelled"


def test_stale_link_cancels_pending_learning_and_does_not_send_keys(rt):
    prepare_menu(rt)
    confirm(rt)
    interaction = rt.pending_selection
    rt.test.board.fresh = False
    before = len(rt.test.board.sent)
    rt.key("a", True)
    rt.tick(1)
    assert len(rt.test.board.sent) == before
    assert rt.keyboard_mask == 0
    assert rt.store.get_selection(interaction)["status"] == "cancelled"


def test_browser_heartbeat_does_not_replay_held_keys_after_reconnect(rt):
    prepare_menu(rt)
    rt.key("a", True)
    rt.tick(0)
    assert rt.keyboard_mask == 2
    rt.test.board.fresh = False
    rt.tick(0)
    rt.test.board.fresh = True
    rt.test.board.connections += 1
    rt.test.board.emit(keyboard_connected=0, keyboard_mask=0)
    rt.keyboard_state(["a"])
    rt.tick(0)
    assert rt.keyboard_mask == 0 and rt.test.board.keys[-1].strip().endswith(" 1 0")
    assert rt.vision is None
    ready(rt)
    rt.keyboard_state(["a"])
    rt.tick(0)
    assert rt.keyboard_mask == 0


def test_browser_lease_releases_keys_without_another_keyup(rt):
    ready(rt)
    rt.key("a", True)
    rt.tick(0)
    rt.test.clock.now += 0.36
    rt.tick(0)
    assert rt.keyboard_mask == 0
    assert rt.test.board.keys[-1].strip().endswith(" 0")


def test_handshake_retries_sequence_one_until_the_board_echoes_it(rt):
    rt.test.clock.now += 0.2
    rt.tick(0)
    assert rt.test.board.keys[-1] == "K 7 1 1 0\n"
    ready(rt)
    assert rt.keyboard_session == 1


def test_menu_id_collision_with_existing_board_menu_is_avoided(rt):
    ready(rt)
    rt.test.board.emit(state="ADAPTIVE", loaded=1, menu_id=1, adaptive=[1, 0, 0, 0],
                       adaptive_count=1, full=[1, 2, 3, 4], full_count=4)
    rt.tick(0)
    assert rt.test.hub.latest("menu")["context"]["object"] is None
    lock(rt)
    assert rt.pending[0].proposal.menu_id != 1


def test_unknown_existing_actuation_keeps_actual_grip_and_no_invented_menu_origin(rt):
    rt.test.board.emit(state="HOLDING", loaded=1, menu_id=77, active=1, progress=0.3,
                       menu_ready=0, adaptive=[1, 2, 0, 0], adaptive_count=2,
                       full=[1, 2, 3, 4], full_count=4)
    rt.tick(0)
    state = rt.test.hub.latest("fsm")
    assert state["active_grip"] == "POWER" and state["grip_progress"] == 0.3
    assert state["menu_kind"] is None and rt.store.history() == []


def test_full_menu_and_selection_survive_confidence_refresh(rt):
    prepare_menu(rt)
    rt.test.board.emit(state="FULL", selected=2, gesture="LE", gesture_seq=1, revision=9)
    rt.tick(0)
    lock(rt, confidence=0.5)
    assert int(rt.test.board.menus[-1].split()[4]) & 2
    values = list(map(int, rt.test.board.menus[-1].split()[1:]))
    rt.test.board.emit(menu_id=values[2], revision=10, adaptive=values[5:9], adaptive_count=values[4],
                       full=values[10:14], full_count=values[9])
    rt.tick(0)
    assert rt.test.hub.latest("fsm")["menu_kind"] == "FULL"
    assert rt.test.hub.latest("fsm")["selected_index"] == 2


def test_old_or_unstable_vision_does_not_replace_a_menu(rt):
    prepare_menu(rt)
    count = len(rt.test.board.menus)
    for result in [dict(ts=rt.resume_after, state="LOCKED", stable=True),
                   dict(ts=rt.clock(), state="LOST", stable=False)]:
        rt.receive_vision(result)
        rt.tick(0)
    assert len(rt.test.board.menus) == count


def test_calibration_controls_are_whitelisted_and_require_home(rt):
    ready(rt)
    rt.control({"action": "device_setup", "enabled": True})
    rt.tick(0)
    assert "x\n" in rt.test.board.sent
    rt.control({"action": "device_command", "command": "r"})
    rt.tick(0)
    assert "r\n" in rt.test.board.sent
    before = len(rt.test.board.sent)
    rt.control({"action": "device_command", "command": "m"})
    rt.tick(0)
    assert len(rt.test.board.sent) == before
    lock(rt)
    assert rt.test.board.menus == []  # Vision cannot leave HOME during calibration.
    rt.control({"action": "device_setup", "enabled": False})
    rt.tick(0)
    lock(rt)
    acknowledge(rt)
    before = len(rt.test.board.sent)
    rt.control({"action": "device_command", "command": "x"})
    rt.tick(0)
    assert len(rt.test.board.sent) == before


@pytest.mark.parametrize("timeout", [0, -1, float("nan")])
def test_invalid_vision_timeout_is_rejected(timeout):
    hub = Hub()
    with pytest.raises(ValueError):
        DeviceDashboardRuntime(hub, Session(hub.publish), device=Board(), db=":memory:", result_timeout=timeout)


def test_keyboard_navigation_after_completed_emg_return_keeps_previous_preference(rt):
    prepare_menu(rt)
    confirm(rt)
    interaction = rt.pending_selection
    rt.test.board.emit(samples=rt.snapshot["samples"] + 500, progress=0.3)
    rt.tick(0)
    rt.test.board.emit(state="FULL", active=-1, selected=0, progress=0, menu_ready=1,
                       gesture="HE", gesture_seq=rt.snapshot["gesture_seq"] + 1)
    rt.tick(0)
    rt.key("s", True)
    rt.tick(0)
    assert rt.store.get_selection(interaction)["status"] == "accepted"
    assert sum(rt.store.counts("P01", "cup").values()) == 1


def test_calibration_setup_from_menu_waits_for_home_and_fresh_vision(rt):
    prepare_menu(rt)
    rt.control({"action": "device_setup", "enabled": True})
    rt.tick(0)
    assert rt.calibration_mode and "x\n" in rt.test.board.sent
    before = len(rt.test.board.sent)
    rt.control({"action": "device_command", "command": "r"})
    rt.tick(0)
    assert len(rt.test.board.sent) == before
    rt.test.board.emit(**{k: v for k, v in home(calibrated=0, armed=0).items()
                         if k not in {"samples", "keyboard_session", "keyboard_sequence"}})
    rt.tick(0)
    lock(rt)
    count = len(rt.test.board.menus)
    assert rt.calibration_mode
    rt.control({"action": "device_setup", "enabled": False})
    rt.tick(0)
    assert not rt.calibration_mode and len(rt.test.board.menus) == count
    ready(rt)
    lock(rt)
    assert len(rt.test.board.menus) > count


def test_calibration_reset_is_rejected_during_actuation_and_when_stale(rt):
    prepare_menu(rt)
    confirm(rt)
    rt.control({"action": "device_setup", "enabled": True})
    rt.tick(0)
    assert not rt.calibration_mode and "x\n" not in rt.test.board.sent
    rt.test.board.fresh = False
    rt.control({"action": "device_setup", "enabled": True})
    rt.tick(0)
    assert not rt.calibration_mode


def test_calibration_setup_needs_explicit_boolean_and_released_keys(rt):
    ready(rt)
    rt.control({"action": "device_setup", "enabled": "yes"})
    rt.tick(0)
    assert not rt.calibration_mode
    rt.key("a", True)
    rt.control({"action": "device_setup", "enabled": True})
    rt.tick(0)
    assert not rt.calibration_mode and "x\n" not in rt.test.board.sent


def test_board_mode_keeps_profiles_and_reports_rejected_controls(rt):
    ready(rt)
    assert rt.test.hub.latest("users")["users"][0]["user"] == "P01"
    rt.control({"action": "add_user", "user": " p07 "})
    rt.tick(0)
    assert [user["user"] for user in rt.test.hub.latest("users")["users"]] == ["P01", "P07"]
    rt.control({"action": "add_user", "user": "P07"})
    rt.tick(0)
    # Hub treats notices as transient events; audit proves the rejection.
    assert "already exists" in rt.test.audit.getvalue()
    rt.control({"action": "set_session", "participant": "P07", "condition": "C3_ADAPTIVE"})
    rt.tick(0)
    assert rt.session.state.participant == rt.test.hub.latest("users")["current"] == "P07"


def test_board_mode_keeps_rest_controls_and_audit_context(rt):
    rt.session._audit = lambda event, **data: rt.audit(event, **data)
    rt.control({"action": "start_rest"})
    rt.tick(0)
    assert rt.test.hub.latest("session")["rest_active"]
    rt.audit("observed", source="device")
    records = [json.loads(line) for line in rt.test.audit.getvalue().splitlines()]
    assert records[-1]["rest"] == 1
    rt.control({"action": "end_rest"})
    rt.tick(0)
    assert not rt.test.hub.latest("session")["rest_active"]


def test_board_mode_refreshes_user_counts_after_real_emg_learning(rt):
    prepare_menu(rt)
    confirm(rt)
    rt.test.board.emit(samples=rt.snapshot["samples"] + 500, progress=0.3)
    rt.tick(0)
    profile = rt.test.hub.latest("users")["users"][0]
    assert profile["selections"] == 1 and profile["accepted"] == 1
