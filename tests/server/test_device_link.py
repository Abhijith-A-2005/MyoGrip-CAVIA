"""Wire validation, freshness and command isolation without a physical board."""
from copy import deepcopy
import json
import queue
import threading
import time
from types import SimpleNamespace

import pytest

import cavia.server.device_link as device_link_module
from cavia.server.device_link import (
    DeviceLink, keyboard_line, menu_line, next_keyboard_session, parse_snapshot,
)


def snapshot(**changes):
    data = dict(v=1, wire=3, keyboard_wire=2, boot=7, revision=1, samples=0,
                keyboard_session=0, keyboard_sequence=0, keyboard_mask=0, keyboard_connected=0,
                rest=0, menu_ready=1, calibrated=0, armed=0, activity="UNCALIBRATED",
                gesture="NONE", gesture_source="device", gesture_seq=0, state="HOME", menu_id=0,
                loaded=0, selected=0, active=-1, progress=0, gate=0, returning=0,
                adaptive_count=0, adaptive=[0, 0, 0, 0], full_count=0, full=[0, 0, 0, 0])
    data.update(changes)
    return data


def frame(**changes):
    return "I (123) MYOGRIP_FSM: MGSTATE " + json.dumps(snapshot(**changes)) + "\x1b[0m\n"


def loaded(**changes):
    data = snapshot(state="ADAPTIVE", loaded=1, menu_id=42, adaptive_count=2,
                    adaptive=[4, 2, 0, 0], full_count=4, full=[1, 2, 3, 4])
    data.update(changes)
    return data


@pytest.mark.parametrize("data", [snapshot(), loaded(),
    loaded(state="CLOSING", active=4, progress=0.25, menu_ready=0),
    loaded(state="OPENING", active=4, progress=0.2, menu_ready=0, returning=1)])
def test_current_firmware_states_are_accepted(data):
    assert parse_snapshot("prefix MGSTATE " + json.dumps(data) + "\x1b[0m") == data


@pytest.mark.parametrize("change", [
    {"wire": 2}, {"keyboard_wire": 1}, {"v": True}, {"state": "FAKE"},
    {"boot": 0}, {"samples": -1}, {"samples": 2**32}, {"progress": float("nan")},
    {"progress": 1.1}, {"armed": True}, {"armed": 1}, {"selected": 4},
    {"active": 0}, {"loaded": 1}, {"returning": 1}, {"gate": 1},
    {"keyboard_mask": 2}, {"keyboard_connected": 1}, {"gesture_source": "unknown"},
    {"full": [0, 0, 0]}, {"full": [False, 0, 0, 0]}, {"full_count": 5},
    {"activity": []}, {"gesture": "LF_REPEAT"},
])
def test_invalid_or_incompatible_frames_are_rejected(change):
    assert parse_snapshot("MGSTATE " + json.dumps(snapshot(**change))) is None


def test_damaged_prefix_and_trailing_color_recover_without_repairing_bad_json():
    good = frame(samples=25)
    assert parse_snapshot("MGSTATE {broken " + good)["samples"] == 25
    assert parse_snapshot("MGSTATE {broken") is None
    assert parse_snapshot("MGSTATE [1, 2]") is None
    assert parse_snapshot(None) is None
    bad = loaded(adaptive=[4, 4, 0, 0])
    assert parse_snapshot("MGSTATE " + json.dumps(bad)) is None
    bad = loaded(adaptive=[4, 2, 0, 0], full=[1, 2, 3, 0], full_count=3)
    assert parse_snapshot("MGSTATE " + json.dumps(bad)) is None


def test_packet_builders_keep_menu_order_and_use_reported_boot_and_revision():
    proposal = SimpleNamespace(menu_id=42, items=[4, 2], full_menu=[1, 2, 3, 4],
                               policy=SimpleNamespace(value="TOP_TWO"))
    state = snapshot(revision=9, keyboard_session=8)
    assert menu_line(state, proposal, True) == "@ 7 9 42 2 2 4 2 0 0 4 1 2 3 4\n"
    proposal.policy.value = "FULL_MENU"
    assert menu_line(state, proposal).split()[4] == "1"
    assert next_keyboard_session(state) == 9
    assert keyboard_line(state, 9, 1, 0) == "K 7 9 1 0\n"
    proposal.items = [4, 4]
    with pytest.raises(ValueError):
        menu_line(state, proposal)
    for session, sequence, mask in [(0, 1, 0), (1, 0, 0), (1, 1, 32), (True, 1, 0)]:
        with pytest.raises(ValueError):
            keyboard_line(state, session, sequence, mask)
    with pytest.raises(ValueError):
        next_keyboard_session(snapshot(keyboard_session=0xFFFFFFFF))


class Clock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now


def fresh_link():
    clock = Clock()
    link = DeviceLink("test", clock=clock)
    link.connected = True
    link._accept(snapshot())
    assert link.status()["status"] == "stale"
    clock.now += 0.1
    link._accept(snapshot(samples=25))
    assert link.status()["status"] == "connected"
    return link, clock


def test_duplicate_arrival_cannot_hide_a_frozen_sample_counter():
    link, clock = fresh_link()
    clock.now += 1.6
    link._accept(snapshot(samples=25))
    assert link.status()["status"] == "stale"
    with pytest.raises(ValueError, match="fresh"):
        link.send("x")


