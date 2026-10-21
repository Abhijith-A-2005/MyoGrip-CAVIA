"""Exercise the real launcher/event loop with mocked vision hardware."""

import json
import time

import pytest


def test_launcher_window_freezes_then_resumes_and_cleans_up(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    pygame = pytest.importorskip("pygame")
    from cavia.runtime import live

    states = []
    frames = {"n": 0}

    class FakeVision:
        exited = False
        control_error = None
        commands = []
        started = False
        closed = False

        def __init__(self, script):
            assert script.name == "objdet.py"

        def start(self):
            FakeVision.started = True

        def latest(self):
            frames["n"] += 1
            n = frames["n"]

            return dict(
                ts=time.monotonic(),
                state="LOCKED",
                stable=True,
                object="cup" if n < 5 else "bottle",
                region="handle" if n < 3 else "body",
                region_confidence=0.9,
            )

        def close(self):
            FakeVision.closed = True

        def set_paused(self, paused):
            FakeVision.commands.append(paused)

    class Clock:
        def tick(self, hz):
            return 100

    def events():
        n = frames["n"]

        if n == 4:
            return [
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a)
            ]

        if n == 5:
            return [
                pygame.event.Event(pygame.KEYUP, key=pygame.K_a)
            ]

        if n in {6, 8}:
            return [
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e),
                pygame.event.Event(pygame.KEYUP, key=pygame.K_e),
            ]

        if n >= 10:
            return [pygame.event.Event(pygame.QUIT)]

        return []

    original_draw = live.draw_live

    def capture(app, screen, fonts):
        original_draw(app, screen, fonts)

        states.append(
            (
                frames["n"],
                app.fsm.state.value,
                app.request.object,
                app.frozen,
            )
        )

        if frames["n"] in {2, 5, 9}:
            pygame.image.save(
                screen,
                str(tmp_path / f"frame-{frames['n']}.png"),
            )

    monkeypatch.setattr(live, "VisionProcess", FakeVision)
    monkeypatch.setattr(live, "draw_live", capture)
    monkeypatch.setattr(pygame.event, "get", events)
    monkeypatch.setattr(pygame.time, "Clock", Clock)

    logs = tmp_path / "logs"

    live.main(
        [
            "--db",
            str(tmp_path / "history.sqlite3"),
            "--log-dir",
            str(logs),
        ]
    )

    assert FakeVision.started and FakeVision.closed
    assert FakeVision.commands == [True, False]
    assert not pygame.get_init()

    assert (5, "HOLDING", "cup", True) in states
    assert (7, "FULL", "cup", True) in states
    assert (8, "HOME", "unknown", False) in states
    assert (9, "ADAPTIVE", "bottle", False) in states

    entries = [
        json.loads(line)
        for line in next(logs.glob("*.jsonl")).read_text().splitlines()
    ]

    assert sum(row["type"] == "confirmed" for row in entries) == 1
    assert any(row["type"] == "vision_resumed" for row in entries)
    assert entries[-1]["type"] == "session_closed"