"""An absent or rebooted board must never disable the vision/keyboard dashboard."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from cavia.server.combined_runtime import CombinedDashboardRuntime
from cavia.server.hub import Hub
from cavia.server.session import Session
from cavia.server.__main__ import offline_system, runtime_system
from test_device_runtime import Board, Clock, home


@pytest.fixture
def rt():
    hub, board, clock, paused = Hub(), Board(), Clock(), []
    board.fresh = False
    session = Session(hub.publish)
    runtime = CombinedDashboardRuntime(hub, session, db=":memory:", device=board,
                                       clock=clock, detection_control=paused.append)
    runtime.test = SimpleNamespace(hub=hub, board=board, clock=clock, paused=paused)
    runtime.open()
    runtime.tick(0)
    yield runtime
    runtime.close()


def tick(rt, dt=0.1):
    rt.test.clock.now += dt
    rt.tick(dt)


def lock(rt):
    rt.test.clock.now += 0.1
    rt.receive_vision(dict(ts=rt.clock(), state="LOCKED", stable=True,
                           object="cup", region="handle", region_confidence=0.9))
    rt.tick(0)


def connect(rt, boot=7):
    board = rt.test.board
    board.fresh = True
    board.emit(**home(boot=boot, samples=board.packet["samples"] + 25))
    tick(rt)
    session, sequence = map(int, board.keys[-1].split()[2:4])
    board.emit(keyboard_session=session, keyboard_sequence=sequence, keyboard_connected=1)
    tick(rt)
    assert rt.owner == "firmware"


def ack_menu(rt):
    p = list(map(int, rt.test.board.menus[-1].split()[1:]))
    rt.test.board.emit(menu_id=p[2], revision=rt.firmware.snapshot["revision"] + 1,
        loaded=1, state="ADAPTIVE" if p[4] else "FULL", adaptive_count=p[4],
        adaptive=p[5:9], full_count=p[9], full=p[10:14])
    tick(rt)


def test_missing_firmware_still_generates_menu_and_runs_keyboard(rt):
    lock(rt)
    assert rt.hub.latest("menu")["context"]["object"] == "cup"
    assert rt.hub.latest("fsm")["state"] == "ADAPTIVE"
    rt.key("a", True)
    tick(rt)
    assert rt.hub.latest("fsm")["state"] == "CLOSING"
    assert rt.hub.latest("fsm")["grip_progress"] > 0
    assert rt.test.board.sent == []
    assert rt.status()["controller"] == "keyboard"


def test_original_no_port_keyboard_mode_uses_the_existing_database(tmp_path):
    hub, clock = Hub(), Clock()
    db = tmp_path / "original.sqlite3"
    runtime = CombinedDashboardRuntime(hub, Session(hub.publish), db=db, clock=clock)
    runtime.open()
    try:
        clock.now += 0.1
        runtime.receive_vision(dict(ts=clock(), state="LOCKED", stable=True,
                                   object="bottle", region="unknown", region_confidence=0.79))
        runtime.tick(0)
        assert hub.latest("menu") and hub.latest("fsm")["state"] == "ADAPTIVE"
        assert runtime.history_db == db
        assert not runtime.status()["device_configured"]
    finally:
        runtime.close()


def test_firmware_view_uses_exact_acknowledgement_and_actual_progress(rt):
    connect(rt)
    lock(rt)
    assert rt.hub.latest("menu") is None
    assert rt.test.board.menus
    ack_menu(rt)
    packet = rt.test.board.packet
    rt.test.board.emit(state="CLOSING", active=packet["adaptive"][0], progress=0.24, menu_ready=0)
    tick(rt)
    assert rt.hub.latest("fsm")["grip_progress"] == 0.24
    tick(rt, 0.8)
    assert rt.hub.latest("fsm")["grip_progress"] == 0.24


def test_real_gesture_events_keep_their_audit_payload_during_handover(rt):
    connect(rt)
    lock(rt)
    ack_menu(rt)
    rt.test.board.emit(gesture="SF", gesture_source="keyboard", gesture_seq=1, selected=1)
    tick(rt)
    assert rt.owner == "firmware"
    assert rt.hub.latest("fsm")["selected_index"] == 1
    assert rt.status()["fallback_reason"] == ""


def test_disconnect_unpauses_vision_and_new_locks_load_offline(rt):
    connect(rt)
    lock(rt)
    ack_menu(rt)
    rt.test.board.emit(state="CLOSING", active=rt.test.board.packet["adaptive"][0],
                       progress=0.2, menu_ready=0)
    tick(rt)
    assert rt.test.paused[-1] is True
    rt.test.board.fresh = False
    tick(rt)
    assert rt.owner == "keyboard" and rt.test.paused[-1] is False
    lock(rt)
    assert rt.hub.latest("menu") and rt.hub.latest("fsm")["state"] == "ADAPTIVE"


def test_offline_grip_and_held_key_are_not_replayed_on_reconnect(rt):
    lock(rt)
    rt.key("a", True)
    tick(rt)
    assert rt.hub.latest("fsm")["state"] == "CLOSING"
    connect(rt)
    assert rt.hub.latest("fsm")["state"] == "HOME"
    assert rt.hub.latest("fsm")["grip_progress"] == 0
    assert rt.firmware.keyboard_mask == 0
    rt.keyboard_state(["a"])
    rt.key("a", True)  # Repeated down from a still-held key is blocked.
    tick(rt)
    assert rt.firmware.keyboard_mask == 0
    rt.key("a", False)
    tick(rt)
    rt.key("a", True)
    tick(rt)
    assert rt.firmware.keyboard_mask == 2


def test_a_queued_press_from_before_handover_is_dropped(rt):
    board = rt.test.board
    board.fresh = True
    tick(rt)
    session, sequence = map(int, board.keys[-1].split()[2:4])
    board.emit(keyboard_session=session, keyboard_sequence=sequence, keyboard_connected=1)
    rt.key("a", True)
    tick(rt)
    assert rt.owner == "firmware" and rt.firmware.keyboard_mask == 0


def test_firmware_errors_cannot_stop_offline_menu_generation(rt, monkeypatch):
    def fail(dt):
        raise ValueError("serial queue is unavailable")
    monkeypatch.setattr(rt.firmware, "tick", fail)
    lock(rt)
    assert rt.hub.latest("menu") and rt.owner == "keyboard"
    assert "queue" in rt.status()["fallback_reason"]


def test_boot_change_requires_a_new_released_handshake(rt):
    connect(rt)
    rt.key("a", True)
    tick(rt)
    rt.test.board.emit(**home(boot=8, samples=10))
    tick(rt)
    assert rt.owner == "keyboard" and rt.firmware.keyboard_mask == 0
    session, sequence = map(int, rt.test.board.keys[-1].split()[2:4])
    rt.test.board.emit(keyboard_session=session, keyboard_sequence=sequence, keyboard_connected=1)
    tick(rt)
    assert rt.owner == "firmware" and rt.firmware.keyboard_mask == 0


def test_firmware_does_not_receive_menus_before_takeover(rt):
    lock(rt)
    rt.test.board.fresh = True
    tick(rt)
    assert rt.owner == "keyboard" and rt.test.board.menus == []


def test_profiles_and_rest_controls_survive_controller_changes(rt):
    rt.control({"action": "add_user", "user": "P07"})
    tick(rt)
    assert "P07" in {p["user"] for p in rt.firmware.store.users()}
    rt.control({"action": "set_session", "participant": "P07", "condition": "C3_ADAPTIVE"})
    tick(rt)
    assert rt.session.state.participant == "P07"
    connect(rt)
    assert rt.hub.latest("users")["current"] == "P07"
    rt.control({"action": "start_rest"})
    tick(rt)
    assert rt.hub.latest("session")["rest_active"]
    rt.test.board.fresh = False
    tick(rt)
    rt.control({"action": "end_rest"})
    tick(rt)
    assert not rt.hub.latest("session")["rest_active"]


def test_keyboard_preferences_do_not_train_the_firmware_database(rt):
    lock(rt)
    rt.key("a", True)
    tick(rt)
    for _ in range(22):
        rt.keyboard_state(["a"])
        tick(rt)
    assert rt.keyboard._store.counts("P01", "cup")
    assert rt.firmware.store.counts("P01", "cup") == {}


def test_keyboard_watchdog_still_releases_after_browser_loss(rt):
    lock(rt)
    rt.key("a", True)
    tick(rt)
    tick(rt, 0.5)
    assert rt.hub.latest("fsm")["state"] == "HOLDING"
    rt.keyboard_state(["a"])
    tick(rt)
    assert rt.hub.latest("fsm")["state"] == "HOLDING"


def test_calibration_commands_are_not_forwarded_while_offline(rt):
    rt.control({"action": "device_setup", "enabled": True})
    tick(rt)
    assert not rt.firmware.calibration_mode and rt.test.board.sent == []


def test_live_status_describes_the_active_controller_even_if_usb_is_stale(rt):
    result = runtime_system(offline_system(), rt, rt.test.board)
    assert result["controller"] == "keyboard" and result["hand_link"]["status"] == "stale"
    connect(rt)
    assert runtime_system(offline_system(), rt, rt.test.board)["controller"] == "firmware"
