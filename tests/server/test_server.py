import threading

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cavia.core.contracts import Condition  # noqa: E402
from cavia.server.app import create_app, parse_client_message  # noqa: E402
from cavia.server.hub import Hub  # noqa: E402
from cavia.server.session import Session  # noqa: E402


def make(dist=None, keys=None):
    hub = Hub()
    audit = []
    session = Session(hub.publish, audit=lambda event, **data: audit.append((event, data)))
    session.announce()
    app = create_app(hub, dist=dist, on_key=(lambda k, d: keys.append((k, d))) if keys is not None else None,
                     on_control=session.control)
    return hub, session, audit, app


def test_snapshot_on_connect():
    hub, _, _, app = make()
    hub.publish("vision", {"state": "SEARCHING"})
    hub.publish("emg", {"event": "SF"})
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        data = msg["data"]
        assert data["vision"] == {"state": "SEARCHING"}
        assert data["session"]["participant"] == "P01"
        assert data["emg_recent"] == [{"event": "SF"}]
        assert data["menu"] is None and data["fsm"] is None


def test_updates_from_another_thread_reach_the_browser():
    hub, _, _, app = make()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()  # snapshot
        t = threading.Thread(target=hub.publish, args=("fsm", {"state": "ADAPTIVE"}))
        t.start()
        t.join()
        assert ws.receive_json() == {"type": "fsm", "data": {"state": "ADAPTIVE"}}


def test_drawer_controls_update_session_and_audit():
    _, session, audit, app = make()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "control", "data": {"action": "set_session", "participant": "p02",
                                                   "condition": "C2_STATIC"}})
        assert ws.receive_json()["data"] == {"participant": "P02", "condition": "C2_STATIC",
                                             "trial": 0, "trial_active": False}
        ws.send_json({"type": "control", "data": {"action": "start_trial"}})
        assert ws.receive_json()["data"]["trial_active"] is True
        ws.send_json({"type": "control", "data": {"action": "end_trial", "grasp_success": True,
                                                   "notes": "clean grasp"}})
        assert ws.receive_json()["data"] == {"participant": "P02", "condition": "C2_STATIC",
                                             "trial": 1, "trial_active": False}
    assert [e for e, _ in audit] == ["session_start", "trial_start", "trial_end"]
    assert audit[-1][1] == {"trial": 1, "grasp_success": True, "notes": "clean grasp"}


def test_invalid_control_is_rejected_and_socket_stays_open():
    hub, session, _, app = make()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "control", "data": {"action": "end_trial", "grasp_success": True}})
        ws.send_json({"type": "control", "data": {"action": "set_session", "participant": "P03",
                                                   "condition": "NOT_A_CONDITION"}})
        ws.send_json({"type": "control", "data": {"action": "start_trial"}})
        msg = ws.receive_json()  # only the valid start_trial produced an update
        assert msg["data"]["trial"] == 1 and msg["data"]["participant"] == "P01"


def test_cannot_change_session_during_trial():
    hub = Hub()
    session = Session(hub.publish)
    session.control({"action": "start_trial"})
    with pytest.raises(ValueError):
        session.control({"action": "set_session", "participant": "P02", "condition": "C1_MANUAL"})
    assert session.state.condition == Condition.C3_ADAPTIVE.value


def test_keys_are_forwarded_and_junk_is_ignored():
    keys = []
    _, _, _, app = make(keys=keys)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "key", "data": {"key": "a", "down": True}})
        ws.send_json({"type": "key", "data": {"key": "q", "down": True}})      # not a gesture key
        ws.send_json({"type": "key", "data": {"key": "s", "down": "yes"}})     # not a bool
        ws.send_json({"type": "nonsense"})
        ws.send_json({"type": "key", "data": {"key": "a", "down": False}})
        ws.send_json({"type": "control", "data": {"action": "start_trial"}})
        ws.receive_json()  # session update proves every earlier message was processed
    assert keys == [("a", True), ("a", False)]


@pytest.mark.parametrize("msg", [None, [], {"type": "key"}, {"type": "key", "data": []},
                                 {"type": "control", "data": {}}])
def test_parse_rejects_malformed(msg):
    assert parse_client_message(msg) is None


def test_hub_rejects_unknown_kind():
    with pytest.raises(ValueError):
        Hub().publish("weather", {})


def test_serves_built_dashboard_and_health(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>CAVIA</title>")
    _, _, _, app = make(dist=tmp_path)
    with TestClient(app) as client:
        assert "CAVIA" in client.get("/").text
        assert client.get("/health").json() == {"ok": True, "clients": 0}
        assert client.get("/video").status_code == 503


def test_missing_build_explains_how_to_build(tmp_path):
    _, _, _, app = make(dist=tmp_path)
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 503 and "npm run build" in r.json()["detail"]
