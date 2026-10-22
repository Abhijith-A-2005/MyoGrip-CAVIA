"""FastAPI app: dashboard WebSocket, health check and the built dashboard UI."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .frames import FrameReceiver
from .hub import Hub

log = logging.getLogger(__name__)

GESTURE_KEYS = frozenset("wasde")
BOUNDARY = "frame"
STREAM_IDLE_S = 5.0     # end the stream if no new frame arrives for this long
STREAM_POLL_S = 0.015

KeyHandler = Callable[[str, bool], None]
ControlHandler = Callable[[dict], None]


def parse_client_message(msg: object) -> tuple[str, dict] | None:
    """Validate a browser message. Returns (kind, data) or None if it should be ignored."""
    if not isinstance(msg, dict) or not isinstance(msg.get("data"), dict):
        return None
    kind, data = msg.get("type"), msg["data"]
    if kind == "key":
        if data.get("key") in GESTURE_KEYS and isinstance(data.get("down"), bool):
            return kind, {"key": data["key"], "down": data["down"]}
        return None
    if kind == "control" and isinstance(data.get("action"), str):
        return kind, data
    return None


def create_app(
    hub: Hub,
    *,
    dist: Path | None = None,
    on_key: KeyHandler | None = None,
    on_control: ControlHandler | None = None,
    frames: FrameReceiver | None = None,
    on_shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    """`on_key` and `on_control` run on the server thread; keep them short and thread-safe.

    `on_shutdown` runs in the app's shutdown phase. Uvicorn re-raises SIGTERM/SIGINT only after
    that phase, so this is the one place cleanup (e.g. stopping the vision process) always runs.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        hub.bind(asyncio.get_running_loop())
        try:
            yield
        finally:
            if on_shutdown is not None:
                on_shutdown()

    app = FastAPI(title="MyoGrip CAVIA", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "clients": hub.client_count}

    @app.get("/video", response_model=None)
    def video() -> JSONResponse | StreamingResponse:
        if frames is None or frames.latest() is None:
            return JSONResponse({"detail": "No camera frames yet"}, status_code=503)
        return StreamingResponse(
            mjpeg(frames),
            media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store"},
        )

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        queue = hub.add_client()
        try:
            await socket.send_json({"type": "snapshot", "data": hub.snapshot()})
            sender = asyncio.create_task(_pump(socket, queue))
            try:
                while True:
                    parsed = parse_client_message(await socket.receive_json())
                    if parsed is None:
                        continue
                    kind, data = parsed
                    try:
                        if kind == "key" and on_key:
                            on_key(data["key"], data["down"])
                        elif kind == "control" and on_control:
                            on_control(data)
                    except ValueError as err:
                        log.info("Rejected %s from dashboard: %s", kind, err)
            finally:
                sender.cancel()
        except (WebSocketDisconnect, ValueError):
            pass  # closed by the browser, or it sent something that is not JSON
        finally:
            hub.remove_client(queue)

    if dist is not None and (dist / "index.html").is_file():
        # Mounted last so /ws, /health and /video take precedence.
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    else:
        @app.get("/")
        def no_build() -> JSONResponse:
            return JSONResponse(
                {"detail": "Dashboard not built. Run: cd src/dashboard/web && npm run build"},
                status_code=503,
            )

    return app


async def _pump(socket: WebSocket, queue: asyncio.Queue) -> None:
    while True:
        await socket.send_json(await queue.get())


def mjpeg_part(jpeg: bytes) -> bytes:
    head = f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n"
    return head.encode() + jpeg + b"\r\n"


async def mjpeg(frames: FrameReceiver, idle_s: float | None = None):
    """Each new frame once, as an MJPEG part. Ends if frames stop, so a frozen picture never lingers."""
    idle_s = STREAM_IDLE_S if idle_s is None else idle_s
    last_seq, last_new = -1, asyncio.get_running_loop().time()
    while True:
        frame = frames.latest()
        now = asyncio.get_running_loop().time()
        if frame is not None and frame.seq != last_seq:
            last_seq, last_new = frame.seq, now
            yield mjpeg_part(frame.jpeg)
        elif now - last_new > idle_s:
            return
        await asyncio.sleep(STREAM_POLL_S)
