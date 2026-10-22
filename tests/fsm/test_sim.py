"""Keyboard scenarios through the simulator logic (no window needed)."""

import pytest

from cavia.core.config import FsmConfig
from cavia.core.contracts import FsmState, Grip, MenuPolicy
from keyboard_sim.fsm.machine import MyoGripFsm
from keyboard_sim.fsm.sim import SimApp, parse_grips


@pytest.fixture
def app():
    fsm = MyoGripFsm(FsmConfig(close_speed=0.5, open_speed=0.5, he_return_speed=1.0))
    return SimApp(fsm, [Grip.LATERAL, Grip.PINCH, Grip.POWER], MenuPolicy.TOP_TWO)


def tap(app, key):
    app.key_down(key)
    app.step(0.0)
    app.key_up(key)
    app.step(0.0)


def hold(app, key, seconds, dt=0.05):
    app.key_down(key)
    for _ in range(round(seconds / dt)):
        app.step(dt)


def release(app, key):
    app.key_up(key)
    app.step(0.0)


def test_vertical_navigation(app):
    assert app.fsm.state is FsmState.ADAPTIVE
    tap(app, "s")
    assert app.fsm.selected == 1
    tap(app, "s")
    tap(app, "s")
    assert app.fsm.selected == 0          # wraps past the bottom
    tap(app, "w")
    assert app.fsm.selected == 2          # wraps past the top


def test_holding_s_moves_only_once(app):
    hold(app, "s", 2.0)
    app.key_down("s")                     # OS auto-repeat
    assert app.fsm.selected == 1


def test_one_press_of_a_confirms_and_closes(app):
    tap(app, "s")
    hold(app, "a", 1.0)                   # the confirming press keeps closing
    assert app.fsm.state is FsmState.CLOSING
    assert app.fsm.active_grip is Grip.PINCH
    assert app.fsm.progress == pytest.approx(0.5)
    release(app, "a")
    assert app.fsm.state is FsmState.HOLDING
    assert app.fsm.progress == pytest.approx(0.5)


def test_quick_tap_of_a_confirms_without_moving(app):
    tap(app, "a")
    assert app.fsm.state is FsmState.HOLDING
    assert app.fsm.progress == 0.0


def test_full_open_stays_in_grip_and_can_close_again(app):
    hold(app, "a", 2.0)
    release(app, "a")
    assert app.fsm.progress == 1.0
    hold(app, "d", 3.0)                   # fully open while D still held
    assert app.fsm.state is FsmState.OPENING and app.fsm.progress == 0.0
    release(app, "d")
    assert app.fsm.state is FsmState.HOLDING and app.fsm.active_grip is Grip.LATERAL

    hold(app, "a", 1.0)                   # second cycle with the same grip
    assert app.fsm.state is FsmState.CLOSING and app.fsm.progress == pytest.approx(0.5)
    release(app, "a")

    tap(app, "e")                         # only HE leaves the grip
    for _ in range(20):
        app.step(0.05)
    assert app.fsm.state is FsmState.FULL and app.fsm.active_grip is None


def test_d_in_actuation_never_opens_full_menu(app):
    tap(app, "a")
    tap(app, "d")
    hold(app, "d", 1.0)
    release(app, "d")
    assert app.fsm.state is FsmState.HOLDING


def test_closing_saturates_at_one(app):
    tap(app, "a")
    hold(app, "a", 5.0)
    assert app.fsm.progress == 1.0


def test_a_and_d_together_stops_and_requires_rest(app):
    tap(app, "a")
    hold(app, "a", 0.4)
    app.key_down("d")                     # co-contraction
    app.step(0.05)
    assert app.fsm.state is FsmState.HOLDING and app.fsm.wait_release
    release(app, "a")                     # D still held: still not at rest
    hold(app, "d", 0.2)
    assert app.fsm.state is FsmState.HOLDING
    release(app, "d")
    assert not app.fsm.wait_release


def test_e_during_actuation_returns_to_full_menu(app):
    tap(app, "a")
    hold(app, "a", 1.0)
    release(app, "a")
    tap(app, "e")
    assert app.fsm.state is FsmState.OPENING and app.fsm.returning
    hold(app, "a", 0.2)                   # ignored while returning
    assert app.fsm.state is FsmState.OPENING
    release(app, "a")
    for _ in range(20):
        app.step(0.05)
    assert app.fsm.state is FsmState.FULL and app.fsm.progress == 0.0


def test_e_while_a_held_is_invalid_not_back(app):
    tap(app, "a")
    hold(app, "a", 0.4)
    app.key_down("e")
    app.step(0.05)
    assert not app.fsm.returning


def test_d_from_adaptive_opens_full_menu_and_e_goes_home(app):
    tap(app, "d")
    assert app.fsm.state is FsmState.FULL
    tap(app, "d")
    assert app.fsm.state is FsmState.FULL
    tap(app, "e")
    assert app.fsm.state is FsmState.HOME
    tap(app, "a")
    assert app.fsm.state is FsmState.HOME  # nothing to confirm without a menu
    app.key_down("m")
    assert app.fsm.state is FsmState.ADAPTIVE


def test_m_ignored_outside_home(app):
    tap(app, "s")
    app.key_down("m")
    assert app.fsm.state is FsmState.ADAPTIVE and app.fsm.selected == 1


def test_focus_loss_stops_closing(app):
    tap(app, "a")
    hold(app, "a", 0.4)
    release(app, "a")
    hold(app, "a", 0.4)
    assert app.fsm.state is FsmState.CLOSING
    app.focus_lost()                      # key-up will never arrive
    app.step(0.05)
    assert app.fsm.state is FsmState.HOLDING


def test_stalled_window_cannot_jump_progress(app):
    tap(app, "a")                         # confirm
    app.key_down("a")
    app.step(0.0)
    assert app.fsm.state is FsmState.CLOSING
    before = app.fsm.progress
    app.step(5.0)
    assert app.fsm.progress - before == pytest.approx(0.1 * 0.5)


def test_quit_keys(app):
    app.key_down("q")
    assert app.quit


@pytest.mark.parametrize("bad", ["", "OPEN", "LATERAL,FOO"])
def test_parse_grips_rejects_bad_menus(bad):
    with pytest.raises(SystemExit):
        parse_grips(bad)
