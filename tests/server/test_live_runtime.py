"""DashboardRuntime driving the real arbitration engine and LiveSimApp, on the test thread."""

import io
import json

import pytest

from cavia.server.hub import Hub
from cavia.server.live_runtime import DashboardRuntime
from cavia.server.session import Session
from cavia.server.vision_feed import VisionFeed


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Recorder(Hub):
    def __init__(self):
        super().__init__()
        self.sent = []

    def publish(self, kind, data):
        self.sent.append((kind, data))
        super().publish(kind, data)

    def kinds(self):
        return [k for k, _ in self.sent]

    def last(self, kind):
        return next(d for k, d in reversed(self.sent) if k == kind)

    def emg_events(self):
        return [d["event"] for k, d in self.sent if k == "emg" and "event" in d]


class Vision:
    """Lock on mug/handle whenever asked."""

    def __init__(self, clock):
        self.clock = clock
        self.locked = False
        self.exited = False

    def latest(self):
        if not self.locked:
            return None
        return {"ts": self.clock(), "state": "LOCKED", "object": "cup", "region": "handle",
                "region_confidence": 0.9, "stable": True}


@pytest.fixture
def rt():
    clock = Clock()
    hub = Recorder()
    log = io.StringIO()
    paused = []
    runtime = None
    session = Session(hub.publish, audit=lambda e, **d: runtime.audit(e, **d))
    runtime = DashboardRuntime(hub, session, db=":memory:", log_file=log, clock=clock,
                               detection_control=paused.append)
    vision = Vision(clock)
    runtime.feed = VisionFeed(vision, hub.publish, on_result=runtime.receive_vision, clock=clock)
    runtime.open()
    runtime.test = dict(clock=clock, hub=hub, log=log, paused=paused, vision=vision)
    yield runtime
    runtime.close()


def step(rt, seconds=0.05, n=1, *, heartbeat=True):
    for _ in range(n):
        rt.test["clock"].t += seconds
        rt.tick(seconds)
        if heartbeat:
            rt.keyboard_state(list(rt.app.keys.held))


def lock(rt):
    rt.test["vision"].locked = True
    step(rt, n=2)


def press(rt, key, hold=0.0):
    rt.key(key, True)
    step(rt)
    if hold:
        step(rt, n=round(hold / 0.05))
    rt.key(key, False)
    step(rt)


def log_types(rt):
    return [json.loads(line)["type"] for line in rt.test["log"].getvalue().splitlines()]


def test_open_publishes_initial_state(rt):
    hub = rt.test["hub"]
    assert hub.last("menu") is None
    assert hub.last("fsm")["state"] == "HOME"
    assert "session_started" in log_types(rt)


def test_two_stage_results_drive_object_then_region_menus(rt):
    from types import SimpleNamespace
    from cavia.server.live_vision import TwoStagePipeline

    pipeline = TwoStagePipeline()
    rectangle = [(200, 100, 440, 400)]

    def latest():
        detection = SimpleNamespace(cls=[0], conf=[0.95], xyxy=[rectangle[0]])
        now = rt.test["clock"]()
        return dict(pipeline.process([detection], {0: "cup"}, (480, 640, 3), now), ts=now)

    rt.test["vision"].latest = latest
    step(rt, n=6)
    hub = rt.test["hub"]
    assert hub.last("menu")["context"]["region"] == "unknown"
    assert hub.last("vision")["targeting"]["stage"] == "settling"
    rectangle[0] = (100, 80, 340, 400)
    step(rt, n=55)
    assert hub.last("menu")["context"]["region"] == "handle"
    rectangle[0] = (200, 100, 440, 400)
    step(rt, n=15)
    assert hub.last("menu")["context"]["region"] == "body"
    rt.key("a", True)
    step(rt, n=10)
    assert rt.test["paused"] == [True]
    assert rt.app.frozen


