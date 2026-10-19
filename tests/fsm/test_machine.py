import json
from pathlib import Path

import pytest

from cavia.core.config import FsmConfig
from cavia.core.contracts import (
    Activity, Condition, EmgEvent, FsmState, Grip, MenuConfidence, MenuContext, MenuKind,
    MenuPolicy, MenuProposal,
)
from cavia.fsm.machine import MyoGripFsm

VECTORS = json.loads((Path(__file__).parent / "vectors.json").read_text())
FULL = [Grip[g] for g in VECTORS["full_menu"]]


def proposal(items, policy=MenuPolicy.TOP_TWO, menu_id=1, full=FULL):
    return MenuProposal(
        ts=0.0, menu_id=menu_id, condition=Condition.C3_ADAPTIVE,
        context=MenuContext("cup", "handle", 0.9), policy=policy,
        items=list(items), scores=[0.0] * len(items), confidence=MenuConfidence(),
        full_menu=list(full),
    )


def apply(fsm, step):
    op = step["op"]
    if op == "menu":
        items = [Grip[g] for g in step["items"]]
        fsm.load_menu(proposal(items, MenuPolicy(step.get("policy", "TOP_TWO"))))
    elif op == "event":
        fsm.on_event(EmgEvent(step["value"]))
    elif op == "activity":
        fsm.on_activity(Activity(step["value"]))
    elif op == "tick":
        fsm.tick(step["dt"])
    elif op == "abort":
        fsm.abort()
    else:
        raise ValueError(op)


def check(fsm, expect, where):
    if "state" in expect:
        assert fsm.state is FsmState(expect["state"]), where
    if "index" in expect:
        assert fsm.selected == expect["index"], where
    if "gate" in expect:
        assert fsm.wait_release is expect["gate"], where
    if "progress" in expect:
        assert fsm.progress == pytest.approx(expect["progress"], abs=1e-9), where
    if "grip" in expect:
        want = None if expect["grip"] is None else Grip[expect["grip"]]
        assert fsm.active_grip is want, where


@pytest.mark.parametrize("seq", VECTORS["sequences"], ids=lambda s: s["name"])
def test_shared_vectors(seq):
    fsm = MyoGripFsm(FsmConfig(**VECTORS["config"]), full=FULL)
    for i, step in enumerate(seq["steps"], 1):
        apply(fsm, step)
        check(fsm, step["expect"], f"{seq['name']} step {i}: {step}")


def test_status_reports_menu_and_actuation():
    fsm = MyoGripFsm(FsmConfig(close_speed=0.5), full=FULL)
    fsm.load_menu(proposal([Grip.LATERAL, Grip.PINCH], menu_id=17))
    fsm.on_event(EmgEvent.SF)
    s = fsm.status(ts=3.0)
    assert (s.state, s.menu_kind, s.selected_grip, s.menu_id) == \
        (FsmState.ADAPTIVE, MenuKind.ADAPTIVE, Grip.PINCH, 17)

    fsm.on_event(EmgEvent.LF)
    fsm.on_activity(Activity.REST)
    fsm.on_activity(Activity.FLEX_ACTIVE)
    fsm.tick(1.0)
    s = fsm.status(ts=4.0)
    assert (s.state, s.menu_kind, s.active_grip, s.grip_progress, s.last_event) == \
        (FsmState.CLOSING, MenuKind.ADAPTIVE, Grip.PINCH, 0.5, "FLEX_ACTIVE")


def test_he_from_menu_clears_snapshot():
    fsm = MyoGripFsm(full=FULL)
    fsm.load_menu(proposal([Grip.POWER], menu_id=5))
    fsm.on_event(EmgEvent.HE)
    s = fsm.status(ts=0.0)
    assert (s.state, s.menu_id, s.menu_kind, s.last_event) == (FsmState.HOME, None, None, "HE")


@pytest.mark.parametrize("field", ["close_speed", "open_speed", "he_return_speed"])
@pytest.mark.parametrize("value", [0.0, -0.5])
def test_non_positive_speed_rejected(field, value):
    with pytest.raises(ValueError):
        MyoGripFsm(FsmConfig(**{field: value}))
