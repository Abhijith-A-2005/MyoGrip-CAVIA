import json

import pytest

from cavia.core.bus import Bus
from cavia.core.config import load_config
from cavia.core.contracts import (
    Activity, Condition, EmgEvent, EmgInput, FsmState, FsmStatus, Grip, LogRecord,
    MenuConfidence, MenuContext, MenuKind, MenuPolicy, MenuProposal, VisionResult, VisionState,
)
from cavia.core.grips import full_menu


def roundtrip(obj):
    # Through real JSON, as the logger and dashboard will do.
    return type(obj).from_dict(json.loads(json.dumps(obj.to_dict())))


def test_grip_wire_values_are_frozen():
    assert [(g.name, g.value) for g in Grip] == [
        ("OPEN", 0), ("POWER", 1), ("PINCH", 2), ("TRIPOD", 3), ("LATERAL", 4),
    ]


def test_vision_result_roundtrip():
    v = VisionResult(ts=1.0, frame_seq=812, state=VisionState.LOCKED, object="cup",
                     region="handle", region_confidence=0.87, det_conf=0.91,
                     reticle_score=0.64, stability=0.88, stable=True)
    assert v.to_dict()["state"] == "LOCKED"
    assert roundtrip(v) == v


def test_menu_proposal_matches_interface_doc():
    m = MenuProposal(
        ts=1235.01, menu_id=17, condition=Condition.C3_ADAPTIVE,
        context=MenuContext("cup", "handle", 0.87), policy=MenuPolicy.TOP_TWO,
        items=[Grip.LATERAL, Grip.PINCH], scores=[0.71, 0.29],
        confidence=MenuConfidence(vision=0.87, evidence_n=6, top_share=0.71, margin=0.42),
        full_menu=full_menu(),
    )
    d = m.to_dict()
    assert d["items"] == ["LATERAL", "PINCH"]
    assert d["full_menu"] == ["POWER", "PINCH", "TRIPOD", "LATERAL"]
    assert d["context"] == {"object": "cup", "region": "handle", "region_confidence": 0.87}
    assert roundtrip(m) == m


def test_emg_input_requires_exactly_one_kind():
    assert roundtrip(EmgInput(ts=1.0, source="keyboard", event=EmgEvent.SF)).event is EmgEvent.SF
    assert roundtrip(EmgInput(ts=1.0, source="device", activity=Activity.FLEX_ACTIVE)).activity \
        is Activity.FLEX_ACTIVE
    with pytest.raises(ValueError):
        EmgInput(ts=1.0, source="keyboard")
    with pytest.raises(ValueError):
        EmgInput(ts=1.0, source="keyboard", event=EmgEvent.SF, activity=Activity.REST)


def test_fsm_status_roundtrip():
    s = FsmStatus(ts=1241.0, menu_id=17, state=FsmState.CLOSING, menu_kind=MenuKind.ADAPTIVE,
                  selected_index=0, selected_grip=Grip.LATERAL, active_grip=Grip.LATERAL,
                  grip_progress=0.43, wait_release=False, last_event="LF")
    assert roundtrip(s) == s
    home = FsmStatus(ts=0.0, menu_id=None, state=FsmState.HOME, menu_kind=None,
                     selected_index=0, selected_grip=None, active_grip=None,
                     grip_progress=0.0, wait_release=False)
    assert roundtrip(home) == home


def test_log_record_rejects_unknown_type():
    r = LogRecord(wall=1.0, ts=2.0, session="S1", user="P01", condition=Condition.C1_MANUAL,
                  trial=1, type="trial_start", data={"target_grip": "POWER"})
    assert roundtrip(r) == r
    with pytest.raises(ValueError):
        LogRecord(wall=1.0, ts=2.0, session="S1", user="P01", condition=Condition.C1_MANUAL,
                  trial=1, type="bogus")


def test_bus_delivers_to_topic_and_wildcard():
    bus, seen = Bus(), []
    unsub = bus.subscribe("menu", lambda t, m: seen.append(("menu", m)))
    bus.subscribe("*", lambda t, m: seen.append(("*", t)))
    bus.publish("menu", 1)
    unsub()
    bus.publish("menu", 2)
    assert seen == [("menu", 1), ("*", "menu"), ("*", "menu")]


def test_config_overrides_and_rejects_typos(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[fsm]\nclose_speed = 0.5\n[policy]\nmin_evidence = 4\n")
    cfg = load_config(p)
    assert cfg.fsm.close_speed == 0.5 and cfg.policy.min_evidence == 4
    p.write_text("[fsm]\nclose_sped = 0.5\n")
    with pytest.raises(KeyError):
        load_config(p)
