"""Retained-menu behavior and detection-loop pause/resume checks."""

import io
import json
from pathlib import Path
import runpy
import select
import socket
import sys
import time
from types import SimpleNamespace

import pytest

from cavia.arbitration.engine import ArbitrationEngine
from cavia.arbitration.preferences import PreferenceStore
from cavia.core.contracts import FsmState
from cavia.runtime.controller import LiveSimApp
from cavia.runtime.vision_link import DetectionControl, VisionProcess


def test_no_menu_until_first_lock_then_retained_until_new_lock_or_home():
    now = [100.0]
    commands = []

    with PreferenceStore(":memory:") as store:
        app = LiveSimApp(
            ArbitrationEngine(store),
            clock=lambda: now[0],
            detection_control=commands.append,
        )

        def send(state, obj="cup", region="handle"):
            now[0] += 0.1

            app.receive(
                dict(
                    ts=now[0],
                    state=state,
                    stable=state == "LOCKED",
                    object=obj,
                    region=region,
                    region_confidence=0.9,
                )
            )
            app.mark_rendered()

        send("SEARCHING")
        assert app.decision is None
        assert app.fsm.state is FsmState.HOME

        send("LOCKED")
        old_menu = app.fsm.menu_id

        send("SEARCHING", "bottle", "cap")
        send("NO_OBJECT", None, None)

        assert app.fsm.menu_id == old_menu
        assert app.request.object == "cup"

        send("LOCKED", "bottle", "cap")

        assert app.fsm.menu_id != old_menu
        assert app.request.object == "bottle"

        app.key_down("e")
        app.key_up("e")

        assert app.decision is None
        assert app.fsm.state is FsmState.HOME
        assert commands == [False]


def test_pause_is_sent_once_and_full_menu_does_not_resume():
    now = [100.0]
    commands = []

    with PreferenceStore(":memory:") as store:
        app = LiveSimApp(
            ArbitrationEngine(store),
            clock=lambda: now[0],
            detection_control=commands.append,
        )

        now[0] += 1
        app.receive(
            dict(
                ts=now[0],
                state="LOCKED",
                stable=True,
                object="cup",
                region="handle",
                region_confidence=0.9,
            )
        )
        app.mark_rendered()

        for key in ("a", "e"):
            app.key_down(key)
            app.key_up(key)

        app.step(0.1)

        assert app.fsm.state is FsmState.FULL
        assert commands == [True]

        app.mark_rendered()

        for key in ("a", "e"):
            app.key_down(key)
            app.key_up(key)

        app.step(0.1)

        # Reconfirming from Full Menu must not resume detection.
        assert commands == [True]

        app.key_down("e")
        app.key_up("e")

        assert commands == [True, False]


def test_control_reader_handles_invalid_and_out_of_order_commands(monkeypatch):
    monkeypatch.delenv("CAVIA_CONTROL_STDIN", raising=False)
    control = DetectionControl()

    control._read(
        io.StringIO(
            "\n".join(
                [
                    "not-json",
                    "[]",
                    "{}",
                    '{"paused":true,"generation":true}',
                    '{"paused":true,"generation":1}',
                ]
            )
        )
    )

    assert control.snapshot() == (True, 1)

    control._read(
        io.StringIO(
            "\n".join(
                [
                    '{"paused":false,"generation":2}',
                    '{"paused":true,"generation":1}',
                ]
            )
        )
    )

    assert control.snapshot() == (False, 2)


def test_old_generation_is_rejected_even_with_a_new_timestamp(tmp_path):
    vision = VisionProcess(tmp_path / "unused.py")
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        vision.generation = 2

        sender.sendto(
            json.dumps(
                dict(
                    ts=time.monotonic(),
                    state="LOCKED",
                    stable=True,
                    object="cup",
                    region="handle",
                    region_confidence=0.9,
                    generation=0,
                )
            ).encode(),
            vision.sock.getsockname(),
        )

        assert vision.latest() is None

    finally:
        sender.close()
        vision.close()


