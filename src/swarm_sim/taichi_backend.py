import os
import tempfile
from typing import Any, Optional

import numpy as np

try:
    import taichi as ti
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    ti = None  # type: ignore[assignment]


_TAICHI_INITIALIZED = False


def taichi_available() -> bool:
    return ti is not None


def _ensure_taichi() -> None:
    global _TAICHI_INITIALIZED
    if _TAICHI_INITIALIZED or ti is None:
        return

    os.environ.setdefault(
        "TI_CACHE_PATH",
        os.path.join(tempfile.gettempdir(), "swarm-taichi-cache"),
    )

    last_error: Optional[Exception] = None
    preferred_arch = os.environ.get("SWARM_TAICHI_ARCH", "cpu").lower()
    if preferred_arch == "gpu":
        arch_order = (ti.gpu, ti.cpu)
    elif preferred_arch == "cpu":
        arch_order = (ti.cpu,)
    else:
        arch_order = (ti.cpu, ti.gpu)

    for arch in arch_order:
        try:
            ti.init(arch=arch, offline_cache=True)
            _TAICHI_INITIALIZED = True
            return
        except Exception as error:  # pragma: no cover - backend selection is environment-specific
            last_error = error

    raise RuntimeError("Unable to initialize Taichi.") from last_error


@ti.data_oriented
class TaichiBoidsBackend:
    def __init__(self, agent_count: int) -> None:
        if ti is None:
            raise RuntimeError(
                "Taichi backend requested but taichi is not installed. Install the gpu extra."
            )
        _ensure_taichi()
        self.agent_count = agent_count
        self.positions = ti.Vector.field(2, dtype=ti.f32, shape=agent_count)
        self.velocities = ti.Vector.field(2, dtype=ti.f32, shape=agent_count)
        self.target_points = ti.Vector.field(2, dtype=ti.f32, shape=agent_count)
        self.active_mask = ti.field(dtype=ti.i32, shape=agent_count)
        self.next_positions = ti.Vector.field(2, dtype=ti.f32, shape=agent_count)
        self.next_velocities = ti.Vector.field(2, dtype=ti.f32, shape=agent_count)

    @ti.kernel
    def _step_kernel(
        self,
        dt: ti.f32,
        max_speed: ti.f32,
        neighbor_radius: ti.f32,
        separation_radius: ti.f32,
        width: ti.f32,
        height: ti.f32,
        separation_weight: ti.f32,
        alignment_weight: ti.f32,
        cohesion_weight: ti.f32,
        waypoint_weight: ti.f32,
        boundary_weight: ti.f32,
    ):
        margin = ti.f32(90.0)
        for agent_index in range(self.agent_count):
            if self.active_mask[agent_index] == 0:
                self.next_positions[agent_index] = self.positions[agent_index]
                self.next_velocities[agent_index] = self.velocities[agent_index]
                continue

            separation = ti.Vector([0.0, 0.0])
            alignment = ti.Vector([0.0, 0.0])
            cohesion_sum = ti.Vector([0.0, 0.0])
            neighbor_count = 0

            for other_index in range(self.agent_count):
                if agent_index == other_index or self.active_mask[other_index] == 0:
                    continue
                offset = self.positions[agent_index] - self.positions[other_index]
                distance = offset.norm() + 1e-5
                if distance <= neighbor_radius:
                    neighbor_count += 1
                    cohesion_sum += self.positions[other_index]
                    alignment += self.velocities[other_index]
                    if distance <= separation_radius:
                        separation += offset / (distance * distance + 1e-5)

            cohesion = ti.Vector([0.0, 0.0])
            if neighbor_count > 0:
                cohesion = cohesion_sum / neighbor_count - self.positions[agent_index]
                alignment = alignment / neighbor_count - self.velocities[agent_index]

            target_offset = self.target_points[agent_index] - self.positions[agent_index]
            target_distance = target_offset.norm() + 1e-5
            target_force = ti.Vector([0.0, 0.0])
            if target_distance > 1e-4:
                target_force = (
                    target_offset.normalized()
                    * ti.min(target_distance / ti.f32(55.0), ti.f32(3.0))
                )

            boundary = ti.Vector([0.0, 0.0])
            if self.positions[agent_index].x < margin:
                boundary.x += (margin - self.positions[agent_index].x) / margin
            elif self.positions[agent_index].x > width - margin:
                boundary.x -= (self.positions[agent_index].x - (width - margin)) / margin
            if self.positions[agent_index].y < margin:
                boundary.y += (margin - self.positions[agent_index].y) / margin
            elif self.positions[agent_index].y > height - margin:
                boundary.y -= (self.positions[agent_index].y - (height - margin)) / margin

            total = (
                separation * separation_weight
                + alignment * alignment_weight
                + cohesion * cohesion_weight
                + target_force * waypoint_weight
                + boundary * boundary_weight
            )

            velocity = self.velocities[agent_index] + total * dt
            speed = velocity.norm()
            if speed > max_speed:
                velocity = velocity.normalized() * max_speed

            position = self.positions[agent_index] + velocity * dt
            position.x = ti.max(ti.f32(20.0), ti.min(width - ti.f32(20.0), position.x))
            position.y = ti.max(ti.f32(20.0), ti.min(height - ti.f32(20.0), position.y))

            self.next_positions[agent_index] = position
            self.next_velocities[agent_index] = velocity

        for agent_index in range(self.agent_count):
            self.positions[agent_index] = self.next_positions[agent_index]
            self.velocities[agent_index] = self.next_velocities[agent_index]

    def step(
        self,
        *,
        positions: np.ndarray,
        velocities: np.ndarray,
        target_points: np.ndarray,
        active_mask: np.ndarray,
        config: Any,
    ) -> None:
        self.positions.from_numpy(positions.astype(np.float32))
        self.velocities.from_numpy(velocities.astype(np.float32))
        self.target_points.from_numpy(target_points.astype(np.float32))
        self.active_mask.from_numpy(active_mask.astype(np.int32))
        self._step_kernel(
            float(config.tick_seconds),
            float(config.max_speed),
            float(config.neighbor_radius),
            float(config.separation_radius),
            float(config.width),
            float(config.height),
            float(config.separation_weight),
            float(config.alignment_weight),
            float(config.cohesion_weight),
            float(config.waypoint_weight),
            float(config.boundary_weight),
        )
        positions[:] = self.positions.to_numpy()
        velocities[:] = self.velocities.to_numpy()
