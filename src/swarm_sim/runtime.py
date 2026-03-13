from __future__ import annotations

import asyncio
import contextlib
import multiprocessing as mp
import queue
import time
from dataclasses import asdict
from itertools import count
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from swarm_sim.simulator import SwarmConfig, SwarmMetrics, SwarmSimulator
from swarm_sim.transport import (
    dump_websocket_json_text,
    json_backend_name,
    pack_msgpack,
    unpack_msgpack,
)


def _pack_message(payload: dict[str, Any]) -> bytes:
    return pack_msgpack(payload)


def _unpack_message(payload: bytes) -> dict[str, Any]:
    return unpack_msgpack(payload)


def _worker_main(
    command_queue: mp.Queue[bytes],
    state_queue: mp.Queue[bytes],
    config_data: dict[str, Any],
    seed: int,
) -> None:
    simulator = SwarmSimulator(config=SwarmConfig(**config_data), seed=seed)
    running = True
    next_tick_at = time.perf_counter()
    max_catchup_steps = 8

    while True:
        try:
            while True:
                command_message = command_queue.get_nowait()
                command = _unpack_message(command_message)
                request_id = command["request_id"]
                name = command["command"]

                if name == "shutdown":
                    state_queue.put(
                        _pack_message(
                            {"kind": "response", "request_id": request_id, "payload": {"ok": True}}
                        )
                    )
                    return
                if name == "snapshot":
                    payload = simulator.snapshot()
                elif name == "reset":
                    payload = simulator.reset(seed=command.get("seed"))
                elif name == "pause":
                    running = False
                    payload = {"running": False}
                elif name == "resume":
                    running = True
                    next_tick_at = time.perf_counter() + simulator.config.tick_seconds
                    payload = {"running": True}
                elif name == "configure":
                    payload = {
                        "config": simulator.update_config(
                            tick_seconds=command.get("tick_seconds"),
                            render_stride=command.get("render_stride"),
                        ),
                        "snapshot": simulator.snapshot(),
                    }
                    if running:
                        next_tick_at = time.perf_counter() + simulator.config.tick_seconds
                elif name == "fail-random":
                    failed_drone_id = simulator.inject_random_failure()
                    payload = {
                        "failed_drone_id": failed_drone_id,
                        "snapshot": simulator.snapshot(),
                    }
                else:
                    payload = {"error": f"Unsupported command {name!r}"}

                state_queue.put(
                    _pack_message(
                        {"kind": "response", "request_id": request_id, "payload": payload}
                    )
                )
        except queue.Empty:
            pass

        if not running:
            time.sleep(0.001)
            continue

        now = time.perf_counter()
        if now < next_tick_at:
            time.sleep(min(0.001, next_tick_at - now))
            continue

        latest_snapshot: dict[str, Any] | None = None
        catchup_steps = 0
        while now >= next_tick_at and catchup_steps < max_catchup_steps:
            latest_snapshot = simulator.step()
            catchup_steps += 1
            next_tick_at += simulator.config.tick_seconds
            now = time.perf_counter()

        if latest_snapshot is not None and latest_snapshot["tick"] % simulator.config.render_stride == 0:
            state_queue.put(
                _pack_message(
                    {"kind": "frame", "payload_msgpack": pack_msgpack(latest_snapshot)}
                )
            )


