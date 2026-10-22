"""Serve the CAVIA dashboard: python -m cavia.server

Open http://127.0.0.1:8000 after building the UI (cd src/dashboard/web && npm run build),
or use the Vite dev server with http://localhost:5173/?live=1.

Vision:  --vision live                      run objdet.py with the camera (needs the vision extra)
         --vision live --record-vision F    ...and save every tracker result to F (JSONL)
         --replay F                         play a recording instead of a camera
"""

from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

from cavia.core.contracts import Condition

from .app import create_app
from .hub import Hub
from .session import Session
from .vision_feed import ReplayVision, VisionFeed

DIST = Path(__file__).resolve().parents[2] / "dashboard" / "web" / "dist"
OBJDET = Path(__file__).resolve().parents[1] / "vision" / "objdet.py"


def offline_system() -> dict:
    """System status before any camera, vision or hand link is wired in."""
    return {
        "camera": {"status": "down", "source": "XIAO", "fps": 0.0, "latency_ms": 0},
        "vision": {"status": "down", "model": "not running"},
        "hand_link": {"status": "disconnected", "battery_pct": None},
        "emg_source": "keyboard",
    }


def system_status(feed: VisionFeed | None) -> dict:
    system = offline_system()
    if feed is not None:
        system.update(feed.status())
    return system


def start_heartbeat(hub: Hub, stop: threading.Event, feed: VisionFeed | None = None,
                    period: float = 1.0) -> threading.Thread:
    def run() -> None:
        while not stop.wait(period):
            hub.publish("system", system_status(feed))

    thread = threading.Thread(target=run, name="system-heartbeat", daemon=True)
    thread.start()
    return thread


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open it from another device")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--participant", default="P01")
    parser.add_argument("--condition", default=Condition.C3_ADAPTIVE.value, choices=[c.value for c in Condition])
    parser.add_argument("--dist", type=Path, default=DIST, help="built dashboard directory")
    parser.add_argument("--vision", choices=["off", "live"], default="off",
                        help="live: run objdet.py with the camera")
    parser.add_argument("--replay", type=Path, help="play recorded vision results (JSONL) instead")
    parser.add_argument("--record-vision", type=Path, help="save every vision result to this JSONL file")
    args = parser.parse_args(argv)
    if args.replay and args.vision == "live":
        parser.error("--replay and --vision live are alternatives")

    try:
        import uvicorn
    except ImportError:
        raise SystemExit('Install the server dependencies: pip install -e ".[dashboard]"')

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    hub = Hub()
    session = Session(hub.publish, participant=args.participant, condition=Condition(args.condition))

    source = None
    if args.replay:
        source = ReplayVision(args.replay)
        logging.info("Replaying vision results from %s", args.replay)
    elif args.vision == "live":
        from cavia.runtime.vision_link import VisionProcess

        source = VisionProcess(OBJDET)
        source.start()
        logging.info("Started vision: %s", OBJDET)

    record = None
    if args.record_vision:
        args.record_vision.parent.mkdir(parents=True, exist_ok=True)
        record = args.record_vision.open("w", encoding="utf-8", buffering=1)
        logging.info("Recording vision results to %s", args.record_vision)
    feed = VisionFeed(source, hub.publish, record=record) if source is not None else None

    hub.publish("system", system_status(feed))
    session.announce()

    app = create_app(hub, dist=args.dist, on_control=session.control)
    if not (args.dist / "index.html").is_file():
        logging.warning("No dashboard build at %s; run npm run build in src/dashboard/web", args.dist)

    stop = threading.Event()
    start_heartbeat(hub, stop, feed)
    if feed is not None:
        feed.start()
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        stop.set()
        if feed is not None:
            feed.stop()
        if hasattr(source, "close"):
            source.close()
        if record is not None:
            record.close()


if __name__ == "__main__":
    main()
