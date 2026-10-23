"""Live menu, retained-context and confirmation regression tests."""

import json
from pathlib import Path
import select
import socket
import time

import pytest

from cavia.arbitration.engine import ArbitrationEngine
from cavia.arbitration.preferences import PreferenceStore
from cavia.core.contracts import FsmState, Grip, MenuPolicy
from cavia.runtime.controller import LiveSimApp
from cavia.runtime.vision_link import VisionProcess, decode_result


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def live():
    with PreferenceStore(":memory:") as store:
        clock = Clock()
        app = LiveSimApp(ArbitrationEngine(store), clock=clock)
        yield app, store, clock


def feed(
    live,
    obj="cup",
    region="handle",
    confidence=0.9,
    state="LOCKED",
    render=True,
):
    app, _, clock = live
    clock.now += 0.01

    packet = dict(
        ts=clock.now,
        object=obj,
        region=region,
        region_confidence=confidence,
        state=state,
        stable=state == "LOCKED",
    )

    app.receive(packet)

    if render:
        app.mark_rendered()

    return packet


def tap(app, key):
    app.key_down(key)
    app.key_up(key)


def return_to_full(app):
    tap(app, "e")

    for _ in range(30):
        app.step(0.1)

    assert app.fsm.state is FsmState.FULL
    app.mark_rendered()


def test_startup_waits_and_vision_changes_menu_even_after_navigation(live):
    app, store, _ = live
    assert app.fsm.state is FsmState.HOME

    feed(live)
    assert app.fsm.current_items() == [Grip.LATERAL, Grip.PINCH]

    tap(app, "s")
    assert app.fsm.selected_grip() is Grip.PINCH

    feed(live, region="body")
    assert app.fsm.current_items() == [Grip.POWER, Grip.LATERAL]
    assert not app.frozen and not store.history()


def test_unchanged_frames_do_not_reset_navigation_or_write_menus(live):
    app, store, _ = live
    feed(live)

    original = app.fsm.menu_id
    tap(app, "s")

    for confidence in (0.91, 0.93, 0.86, 0.99):
        feed(live, confidence=confidence)

    assert app.fsm.menu_id == original
    assert app.fsm.selected_grip() is Grip.PINCH
    assert store.connection.execute(
        "SELECT COUNT(*) FROM menus"
    ).fetchone()[0] == 1


@pytest.mark.parametrize("region", [None, "unknown"])
def test_unresolved_region_of_same_object_keeps_last_region_menu(live, region):
    app, store, _ = live
    feed(live)

    original = app.fsm.menu_id
    tap(app, "s")
    feed(live, region=region)

    assert app.fsm.menu_id == original
    assert app.fsm.selected_grip() is Grip.PINCH
    assert app.request.region == "handle"
    assert "region not resolved" in app.vision_status
    assert store.connection.execute(
        "SELECT COUNT(*) FROM menus"
    ).fetchone()[0] == 1

    feed(live, region="body")
    assert app.request.region == "body"
    assert app.fsm.menu_id != original


def test_unknown_region_is_allowed_for_first_lock_and_different_object(live):
    app, _, _ = live

    feed(live, region="unknown")
    assert app.request.object == "cup"
    assert app.request.region == "unknown"

    feed(live, region="handle")
    original = app.fsm.menu_id

    feed(live, obj="bottle", region=None)
    assert app.request.object == "bottle"
    assert app.request.region == "unknown"
    assert app.fsm.menu_id != original


def test_confidence_policy_updates_and_preserves_selected_grip_if_present(live):
    app, _, _ = live
    engine = app.engine

    for i in range(8):
        decision = engine.propose(
            dict(
                user=1,
                object="cup",
                region="handle",
                vision_confidence=0.9,
            )
        )
        engine.confirm(
            decision.proposal.menu_id,
            Grip.PINCH,
            f"seed-{i}",
        )
        engine.finish(f"seed-{i}", "accepted")

    feed(live, confidence=0.7)
    assert app.decision.proposal.policy is MenuPolicy.TOP_TWO
    assert app.fsm.selected_grip() is Grip.PINCH

    feed(live, confidence=0.85)
    assert app.decision.proposal.policy is MenuPolicy.ONE_CONFIRM
    assert app.fsm.selected_grip() is Grip.PINCH
    assert not app.frozen


