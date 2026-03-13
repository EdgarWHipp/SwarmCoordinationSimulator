from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from prometheus_client import make_asgi_app

from swarm_sim.runtime import SimulationRuntime


STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    runtime = SimulationRuntime()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.start()
        app.state.runtime = runtime
        try:
            yield
        finally:
            with suppress(asyncio.CancelledError):
                await runtime.stop()

    app = FastAPI(
        title="Swarm Coordination Simulator",
        version="0.2.0",
        lifespan=lifespan,
    )

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {"service": "swarm-sim", "status": "ok", "docs": "/docs", "ws": "/ws", "config": "/api/config"}
        )

    @app.get("/api/state")
    async def get_state() -> JSONResponse:
        return JSONResponse(await runtime.snapshot())

    @app.post("/api/reset")
    async def reset() -> JSONResponse:
        return JSONResponse(await runtime.reset())

    @app.post("/api/pause")
    async def pause() -> JSONResponse:
        return JSONResponse(await runtime.pause())

    @app.post("/api/resume")
    async def resume() -> JSONResponse:
        return JSONResponse(await runtime.resume())

    @app.post("/api/fail-random")
    async def fail_random() -> JSONResponse:
        return JSONResponse(await runtime.inject_random_failure())

    @app.get("/api/config")
    async def get_config() -> JSONResponse:
        return JSONResponse(
            {
                "config": await runtime.current_config(),
                "websocket_json_backend": runtime.websocket_json_backend,
                "websocket_encodings": ["json", "msgpack"],
            }
        )

    @app.post("/api/config")
    async def update_config(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        config = await runtime.update_config(
            tick_seconds=payload.get("tick_seconds"),
            render_stride=payload.get("render_stride"),
        )
        return JSONResponse(
            {
                "config": config,
                "websocket_json_backend": runtime.websocket_json_backend,
                "websocket_encodings": ["json", "msgpack"],
            }
        )

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await runtime.connect(websocket)
        try:
            while True:
                await websocket.receive()
        except WebSocketDisconnect:
            runtime.disconnect(websocket)

    app.mount("/metrics", make_asgi_app(registry=runtime.metrics.registry))
    return app


app = create_app()


def main() -> None:
    uvicorn.run("swarm_sim.server:app", host="127.0.0.1", port=8000, reload=False)
