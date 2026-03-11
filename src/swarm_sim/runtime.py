from __future__ import annotations

import asyncio
import contextlib
import multiprocessing as mp
import queue
import time
from dataclasses import asdict
from itertools import count
from typing import Any

import msgpack
from fastapi import WebSocket

from swarm_sim.simulator import SwarmConfig, SwarmMetrics, SwarmSimulator


def _pack_message(payload: dict[str, Any]) -> bytes:
    return msgpack.packb(payload, use_bin_type=True)


def _unpack_message(payload: bytes) -> dict[str, Any]:
    return msgpack.unpackb(payload, raw=False)


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
            state_queue.put(_pack_message({"kind": "frame", "payload": latest_snapshot}))


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
        self.pending: dict[int, asyncio.Future[Any]] = {}
        self.request_ids = count(1)
        self.reader_task: asyncio.Task[None] | None = None
        self.metrics = SwarmMetrics()
        self.last_collision_total = 0
        self.last_completion_total = 0
        self.latest_snapshot = SwarmSimulator(config=self.config, seed=self.seed).snapshot()
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
            packed_message = await asyncio.to_thread(self.state_queue.get)
            message = _unpack_message(packed_message)
            kind = message["kind"]

            if kind == "frame":
                self.latest_snapshot = message["payload"]
                self._observe_snapshot(self.latest_snapshot)
                await self.broadcast(self.latest_snapshot)
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
                self.latest_snapshot = response
                self._observe_snapshot(self.latest_snapshot)
                await self.broadcast(self.latest_snapshot)
            elif "snapshot" in response and isinstance(response["snapshot"], dict):
                self.latest_snapshot = response["snapshot"]
                self._observe_snapshot(self.latest_snapshot)
                await self.broadcast(self.latest_snapshot)

        return response

    async def snapshot(self) -> dict[str, Any]:
        return self.latest_snapshot

    async def reset(self) -> dict[str, Any]:
        return await self.request("reset")

    async def pause(self) -> dict[str, bool]:
        return await self.request("pause")

    async def resume(self) -> dict[str, bool]:
        return await self.request("resume")

    async def inject_random_failure(self) -> dict[str, Any]:
        return await self.request("fail-random")

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.add(websocket)
        await websocket.send_json(self.latest_snapshot)

    def disconnect(self, websocket: WebSocket) -> None:
        self.clients.discard(websocket)

    async def broadcast(self, snapshot: dict[str, Any]) -> None:
        stale_clients: list[WebSocket] = []
        for client in list(self.clients):
            try:
                await client.send_json(snapshot)
            except RuntimeError:
                stale_clients.append(client)
        for client in stale_clients:
            self.disconnect(client)

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