def test_new_menu_must_be_rendered_before_confirm(live):
    app, store, _ = live

    feed(live)
    feed(live, obj="bottle", region="body", render=False)

    app.key_down("a")
    app.step(0.1)

    assert app.fsm.state is FsmState.ADAPTIVE
    assert app.fsm.progress == 0
    assert not store.history()

    app.mark_rendered()
    app.key_down("a")
    assert not app.frozen

    app.key_up("a")
    tap(app, "a")

    assert app.frozen
    assert app.fsm.active_grip is Grip.POWER


def test_freeze_survives_actuation_full_and_reconfirmation_until_home(live):
    app, store, _ = live
    feed(live)

    menu_id = app.fsm.menu_id
    tap(app, "a")

    feed(live, obj="bottle", region="cap")
    app.check_source(exited=True)

    assert app.fsm.menu_id == menu_id
    assert app.request.object == "cup"

    return_to_full(app)
    feed(live, obj="book", region="cover_face")

    assert app.frozen
    assert app.fsm.menu_id == menu_id

    tap(app, "a")
    assert app.fsm.active_grip is Grip.POWER
    assert store.history()[-1]["object"] == "cup"
    assert store.history()[-1]["compatible"] == 0

    return_to_full(app)
    old = feed(live, obj="bottle", region="cap")

    tap(app, "e")
    assert app.fsm.state is FsmState.HOME
    assert not app.frozen

    app.receive(old)
    assert app.fsm.state is FsmState.HOME

    feed(live, obj="bottle", region="cap")
    assert app.request.object == "bottle"
    assert app.fsm.menu_id != menu_id


def test_history_uses_confirmed_snapshot_once_and_never_claims_success(live):
    app, store, _ = live
    feed(live)
    tap(app, "s")

    app.key_down("a")
    feed(live, obj="bottle", region="body")

    for _ in range(30):
        app.step(0.1)

    app.key_up("a")

    assert len(store.history()) == 1

    row = store.history()[0]
    assert (row["object"], row["region"], row["grip"]) == (
        "cup",
        "handle",
        "PINCH",
    )
    assert row["status"] == "accepted"
    assert row["grasp_success"] is None
    assert store.counts(1, "cup") == {"PINCH": 1}
    assert store.counts(2, "cup") == {}


@pytest.mark.parametrize("state", ["NO_OBJECT", "SEARCHING", "LOST"])
def test_loss_retains_last_menu_selection_and_allows_confirmation(live, state):
    app, store, _ = live
    feed(live)
    tap(app, "s")

    menu_id = app.fsm.menu_id
    feed(live, state=state)

    assert app.fsm.menu_id == menu_id
    assert app.fsm.selected_grip() is Grip.PINCH
    assert "LAST LOCK" in app.vision_status

    tap(app, "a")

    assert app.frozen
    assert app.fsm.active_grip is Grip.PINCH
    assert store.history()[0]["region"] == "handle"


def test_timeout_and_child_exit_preserve_the_last_menu(live):
    app, _, clock = live
    feed(live)
    original = app.fsm.menu_id

    clock.now += 3
    app.check_source()

    assert app.fsm.state is FsmState.ADAPTIVE
    assert app.fsm.menu_id == original

    feed(live)
    app.check_source(exited=True)

    assert app.fsm.state is FsmState.ADAPTIVE
    assert app.fsm.menu_id == original

    feed(live)
    tap(app, "a")

    clock.now += 3
    app.check_source(exited=True)

    assert app.frozen
    assert app.fsm.state is FsmState.HOLDING