def test_backwards_counter_is_discarded_and_real_uint32_wrap_advances():
    link, clock = fresh_link()
    clock.now += 1.6
    link._accept(snapshot(samples=0))
    link._accept(snapshot(samples=25))
    assert link.last["samples"] == 25 and link.status()["status"] == "stale"
    assert link.status()["discarded_frames"] == 1
    wrapped = DeviceLink("test", clock=clock)
    wrapped.connected = True
    wrapped._accept(snapshot(samples=0xFFFFFFFE))
    wrapped._accept(snapshot(samples=2))
    assert wrapped.status()["status"] == "connected"


class Sink:
    def __init__(self):
        self.writes = []

    def write(self, value):
        self.writes.append(value)
        return len(value)


def test_boot_change_discards_pending_commands_and_waits_for_new_sample_progress():
    link, clock = fresh_link()
    link.send("x")
    stale = link.commands.get_nowait()
    link._accept(snapshot(boot=8))
    assert link.commands.empty() and link.status()["status"] == "stale"
    link._accept(snapshot(boot=8, samples=25))
    link.commands.put_nowait(stale)  # Simulate an enqueue racing with reset.
    sink = Sink()
    link._write_next(sink)
    assert sink.writes == []
    with pytest.raises(ValueError, match="old board boot"):
        link.send("K 7 1 1 0\n")
    assert all(packet["boot"] == 8 for packet in link.drain())


def test_command_deadline_and_stale_link_drop_commands_instead_of_replaying():
    link, clock = fresh_link()
    sink = Sink()
    link.send("K 7 1 1 0\n")
    clock.now += 0.26
    link._write_next(sink)
    assert sink.writes == []
    link.send("K 7 1 2 0\n")
    link._write_next(sink)
    assert sink.writes == [b"K 7 1 2 0\n"]
    link.send("x")
    clock.now += 2
    link._write_next(sink)
    assert len(sink.writes) == 1


def test_invalid_commands_and_full_queue_are_reported():
    link, _ = fresh_link()
    for line in ["", "K 7 1 1 0\nx", "unknown", "@ 7", "K 7 1 -1 0", "K 7 1 1 4294967296", "é"]:
        with pytest.raises(ValueError):
            link.send(line)
    for _ in range(8):
        link.send("?")
    with pytest.raises(ValueError, match="queue is full"):
        link.send("?")


class FakeSerial(Sink):
    def __init__(self, chunks, hold_idle=False, require_control_release=False):
        super().__init__()
        self.chunks = queue.Queue()
        for chunk in chunks:
            self.chunks.put(chunk)
        self.hold_idle = hold_idle
        self.require_control_release = require_control_release
        self.controls = []
        self.opened = False
        self._dtr = self._rts = None
        self.waiting = threading.Event()
        self.release_idle = threading.Event()
        self.closed = False

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, value):
        self.controls.append((self.opened, "dtr", value))
        self._dtr = value

    @property
    def rts(self):
        return self._rts

    @rts.setter
    def rts(self, value):
        self.controls.append((self.opened, "rts", value))
        self._rts = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        self.opened = False

    def open(self):
        assert self.port == "test" and self.dtr is False and self.rts is False
        self.opened = True

    @property
    def in_waiting(self):
        return 1

    def read(self, count):
        if self.require_control_release and self.controls[-2:] != [
                (True, "rts", False), (True, "dtr", False)]:
            time.sleep(0.01)
            return b""
        if self.chunks.empty() and self.hold_idle:
            self.waiting.set()
            self.release_idle.wait(2)
        try:
            value = self.chunks.get(timeout=0.02)
        except queue.Empty:
            return b""
        if isinstance(value, Exception):
            raise value
        return value


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Serial worker did not reach expected state")
        time.sleep(0.005)


def test_fragmented_lines_reconnect_and_no_queued_command_replay():
    raw = frame().encode()
    first = FakeSerial([b"MGSTATE {broken\n", raw[:23], raw[23:], frame(samples=25).encode()], True)
    second = FakeSerial([frame(boot=8).encode(), frame(boot=8, samples=25).encode()])
    devices = iter([first, second])
    link = DeviceLink("test", serial_factory=lambda **kwargs: next(devices))
    try:
        link.start()
        link.start()  # Idempotent while the worker is alive.
        wait_for(lambda: link.status()["status"] == "connected" and first.waiting.is_set())
        link.send("K 7 1 1 0\n")
        first.chunks.put(OSError("unplugged"))
        first.release_idle.set()
        wait_for(lambda: link.status()["connections"] == 2 and link.status()["status"] == "connected")
        assert first.closed and first.writes == [] and second.writes == []
        assert link.status()["discarded_frames"] == 1
        assert all(packet["boot"] == 8 for packet in link.drain())
        link.send("K 8 1 1 0\n")
        wait_for(lambda: second.writes == [b"K 8 1 1 0\n"])
    finally:
        first.release_idle.set()
        link.close()
    assert second.closed and link.status()["status"] == "disconnected"


def test_windows_port_reapplies_released_control_lines_after_open(monkeypatch):
    monkeypatch.setattr(device_link_module, "_WINDOWS_SERIAL", True)
    device = FakeSerial([frame().encode(), frame(samples=25).encode()],
                        require_control_release=True)
    link = DeviceLink("test", serial_factory=lambda **kwargs: device)
    try:
        link.start()
        wait_for(lambda: link.status()["status"] == "connected")
        assert device.controls == [(False, "dtr", False), (False, "rts", False),
                                   (True, "rts", False), (True, "dtr", False)]
        assert link.status()["bytes_received"] > 0
        assert link.status()["lines_received"] == 2
        assert "MGSTATE " in link.last_serial_line
    finally:
        link.close()
