from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .bluez import BlueZMonitor
from .network import LanMonitor
from .state import TelemetryState

DEFAULT_DEVICE = "EC:B5:50:2E:16:9C"
STATIC_DIR = Path(__file__).with_name("static")


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.state = TelemetryState(address=os.getenv("BLUETOOTH_DEVICE", DEFAULT_DEVICE))
        self.monitor = self.create_monitor()
        self.lan_monitor = LanMonitor(self.state, self.broadcast)
        self.error: str | None = None

    def create_monitor(self) -> BlueZMonitor:
        return BlueZMonitor(self.state.address, self.state, self.broadcast)

    async def broadcast(self, state: TelemetryState) -> None:
        await self._broadcast_payload(json.dumps({"type": "telemetry", "data": state.to_dict()}))

    async def broadcast_error(self, message: str) -> None:
        await self._broadcast_payload(json.dumps({"type": "error", "message": message}))

    async def _broadcast_payload(self, payload: str) -> None:
        clients = tuple(self.clients)

        async def send(client: WebSocket) -> WebSocket | None:
            try:
                await asyncio.wait_for(client.send_text(payload), timeout=1.5)
                return None
            except Exception:
                return client

        dead = await asyncio.gather(*(send(client) for client in clients))
        for client in dead:
            if client is None:
                continue
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
    retry_delay = 2.0
    while True:
        try:
            await hub.monitor.start()
            hub.error = None
            hub.state.monitor_status = "ready"
            hub.state.touch("monitor-ready")
            await hub.broadcast(hub.state)
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            hub.error = str(exc)
            hub.state.monitor_status = "error"
            hub.state.touch("monitor-error")
            await hub.broadcast(hub.state)
            await hub.broadcast_error(hub.error)
            await hub.monitor.close()
            await asyncio.sleep(retry_delay)
            retry_delay = min(30.0, retry_delay * 2)
            hub.monitor = hub.create_monitor()


app = FastAPI(title="Bluetooth HUD", version="0.3.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=FileResponse)
async def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/state")
async def get_state() -> JSONResponse:
    return JSONResponse({"state": hub.state.to_dict(), "error": hub.error})


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "ok": hub.error is None and hub.state.monitor_status == "ready",
        "device": hub.state.address,
        "connected": hub.state.connected,
        "monitor_status": hub.state.monitor_status,
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
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
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
