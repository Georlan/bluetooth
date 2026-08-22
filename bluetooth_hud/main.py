from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from .bluez import BlueZMonitor
from .network import LanMonitor
from .state import TelemetryState

DEFAULT_DEVICE = "EC:B5:50:2E:16:9C"
STATIC_DIR = Path(__file__).with_name("static")


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.state = TelemetryState(address=os.getenv("BLUETOOTH_DEVICE", DEFAULT_DEVICE))
        self.monitor = BlueZMonitor(self.state.address, self.state, self.broadcast)
        self.lan_monitor = LanMonitor(self.state, self.broadcast)
        self.error: str | None = None

    async def broadcast(self, state: TelemetryState) -> None:
        payload = json.dumps({"type": "telemetry", "data": state.to_dict()})
        dead: list[WebSocket] = []
        for client in tuple(self.clients):
            try:
                await client.send_text(payload)
            except Exception:
                dead.append(client)
        for client in dead:
            self.clients.discard(client)

    async def send_snapshot(self, client: WebSocket) -> None:
        await client.send_json({"type": "telemetry", "data": self.state.to_dict()})
        if self.error:
            await client.send_json({"type": "error", "message": self.error})


hub = Hub()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    monitor_task = asyncio.create_task(_run_monitor())
    await hub.lan_monitor.start()
    try:
        yield
    finally:
        monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
        await hub.monitor.close()
        await hub.lan_monitor.close()


async def _run_monitor() -> None:
    try:
        await hub.monitor.start()
    except Exception as exc:
        hub.error = str(exc)
        hub.state.touch("monitor-error")
        await hub.broadcast(hub.state)


app = FastAPI(title="Bluetooth HUD", version="0.2.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/state")
async def get_state() -> JSONResponse:
    return JSONResponse({"state": hub.state.to_dict(), "error": hub.error})


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "ok": hub.error is None,
        "device": hub.state.address,
        "connected": hub.state.connected,
        "lan_target_ip": hub.state.lan_target_ip,
        "lan_present": hub.state.lan_present,
        "lan_target_mode": hub.state.lan_target_mode,
        "error": hub.error,
    })


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    hub.clients.add(websocket)
    await hub.send_snapshot(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(websocket)


def run() -> None:
    import uvicorn

    host = os.getenv("BLUETOOTH_HOST", "127.0.0.1")
    port = int(os.getenv("BLUETOOTH_PORT", "8765"))
    uvicorn.run("bluetooth_hud.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
