"""Launch the CAVIA dashboard with vision and user history."""

import argparse
from contextlib import ExitStack
import logging
from pathlib import Path
import socket
import threading
import time
import uuid
import webbrowser

from cavia.core.contracts import Condition

from .app import create_app
from .hub import Hub
from .live_runtime import DashboardRuntime
from .session import Session
from .vision_feed import ReplayVision, VisionFeed


DIST = (
    Path(__file__).resolve().parents[2]
    / "dashboard"
    / "web"
    / "dist"
)


def offline_system():
    """Initial status and compatibility with existing status tests."""
    return {
        "camera": {
            "status": "down",
            "source": "XIAO",
            "fps": 0.0,
            "latency_ms": 0,
        },
        "vision": {
            "status": "down",
            "model": "not running",
        },
        "hand_link": {
            "status": "disconnected",
            "battery_pct": None,
        },
        "emg_source": "keyboard",
    }


def system_status(feed, frames=None):
    """Retain the existing helper for older frame-transport tests."""
    system = offline_system()

    if feed is not None:
        system.update(feed.status())

    stats = frames.stats() if frames is not None else None

    if stats is not None and system["camera"]["status"] != "down":
        fps, latency_ms = stats

        system["camera"] = {
            **system["camera"],
            "status": "live",
            "fps": fps,
            "latency_ms": latency_ms,
        }

    return system


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)

    parser.add_argument(
        "--user",
        "--participant",
        dest="user",
        default="1",
    )

    parser.add_argument(
        "--vision",
        choices=["live", "off"],
        default="live",
    )

    parser.add_argument("--replay", type=Path)
    parser.add_argument("--record-vision", type=Path)
    parser.add_argument("--dist", type=Path, default=DIST)
    parser.add_argument("--db", default="data/arbitration/demo.sqlite3")

    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("data/arbitration/sessions"),
    )

    parser.add_argument("--result-timeout", type=float, default=2.0)
    parser.add_argument("--no-browser", action="store_true")

    args = parser.parse_args(argv)

    if not args.user.strip():
        parser.error("--user must not be empty")

    if not (args.dist / "index.html").is_file():
        parser.error(
            "Build the dashboard first: "
            "npm --prefix src/dashboard/web run build"
        )

    import uvicorn

    logging.basicConfig(level=logging.INFO)

    with ExitStack() as stack:
        # Check the port before starting the camera.
        listener = stack.enter_context(
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        )

        try:
            listener.bind((args.host, args.port))
            listener.listen(128)
        except OSError as error:
            parser.exit(
                1,
                f"Cannot use {args.host}:{args.port}: {error}\n"
                "Stop the previous CAVIA server "
                "or choose --port 8001.\n",
            )

        source = None
        frames = None

        if args.replay:
            source = ReplayVision(args.replay)

        elif args.vision == "live":
            from .live_vision import LiveVision, PreviewFrames

            source = LiveVision().start()
            stack.callback(source.close)
            frames = PreviewFrames(source)

        args.log_dir.mkdir(parents=True, exist_ok=True)

        session_name = (
            f"{time.strftime('%Y%m%d-%H%M%S')}"
            f"-{uuid.uuid4().hex[:8]}"
        )

        log_path = args.log_dir / f"{session_name}.jsonl"

        session_log = stack.enter_context(
            log_path.open(
                "w",
                encoding="utf-8",
                buffering=1,
            )
        )

        record = None

        if args.record_vision:
            args.record_vision.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            record = stack.enter_context(
                args.record_vision.open(
                    "w",
                    encoding="utf-8",
                    buffering=1,
                )
            )

        hub = Hub()

        session = Session(
            hub.publish,
            audit=lambda event, **data: runtime.audit(event, **data),
            participant=args.user,
            condition=Condition.C3_ADAPTIVE,
        )

        runtime = DashboardRuntime(
            hub,
            session,
            db=args.db,
            log_file=session_log,
            result_timeout=args.result_timeout,
            detection_control=getattr(source, "set_paused", None),
        )

        if source is not None:
            runtime.feed = VisionFeed(
                source,
                hub.publish,
                record=record,
                on_result=runtime.receive_vision,
            )

        session.announce()

        stop = threading.Event()
        stack.callback(stop.set)
        stack.callback(runtime.stop)

        def heartbeat():
            while not stop.wait(0.25):
                if source is not None and hasattr(source, "status"):
                    status = source.status()
                else:
                    status = offline_system()
                    status["vision"] = {
                        "status": "ok" if source else "down",
                        "model": "Replay" if source else "Off",
                    }

                hub.publish(
                    "system",
                    {
                        **status,
                        "hand_link": {
                            "status": "disconnected",
                            "battery_pct": None,
                        },
                        "emg_source": "keyboard",
                    },
                )

        threading.Thread(
            target=heartbeat,
            daemon=True,
        ).start()

        app = create_app(
            hub,
            dist=args.dist,
            on_key=runtime.key,
            on_control=runtime.control,
            frames=frames,
            on_shutdown=stack.close,
        )

        runtime.start()

        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=args.host,
                port=args.port,
                log_level="info",
            )
        )

        browser_host = (
            "127.0.0.1"
            if args.host == "0.0.0.0"
            else args.host
        )

        actual_port = listener.getsockname()[1]
        url = f"http://{browser_host}:{actual_port}/"

        if not args.no_browser:
            def open_browser():
                while not stop.wait(0.1):
                    if server.started:
                        webbrowser.open(url)
                        return

            threading.Thread(
                target=open_browser,
                daemon=True,
            ).start()

        logging.info(
            "User %s | History %s | Session %s | Dashboard %s",
            args.user,
            args.db,
            log_path,
            url,
        )

        server.run(sockets=[listener])


if __name__ == "__main__":
    main()