from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from swarm_sim.runtime import SimulationRuntime


def _cors_origins() -> list[str]:
    configured = os.environ.get("SWARM_CORS_ORIGINS")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def index() -> JSONResponse:
        return JSONResponse(
            {
                "service": "swarm-sim",
                "status": "ok",
                "ui": "Use the Next.js frontend for visualization.",
                "docs": "/docs",
                "state": "/api/state",
                "ws": "/ws",
                "config": "/api/config",
                "metrics": "/metrics",
                "cors_origins": _cors_origins(),
            }
        )

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