class SimulationRuntime:
    def __init__(
        self,
        *,
        config: SwarmConfig | None = None,
        seed: int = 7,
    ) -> None:
        self.config = config or SwarmConfig()
        self.seed = seed
        self.ctx = mp.get_context("spawn")
        self.command_queue: mp.Queue[bytes] = self.ctx.Queue()
        self.state_queue: mp.Queue[bytes] = self.ctx.Queue()
        self.process = self.ctx.Process(
            target=_worker_main,
            args=(self.command_queue, self.state_queue, asdict(self.config), self.seed),
            daemon=True,
        )
        self.clients: set[WebSocket] = set()
        self.client_encodings: dict[WebSocket, str] = {}
        self.pending: dict[int, asyncio.Future[Any]] = {}
        self.request_ids = count(1)
        self.reader_task: asyncio.Task[None] | None = None
        self.metrics = SwarmMetrics()
        self.last_collision_total = 0
        self.last_completion_total = 0
        self.latest_snapshot = SwarmSimulator(config=self.config, seed=self.seed).snapshot()
        self.latest_snapshot_json = dump_websocket_json_text(self.latest_snapshot)
        self.latest_snapshot_msgpack = pack_msgpack(self.latest_snapshot)
        self.websocket_json_backend = json_backend_name()
        self._observe_snapshot(self.latest_snapshot)

    async def start(self) -> None:
        self.process.start()
        self.reader_task = asyncio.create_task(self._reader_loop())
        self.latest_snapshot = await self.request("snapshot")
        self._observe_snapshot(self.latest_snapshot)

    async def stop(self) -> None:
        if self.process.is_alive():
            await self.request("shutdown")
            await asyncio.to_thread(self.process.join, 3.0)
        if self.reader_task is not None:
            self.reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader_task

    async def _reader_loop(self) -> None:
        while True:
            try:
                packed_message = await asyncio.to_thread(self.state_queue.get, True, 0.25)
            except queue.Empty:
                continue
            message = _unpack_message(packed_message)
            kind = message["kind"]

            if kind == "frame":
                packed_snapshot = message["payload_msgpack"]
                snapshot = unpack_msgpack(packed_snapshot)
                self._cache_snapshot(snapshot, packed_snapshot)
                self._observe_snapshot(self.latest_snapshot)
                await self.broadcast()
                continue

            request_id = int(message["request_id"])
            future = self.pending.pop(request_id, None)
            if future is None or future.done():
                continue
            future.set_result(message["payload"])

    async def request(self, command: str, **payload: Any) -> Any:
        request_id = next(self.request_ids)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self.pending[request_id] = future
        await asyncio.to_thread(
            self.command_queue.put,
            _pack_message({"request_id": request_id, "command": command, **payload}),
        )
        response = await future

        if isinstance(response, dict):
            if "tick" in response:
                self._cache_snapshot(response)
                self._observe_snapshot(self.latest_snapshot)
                await self.broadcast()
            elif "snapshot" in response and isinstance(response["snapshot"], dict):
                self._cache_snapshot(response["snapshot"])
                if "config" in response and isinstance(response["config"], dict):
                    self.config = SwarmConfig(**response["config"])
                self._observe_snapshot(self.latest_snapshot)
                await self.broadcast()

        return response

    async def snapshot(self) -> dict[str, Any]:
        return self.latest_snapshot

    async def reset(self) -> dict[str, Any]:
        return await self.request("reset")

    async def current_config(self) -> dict[str, Any]:
        return self.config.as_dict()

    async def update_config(
        self,
        *,
        tick_seconds: float | None = None,
        render_stride: int | None = None,
    ) -> dict[str, Any]:
        response = await self.request(
            "configure",
            tick_seconds=tick_seconds,
            render_stride=render_stride,
        )
        if isinstance(response, dict) and "config" in response and isinstance(response["config"], dict):
            self.config = SwarmConfig(**response["config"])
            return response["config"]
        raise RuntimeError("Worker did not return an updated config payload.")

    async def pause(self) -> dict[str, bool]:
        return await self.request("pause")

    async def resume(self) -> dict[str, bool]:
        return await self.request("resume")

    async def inject_random_failure(self) -> dict[str, Any]:
        return await self.request("fail-random")

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.add(websocket)
        encoding = websocket.query_params.get("encoding", "json").lower()
        if encoding not in {"json", "msgpack"}:
            encoding = "json"
        self.client_encodings[websocket] = encoding
        await self._send_snapshot(websocket, encoding)

    def disconnect(self, websocket: WebSocket) -> None:
        self.clients.discard(websocket)
        self.client_encodings.pop(websocket, None)

    async def broadcast(self) -> None:
        stale_clients: list[WebSocket] = []
        for client in list(self.clients):
            try:
                await self._send_snapshot(client, self.client_encodings.get(client, "json"))
            except (RuntimeError, WebSocketDisconnect):
                stale_clients.append(client)
        for client in stale_clients:
            self.disconnect(client)

    async def _send_snapshot(self, websocket: WebSocket, encoding: str) -> None:
        if encoding == "msgpack":
            await websocket.send_bytes(self.latest_snapshot_msgpack)
            return
        await websocket.send_text(self.latest_snapshot_json)

    def _cache_snapshot(self, snapshot: dict[str, Any], packed_snapshot: bytes | None = None) -> None:
        self.latest_snapshot = snapshot
        self.latest_snapshot_msgpack = packed_snapshot or pack_msgpack(snapshot)
        self.latest_snapshot_json = dump_websocket_json_text(snapshot)
        config_data = snapshot.get("config")
        if isinstance(config_data, dict):
            self.config = SwarmConfig(**config_data)

    def _observe_snapshot(self, snapshot: dict[str, Any]) -> None:
        summary = snapshot.get("summary")
        if not isinstance(summary, dict):
            return
        self.metrics.observe_summary(summary)
        collision_total = int(summary.get("collision_events_total", 0))
        completion_total = int(summary.get("waypoint_completions", 0))
        self.metrics.record_collisions(max(0, collision_total - self.last_collision_total))
        self.metrics.record_completions(max(0, completion_total - self.last_completion_total))
        self.last_collision_total = collision_total
        self.last_completion_total = completion_total
