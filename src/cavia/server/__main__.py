"""Serve the CAVIA dashboard: python -m cavia.server

Open http://127.0.0.1:8000 after building the UI (cd src/dashboard/web && npm run build),
or use the Vite dev server with http://localhost:5173/?live=1.
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

DIST = Path(__file__).resolve().parents[2] / "dashboard" / "web" / "dist"


def offline_system() -> dict:
    """System status before any camera, vision or hand link is wired in."""
    return {
        "camera": {"status": "down", "source": "XIAO", "fps": 0.0, "latency_ms": 0},
        "vision": {"status": "down", "model": "not running"},
        "hand_link": {"status": "disconnected", "battery_pct": None},
        "emg_source": "keyboard",
    }


def start_heartbeat(hub: Hub, stop: threading.Event, period: float = 1.0) -> threading.Thread:
    def run() -> None:
        while not stop.wait(period):
            hub.publish("system", offline_system())

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
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        raise SystemExit('Install the server dependencies: pip install -e ".[dashboard]"')

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    hub = Hub()
    session = Session(hub.publish, participant=args.participant, condition=Condition(args.condition))
    hub.publish("system", offline_system())
    session.announce()

    app = create_app(hub, dist=args.dist, on_control=session.control)
    if not (args.dist / "index.html").is_file():
        logging.warning("No dashboard build at %s; run npm run build in src/dashboard/web", args.dist)

    stop = threading.Event()
    start_heartbeat(hub, stop)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