def test_vision_lock_produces_menu_and_adaptive_state(rt):
    lock(rt)
    hub = rt.test["hub"]
    menu = hub.last("menu")
    assert menu["context"]["object"] == "cup" and menu["context"]["region"] == "handle"
    assert menu["condition"] == "C3_ADAPTIVE" and menu["full_menu"]
    fsm = hub.last("fsm")
    assert fsm["state"] in ("ADAPTIVE", "FULL") and fsm["menu_id"] == menu["menu_id"]
    assert fsm["returning"] is False
    assert hub.kinds().count("vision") >= 1


def test_gesture_is_published_before_the_fsm_update_it_causes(rt):
    lock(rt)
    hub = rt.test["hub"]
    if hub.last("fsm")["state"] != "ADAPTIVE" or len(hub.last("menu")["items"]) < 2:
        pytest.skip("cold-start menu has fewer than two items")
    start = len(hub.sent)
    press(rt, "s")
    after = hub.sent[start:]
    i_emg = next(i for i, (k, d) in enumerate(after) if k == "emg" and d.get("event") == "SF")
    i_fsm = next(i for i, (k, d) in enumerate(after) if k == "fsm" and d["selected_index"] == 1)
    assert i_emg < i_fsm


def test_confirm_closes_pauses_detection_and_learns(rt):
    lock(rt)
    hub = rt.test["hub"]
    rt.key("a", True)
    for _ in range(50):                # 2.5 s of flexion with browser heartbeats
        rt.keyboard_state(["a"])
        step(rt)
    assert hub.emg_events()[-1] == "LF"
    fsm = hub.last("fsm")
    assert fsm["state"] == "CLOSING" and fsm["grip_progress"] > 0.2 and fsm["active_grip"]
    assert rt.test["paused"] == [True]
    activity = [d["activity"] for k, d in hub.sent if k == "emg" and "activity" in d]
    assert activity[-1] == "FLEX_ACTIVE"
    assert "preference_update" in log_types(rt)          # held >= 2 s with progress >= 0.2
    rt.key("a", False)
    step(rt)
    assert hub.last("fsm")["state"] == "HOLDING"


def test_unseen_menu_guard_produces_no_fake_gesture(rt):
    lock(rt)
    rt.app.ready = False                # as if the menu had just been replaced
    before = rt.test["hub"].emg_events()
    rt._apply_key("a", True)
    assert rt.test["hub"].emg_events() == before
    assert rt.app.fsm.state.value in ("ADAPTIVE", "FULL")


def test_he_returns_home_clears_menu_and_resumes_detection(rt):
    lock(rt)
    hub = rt.test["hub"]
    rt.key("a", True)
    step(rt, n=10)
    rt.key("a", False)
    step(rt)
    press(rt, "e")                      # leave the grip: controlled opening, then Full Menu
    step(rt, n=40)
    assert hub.last("fsm")["state"] == "FULL"
    rt.test["vision"].locked = False
    press(rt, "e")                      # Full Menu + HE -> CAVIA Home
    assert hub.last("fsm")["state"] == "HOME"
    assert hub.last("menu") is None
    assert rt.test["paused"] == [True, False]


def test_session_rules(rt):
    hub = rt.test["hub"]
    rt.control({"action": "set_session", "participant": "P02", "condition": "C1_MANUAL"})
    step(rt)
    assert rt.session.state.participant == "P01"            # C1 rejected in live mode
    rt.control({"action": "set_session", "participant": "p02", "condition": "C3_ADAPTIVE"})
    step(rt)
    assert rt.session.state.participant == "P02" and rt.app.user == "P02"
    assert hub.last("session")["participant"] == "P02"
    lock(rt)
    rt.key("a", True)
    step(rt, n=5)
    rt.control({"action": "set_session", "participant": "P03", "condition": "C3_ADAPTIVE"})
    step(rt)
    assert rt.session.state.participant == "P02"            # not during a grip
    assert log_types(rt).count("control_rejected") == 2


def test_trial_controls_are_logged_with_context(rt):
    rt.control({"action": "start_trial"})
    step(rt)
    rt.control({"action": "end_trial", "grasp_success": True, "notes": "ok"})
    step(rt)
    records = [json.loads(line) for line in rt.test["log"].getvalue().splitlines()]
    start = next(r for r in records if r["type"] == "trial_start")
    end = next(r for r in records if r["type"] == "trial_end")
    assert start["trial"] == 1 and start["user"] == "P01" and start["condition"] == "C3_ADAPTIVE"
    assert end["data"] == {"trial": 1, "grasp_success": True, "notes": "ok"}
    assert end["trial"] is None                              # trial already closed when logged