def test_home_waits_for_release_and_a_fresh_unchanged_lock(live):
    app, _, _ = live
    feed(live)

    app.key_down("e")
    feed(live)
    assert app.fsm.state is FsmState.HOME

    app.key_up("e")
    feed(live)
    assert app.fsm.state is FsmState.ADAPTIVE


def test_manual_full_survives_live_target_change_until_confirmation(live):
    app, store, _ = live

    feed(live)
    tap(app, "d")
    feed(live, obj="bottle", region="body")

    assert app.fsm.state is FsmState.FULL
    assert app.fsm.current_items() == list(app.engine.available)

    tap(app, "a")
    assert store.history()[0]["object"] == "bottle"


def test_unknown_region_uses_object_candidates(live):
    app, _, _ = live
    feed(live, region=None)

    assert app.request.region == "unknown"
    assert app.fsm.current_items() == [
        Grip.POWER,
        Grip.LATERAL,
        Grip.PINCH,
    ]


def test_user_changes_only_before_confirmation(live):
    app, store, _ = live
    app.set_user(1)
    feed(live)
    assert app.decision.user == "1"

    app.set_user(2)                     # an unconfirmed menu is cleared
    assert app.decision is None
    assert app.fsm.state is FsmState.HOME
    feed(live)
    assert app.decision.user == "2"

    tap(app, "a")
    with pytest.raises(ValueError):
        app.set_user(1)
    assert store.history()[0]["user"] == "2"


def test_ambiguous_keys_do_not_confirm_or_freeze(live):
    app, store, _ = live
    feed(live)

    app.key_down("s")
    app.key_down("a")

    assert app.fsm.state is FsmState.ADAPTIVE
    assert not app.frozen
    assert not store.history()


@pytest.mark.parametrize(
    "changes",
    [
        {"ts": float("nan")},
        {"ts": 101.0},
        {"region_confidence": float("inf")},
        {"region_confidence": -0.1},
        {"region_confidence": True},
        {"stable": "true"},
        {"state": "LOST"},
        {"object": None},
        {"region": 4},
    ],
)
def test_transport_rejects_invalid_fields(changes):
    packet = dict(
        ts=99.0,
        state="LOCKED",
        stable=True,
        object="cup",
        region="handle",
        region_confidence=0.9,
    )
    packet.update(changes)

    assert decode_result(json.dumps(packet).encode(), 100.0) is None


def test_transport_rejects_invalid_json():
    for raw in [b"[]", b"not json", b"{}", b'"hello"', b"\xff"]:
        assert decode_result(raw, 100.0) is None


def test_udp_keeps_newest_and_discards_out_of_order(tmp_path):
    vision = VisionProcess(tmp_path / "unused.py")
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        now = time.monotonic()

        for stamp, region in [
            (now - 2, "body"),
            (now - 1, "handle"),
            (now - 3, "body"),
        ]:
            sender.sendto(
                json.dumps(
                    dict(
                        ts=stamp,
                        state="LOCKED",
                        stable=True,
                        object="cup",
                        region=region,
                        region_confidence=0.9,
                    )
                ).encode(),
                vision.sock.getsockname(),
            )

        assert vision.latest()["region"] == "handle"
        assert vision.latest() is None

    finally:
        sender.close()
        vision.close()


def test_real_child_publishes_and_is_stopped_by_launcher(tmp_path, monkeypatch):
    src = Path(__file__).resolve().parents[2] / "src"
    monkeypatch.setenv("PYTHONPATH", str(src))

    script = tmp_path / "fake_vision.py"
    script.write_text(
        "from cavia.runtime.vision_link import publish_result\n"
        "import threading\n"
        "publish_result(dict(state='LOCKED', stable=True, "
        "object='cup', region='handle', region_confidence=.9))\n"
        "threading.Event().wait(30)\n"
    )

    vision = VisionProcess(script)

    try:
        vision.start()

        assert select.select([vision.sock], [], [], 3)[0]
        assert vision.latest()["object"] == "cup"
        assert not vision.exited

    finally:
        vision.close()

    assert vision.exited