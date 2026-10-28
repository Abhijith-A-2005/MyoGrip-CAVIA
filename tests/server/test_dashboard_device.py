"""Browser leases, multiple viewers, and startup source reporting."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cavia.server.__main__ import offline_system, runtime_system
from cavia.server.app import create_app, parse_client_message
from cavia.server.hub import Hub


@pytest.mark.parametrize("keys", [None, "a", ["a", "a"], ["q"], [[]], [True], list("wasdee")])
def test_invalid_key_heartbeat_is_rejected(keys):
    assert parse_client_message({"type": "key_state", "data": {"keys": keys}}) is None


def test_malformed_key_cannot_crash_message_parser():
    assert parse_client_message({"type": "key", "data": {"key": [], "down": True}}) is None


def make_app():
    hub, events = Hub(), []
    app = create_app(hub, on_key=lambda key, down: events.append((key, down)),
                     on_key_state=lambda keys: events.append(("held", keys)),
                     on_control=lambda data: hub.publish("session", data))
    return app, events


def barrier(ws):
    ws.send_json({"type": "control", "data": {"action": "barrier"}})
    assert ws.receive_json()["type"] == "session"


def test_owner_disconnect_releases_keys():
    app, events = make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "key", "data": {"key": "a", "down": True}})
            ws.send_json({"type": "key_state", "data": {"keys": ["a"]}})
            barrier(ws)
            assert events == [("a", True), ("held", ["a"])]
        assert events[-2:] == [("a", False), ("held", [])]


def test_heartbeat_only_releases_and_never_adds_a_key():
    app, events = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "key_state", "data": {"keys": ["a"]}})
        ws.send_json({"type": "key", "data": {"key": "a", "down": True}})
        ws.send_json({"type": "key_state", "data": {"keys": ["d"]}})
        barrier(ws)
        assert events == [("a", True), ("a", False), ("held", [])]


def test_idle_viewer_cannot_clear_or_refresh_owner_keys():
    app, events = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as owner:
        owner.receive_json()
        owner.send_json({"type": "key", "data": {"key": "a", "down": True}})
        barrier(owner)
        with client.websocket_connect("/ws") as viewer:
            viewer.receive_json()
            viewer.send_json({"type": "key_state", "data": {"keys": []}})
            viewer.send_json({"type": "key", "data": {"key": "d", "down": True}})
            barrier(viewer)
            assert events == [("a", True)]
        assert events == [("a", True)]


def test_keyboard_source_is_explicit_without_device():
    status = runtime_system(offline_system(), None)
    assert status["controller"] == status["emg_source"] == "keyboard"
    assert status["hand_link"]["status"] == "disconnected"


@pytest.mark.parametrize("status", ["connected", "stale", "disconnected"])
def test_firmware_status_preserves_calibration_and_freshness(status):
    device = SimpleNamespace(status=lambda: {"status": status, "calibrated": status == "connected",
                                            "armed": False, "calibration": "REST capture complete"})
    runtime = SimpleNamespace(keyboard_ready=lambda: status == "connected", calibration_mode=True)
    result = runtime_system(offline_system(), runtime, device)
    assert result["controller"] == "firmware" and result["emg_source"] == "device"
    assert result["hand_link"] == device.status()
    assert result["keyboard_ready"] == (status == "connected") and result["calibration_mode"]
