"""The merged launcher keeps the history route and in-process camera lifecycle."""

import pytest

pytest.importorskip("fastapi")
uvicorn = pytest.importorskip("uvicorn")
from fastapi.testclient import TestClient

from cavia.arbitration import ArbitrationEngine, ArbitrationInput, PreferenceStore
from cavia.server import __main__ as launcher
from cavia.server import live_vision


@pytest.mark.parametrize("mode", ["off", "live"])
def test_launcher_wires_history_and_closes_camera(tmp_path, monkeypatch, mode):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>CAVIA</title>")
    db = tmp_path / "preferences.sqlite3"
    with PreferenceStore(db) as store:
        engine = ArbitrationEngine(store)
        menu = engine.propose(ArbitrationInput("P01", "cup", "handle", 0.9)).proposal
        engine.confirm(menu.menu_id, menu.items[0], "merge-check")
        engine.finish("merge-check", "accepted")

    camera_events = []

    class FakeVision:
        exited = False

        def start(self):
            camera_events.append("start")
            return self

        def close(self):
            camera_events.append("close")

        def latest(self):
            return None

        def latest_frame(self):
            return None

        def set_paused(self, paused):
            pass

        def status(self):
            return launcher.offline_system()

    monkeypatch.setattr(live_vision, "LiveVision", FakeVision)
    checked = []

    def run(server, sockets):
        assert sockets[0].getsockname()[1] > 0
        with TestClient(server.config.app) as client:
            response = client.get("/api/history", params={"user": "P01"})
            assert response.status_code == 200
            history = response.json()
            assert history["summary"]["accepted"] == 1
            assert history["selections"][0]["id"] == "merge-check"
            assert client.get("/video").status_code == 503
            assert "CAVIA" in client.get("/").text
        checked.append(True)

    monkeypatch.setattr(uvicorn.Server, "run", run)
    launcher.main([
        "--user", "P01", "--vision", mode, "--no-browser", "--port", "0",
        "--dist", str(dist), "--db", str(db), "--log-dir", str(tmp_path / "logs"),
    ])
    assert checked == [True]
    assert camera_events == (["start", "close"] if mode == "live" else [])