def test_pause_resume_commands_reach_real_child(tmp_path, monkeypatch):
    src = Path(__file__).resolve().parents[2] / "src"
    monkeypatch.setenv("PYTHONPATH", str(src))

    script = tmp_path / "fake_detector.py"
    script.write_text(
        "import time\n"
        "from cavia.runtime.vision_link import DetectionControl, publish_result\n"
        "control = DetectionControl()\n"
        "while True:\n"
        "    paused, generation = control.snapshot()\n"
        "    if not paused:\n"
        "        publish_result(dict(state='LOCKED', stable=True, "
        "object='cup', region='handle', region_confidence=.9), "
        "generation=generation)\n"
        "    time.sleep(.02)\n"
    )

    vision = VisionProcess(script)

    try:
        vision.start()

        assert select.select([vision.sock], [], [], 3)[0]
        assert vision.latest()["generation"] == 0

        vision.set_paused(True)
        vision.set_paused(False)

        assert vision.control_error is None

        result = None
        deadline = time.monotonic() + 3

        while result is None and time.monotonic() < deadline:
            select.select(
                [vision.sock],
                [],
                [],
                max(0, deadline - time.monotonic()),
            )
            result = vision.latest()

        assert result is not None
        assert result["generation"] == 2

    finally:
        vision.close()


@pytest.mark.parametrize("resume_during_inference", [False, True])
def test_actual_objdet_loop_skips_inference_while_paused_and_rejects_old_work(
    monkeypatch,
    resume_during_inference,
):
    """Run objdet.py itself with fake camera/model/GUI dependencies."""
    from cavia.runtime import vision_link

    source = Path(__file__).resolve().parents[2] / "src/cavia/vision"

    control_state = [False, 0]
    calls = []
    emissions = []
    waits = []
    snapshots = [0]
    closed = []

    class Frame:
        shape = (480, 640, 3)

        def copy(self):
            return self

    class Camera:
        mode = "laptop"

        def __init__(self, settings):
            pass

        def start(self):
            return self

        def snapshot(self):
            snapshots[0] += 1

            return dict(
                frame=Frame(),
                received_at=time.monotonic(),
                source="LAPTOP",
                status="Live",
                session=1,
                sequence=snapshots[0],
            )

        def close(self):
            closed.append(True)

    class Model:
        def __init__(self, weights):
            pass

        def __call__(self, frame, verbose=False):
            calls.append(True)

            if resume_during_inference and len(calls) == 1:
                # PAUSE and HOME arrive while this inference is running.
                control_state[:] = [False, 2]

            return [SimpleNamespace(boxes=[])]

    def wait_key(ms):
        waits.append(len(calls))

        if resume_during_inference:
            return ord("q")

        if len(waits) == 1:
            control_state[:] = [True, 1]
        elif len(waits) == 3:
            control_state[:] = [False, 2]
        elif len(waits) == 4:
            return ord("q")

        return -1

    def noop(*args, **kwargs):
        pass

    fake_cv = SimpleNamespace(
        WINDOW_NORMAL=0,
        WND_PROP_VISIBLE=0,
        FONT_HERSHEY_SIMPLEX=0,
        namedWindow=noop,
        resizeWindow=noop,
        line=noop,
        putText=noop,
        imshow=noop,
        waitKey=wait_key,
        getWindowProperty=lambda *args: 1,
        destroyAllWindows=noop,
    )

    monkeypatch.setitem(sys.modules, "cv2", fake_cv)

    monkeypatch.setitem(
        sys.modules,
        "numpy",
        SimpleNamespace(
            zeros=lambda *args, **kwargs: Frame(),
            uint8=int,
        ),
    )

    monkeypatch.setitem(
        sys.modules,
        "ultralytics",
        SimpleNamespace(YOLO=Model),
    )

    monkeypatch.setitem(
        sys.modules,
        "camera_source",
        SimpleNamespace(
            CameraSource=Camera,
            CameraSettings=SimpleNamespace(
                from_env=lambda: SimpleNamespace(max_frame_age=1)
            ),
        ),
    )

    monkeypatch.syspath_prepend(str(source))

    monkeypatch.setattr(
        vision_link,
        "DetectionControl",
        lambda: SimpleNamespace(
            snapshot=lambda: tuple(control_state)
        ),
    )

    monkeypatch.setattr(
        vision_link,
        "publish_result",
        lambda out, generation=0: emissions.append(
            (generation, len(calls))
        ),
    )

    result = runpy.run_path(str(source / "objdet.py"))

    assert closed
    assert len(calls) == 2
    assert result["last_control_generation"] == 2

    if resume_during_inference:
        assert (0, 1) not in emissions
    else:
        assert waits == [1, 1, 1, 2]
        assert all(
            generation != 1
            for generation, _ in emissions
        )