def test_users_are_listed_added_and_switched(rt):
    hub = rt.test["hub"]
    users = hub.last("users")
    assert users["current"] == "P01" and [u["user"] for u in users["users"]] == ["P01"]
    assert users["users"][0]["selections"] == 0 and users["users"][0]["last_used"] is None
    rt.control({"action": "add_user", "user": " p07 "})
    step(rt)
    assert [u["user"] for u in hub.last("users")["users"]] == ["P01", "P07"]
    assert rt.session.state.participant == "P01"            # adding does not switch
    for bad in ["P07", "", "no spaces"]:
        rt.control({"action": "add_user", "user": bad})
        step(rt)
        assert hub.last("notice")["ok"] is False
    assert "already exists" in [d for k, d in hub.sent if k == "notice"][0]["message"]
    rt.control({"action": "set_session", "participant": "P07", "condition": "C3_ADAPTIVE"})
    step(rt)
    assert hub.last("users")["current"] == "P07" and rt.app.user == "P07"
    assert "user_added" in log_types(rt)


def test_user_counts_update_after_a_learned_selection(rt):
    lock(rt)
    rt.key("a", True)
    step(rt, n=50)
    step(rt)
    users = rt.test["hub"].last("users")["users"]
    assert users[0]["user"] == "P01" and users[0]["accepted"] == 1


def test_switching_user_in_a_menu_clears_it_but_not_after_confirmation(rt):
    hub = rt.test["hub"]
    lock(rt)
    assert hub.last("menu") is not None
    rt.control({"action": "set_session", "participant": "P02", "condition": "C3_ADAPTIVE"})
    step(rt)
    assert rt.app.user == "P02" and hub.last("menu") is None and hub.last("fsm")["state"] == "HOME"
    step(rt, n=3)                                            # a fresh lock ranks for the new user
    assert hub.last("menu") is not None and rt.app.decision.user == "P02"
    rt.key("a", True)
    step(rt, n=30)
    rt.key("a", False)
    step(rt)
    rt.control({"action": "set_session", "participant": "P03", "condition": "C3_ADAPTIVE"})
    step(rt)
    assert rt.app.user == "P02"
    assert "before confirming" in hub.last("notice")["message"]


def test_log_records_mark_the_rest_window(rt):
    rt.control({"action": "start_rest"})
    step(rt)
    press(rt, "s")                                            # a gesture during rest: a false activation
    rt.control({"action": "end_rest"})
    step(rt)
    records = [json.loads(line) for line in rt.test["log"].getvalue().splitlines()]
    start = next(r for r in records if r["type"] == "rest_start")
    key = next(r for r in records if r["type"] == "key_down")
    end = next(r for r in records if r["type"] == "rest_end")
    assert start["rest"] == 1 and key["rest"] == 1 and end["rest"] is None
    assert end["data"]["rest"] == 1 and end["data"]["duration_s"] >= 0

def test_browser_lease_stops_offline_hold_and_heartbeat_cannot_repress(rt):
    lock(rt)
    rt.key("a", True)
    step(rt)
    assert rt.app.keys.held == {"a"}
    for _ in range(10):
        rt.keyboard_state(["a"])
        step(rt)
    assert rt.app.keys.held == {"a"}
    step(rt, n=10, heartbeat=False)
    assert not rt.app.keys.held
    assert rt.test["hub"].last("fsm")["state"] == "HOLDING"
    rt.keyboard_state(["a"])
    step(rt)
    assert not rt.app.keys.held
    rt.key("a", True)
    step(rt)
    assert rt.app.keys.held == {"a"}


def test_browser_heartbeat_releases_missing_key(rt):
    lock(rt)
    rt.key("a", True)
    step(rt)
    rt.keyboard_state([])
    step(rt)
    assert not rt.app.keys.held
