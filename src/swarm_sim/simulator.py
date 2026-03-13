from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from numba import njit
from scipy.spatial import cKDTree

from swarm_sim.navigation import NavigationGraph
from swarm_sim.raft import RaftCoordinator
from swarm_sim.swarmraft import SwarmRaftConfig, SwarmRaftLocalizer

if TYPE_CHECKING:
    from swarm_sim.taichi_backend import TaichiBoidsBackend

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge
except ModuleNotFoundError:
    class CollectorRegistry:  # type: ignore[no-redef]
        def __init__(self, auto_describe: bool = True) -> None:
            self.auto_describe = auto_describe


    class _Metric:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.value = 0.0

        def set(self, value: float) -> None:
            self.value = value

        def inc(self, amount: float = 1.0) -> None:
            self.value += amount


    class Counter(_Metric):  # type: ignore[no-redef]
        pass


    class Gauge(_Metric):  # type: ignore[no-redef]
        pass


EPSILON = np.float32(1e-5)
SUPPORTED_ASSIGNMENT_STRATEGIES = ("raft", "swarmraft", "consensus", "greedy")


@dataclass(slots=True)
class SwarmConfig:
    width: int = 1280
    height: int = 720
    drone_count: int = 8
    waypoint_count: int = 8
    tick_seconds: float = 0.08
    planning_interval: int = 6
    render_stride: int = 4
    assignment_strategy: str = "raft"
    physics_backend: str = "numpy"
    max_speed: float = 85.0
    neighbor_radius: float = 150.0
    communication_radius: float = 260.0
    separation_radius: float = 68.0
    collision_radius: float = 14.0
    waypoint_capture_radius: float = 22.0
    route_reach_radius: float = 18.0
    navigation_cols: int = 12
    navigation_rows: int = 8
    cohesion_weight: float = 0.1
    alignment_weight: float = 0.12
    separation_weight: float = 3.4
    waypoint_weight: float = 2.6
    boundary_weight: float = 1.1
    failure_tick: int | None = 240
    failure_recovery_ticks: int = 2
    raft_heartbeat_ticks: int = 1
    raft_election_timeout_min_ticks: int = 4
    raft_election_timeout_max_ticks: int = 8
    swarmraft_gnss_noise_std: float = 6.0
    swarmraft_ins_drift_std: float = 1.4
    swarmraft_range_noise_std: float = 4.0
    swarmraft_residual_threshold: float = 18.0
    swarmraft_min_peer_votes: int = 2

    def as_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "drone_count": self.drone_count,
            "waypoint_count": self.waypoint_count,
            "tick_seconds": self.tick_seconds,
            "planning_interval": self.planning_interval,
            "render_stride": self.render_stride,
            "assignment_strategy": self.assignment_strategy,
            "physics_backend": self.physics_backend,
            "max_speed": self.max_speed,
            "neighbor_radius": self.neighbor_radius,
            "communication_radius": self.communication_radius,
            "separation_radius": self.separation_radius,
            "collision_radius": self.collision_radius,
            "waypoint_capture_radius": self.waypoint_capture_radius,
            "route_reach_radius": self.route_reach_radius,
            "navigation_cols": self.navigation_cols,
            "navigation_rows": self.navigation_rows,
            "cohesion_weight": self.cohesion_weight,
            "alignment_weight": self.alignment_weight,
            "separation_weight": self.separation_weight,
            "waypoint_weight": self.waypoint_weight,
            "boundary_weight": self.boundary_weight,
            "failure_tick": self.failure_tick,
            "failure_recovery_ticks": self.failure_recovery_ticks,
            "raft_heartbeat_ticks": self.raft_heartbeat_ticks,
            "raft_election_timeout_min_ticks": self.raft_election_timeout_min_ticks,
            "raft_election_timeout_max_ticks": self.raft_election_timeout_max_ticks,
            "swarmraft_gnss_noise_std": self.swarmraft_gnss_noise_std,
            "swarmraft_ins_drift_std": self.swarmraft_ins_drift_std,
            "swarmraft_range_noise_std": self.swarmraft_range_noise_std,
            "swarmraft_residual_threshold": self.swarmraft_residual_threshold,
            "swarmraft_min_peer_votes": self.swarmraft_min_peer_votes,
        }


class SwarmMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry(auto_describe=True)
        self.active_agents = Gauge(
            "swarm_active_agents",
            "Number of active drones in the swarm.",
            registry=self.registry,
        )
        self.failed_agents = Gauge(
            "swarm_failed_agents",
            "Number of failed drones that have dropped from the swarm.",
            registry=self.registry,
        )
        self.cohesion_score = Gauge(
            "swarm_cohesion_score",
            "Normalized cohesion score based on average distance to centroid.",
            registry=self.registry,
        )
        self.average_speed = Gauge(
            "swarm_average_speed",
            "Average speed of all active drones.",
            registry=self.registry,
        )
        self.consensus_success_ratio = Gauge(
            "swarm_consensus_success_ratio",
            "Fraction of active drones with a committed consensus assignment.",
            registry=self.registry,
        )
        self.dropout_detected = Gauge(
            "swarm_dropout_detected",
            "Binary signal that at least one drone has failed.",
            registry=self.registry,
        )
        self.assignment_changes = Gauge(
            "swarm_assignment_changes",
            "Number of assignment changes accepted in the latest planning round.",
            registry=self.registry,
        )
        self.collision_events_total = Counter(
            "swarm_collision_events_total",
            "Cumulative count of new collision events.",
            registry=self.registry,
        )
        self.waypoint_completions_total = Counter(
            "swarm_waypoint_completions_total",
            "Cumulative count of completed waypoints.",
            registry=self.registry,
        )

    def observe_summary(self, summary: dict[str, Any]) -> None:
        self.active_agents.set(summary["active_agents"])
        self.failed_agents.set(summary["failed_agents"])
        self.cohesion_score.set(summary["cohesion_score"])
        self.average_speed.set(summary["average_speed"])
        self.consensus_success_ratio.set(summary["consensus_success_ratio"])
        self.dropout_detected.set(1 if summary["dropout_detected"] else 0)
        self.assignment_changes.set(summary["assignment_changes"])

    def record_collisions(self, count: int) -> None:
        if count > 0:
            self.collision_events_total.inc(count)

    def record_completions(self, count: int) -> None:
        if count > 0:
            self.waypoint_completions_total.inc(count)


@njit(cache=True)
def _accumulate_neighbor_data(
    agent_count: int,
    pair_left: np.ndarray,
    pair_right: np.ndarray,
    positions: np.ndarray,
    velocities: np.ndarray,
    separation_radius: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    counts = np.zeros(agent_count, dtype=np.int32)
    position_sums = np.zeros((agent_count, 2), dtype=np.float32)
    velocity_sums = np.zeros((agent_count, 2), dtype=np.float32)
    separation = np.zeros((agent_count, 2), dtype=np.float32)
    radius_sq = separation_radius * separation_radius

    for pair_index in range(pair_left.shape[0]):
        left = pair_left[pair_index]
        right = pair_right[pair_index]
        dx = positions[left, 0] - positions[right, 0]
        dy = positions[left, 1] - positions[right, 1]
        distance_sq = dx * dx + dy * dy
        distance = np.sqrt(distance_sq + EPSILON)

        counts[left] += 1
        counts[right] += 1

        position_sums[left, 0] += positions[right, 0]
        position_sums[left, 1] += positions[right, 1]
        position_sums[right, 0] += positions[left, 0]
        position_sums[right, 1] += positions[left, 1]

        velocity_sums[left, 0] += velocities[right, 0]
        velocity_sums[left, 1] += velocities[right, 1]
        velocity_sums[right, 0] += velocities[left, 0]
        velocity_sums[right, 1] += velocities[left, 1]

        if distance_sq <= radius_sq:
            inv_distance_sq = 1.0 / (distance_sq + EPSILON)
            separation[left, 0] += dx * inv_distance_sq
            separation[left, 1] += dy * inv_distance_sq
            separation[right, 0] -= dx * inv_distance_sq
            separation[right, 1] -= dy * inv_distance_sq

    return counts, position_sums, velocity_sums, separation


@njit(cache=True)
def _limit_and_move(
    positions: np.ndarray,
    velocities: np.ndarray,
    active_indices: np.ndarray,
    total_force: np.ndarray,
    dt: float,
    max_speed: float,
    width: float,
    height: float,
) -> None:
    minimum_x = np.float32(20.0)
    minimum_y = np.float32(20.0)
    maximum_x = np.float32(width - 20.0)
    maximum_y = np.float32(height - 20.0)

    for local_index in range(active_indices.shape[0]):
        agent_index = active_indices[local_index]
        velocities[agent_index, 0] += total_force[local_index, 0] * dt
        velocities[agent_index, 1] += total_force[local_index, 1] * dt

        speed_sq = (
            velocities[agent_index, 0] * velocities[agent_index, 0]
            + velocities[agent_index, 1] * velocities[agent_index, 1]
        )
        if speed_sq > max_speed * max_speed:
            scale = max_speed / np.sqrt(speed_sq)
            velocities[agent_index, 0] *= scale
            velocities[agent_index, 1] *= scale

        positions[agent_index, 0] += velocities[agent_index, 0] * dt
        positions[agent_index, 1] += velocities[agent_index, 1] * dt

        if positions[agent_index, 0] < minimum_x:
            positions[agent_index, 0] = minimum_x
        elif positions[agent_index, 0] > maximum_x:
            positions[agent_index, 0] = maximum_x

        if positions[agent_index, 1] < minimum_y:
            positions[agent_index, 1] = minimum_y
        elif positions[agent_index, 1] > maximum_y:
            positions[agent_index, 1] = maximum_y


@njit(cache=True)
def _consensus_votes(
    active_positions: np.ndarray,
    proposals: np.ndarray,
    proposal_scores: np.ndarray,
    communication_radius: float,
) -> np.ndarray:
    active_count = active_positions.shape[0]
    votes = np.zeros(active_count, dtype=np.int32)
    radius_sq = communication_radius * communication_radius

    for voter in range(active_count):
        best_candidate = -1
        best_score = -1e9
        for candidate in range(active_count):
            dx = active_positions[voter, 0] - active_positions[candidate, 0]
            dy = active_positions[voter, 1] - active_positions[candidate, 1]
            if voter != candidate and (dx * dx + dy * dy) > radius_sq:
                continue
            candidate_score = proposal_scores[candidate]
            if (
                candidate_score > best_score
                or (
                    candidate_score == best_score
                    and best_candidate >= 0
                    and candidate < best_candidate
                )
                or best_candidate < 0
            ):
                best_candidate = candidate
                best_score = candidate_score
        if best_candidate >= 0:
            votes[best_candidate] += 1

    return votes


@njit(cache=True)
def _resolve_consensus_assignments(
    proposals: np.ndarray,
    proposal_scores: np.ndarray,
    votes: np.ndarray,
    score_matrix: np.ndarray,
    waypoint_count: int,
) -> tuple[np.ndarray, int, int]:
    active_count = proposals.shape[0]
    assignments = np.full(active_count, -1, dtype=np.int32)
    agent_taken = np.zeros(active_count, dtype=np.uint8)
    waypoint_taken = np.zeros(waypoint_count, dtype=np.uint8)
    committed_count = 0
    contention_count = 0
    quorum = max(1, (active_count + 1) // 2)

    proposal_counts = np.zeros(waypoint_count, dtype=np.int32)
    for local_index in range(active_count):
        proposal_counts[proposals[local_index]] += 1

    for waypoint_index in range(waypoint_count):
        if proposal_counts[waypoint_index] > 1:
            contention_count += 1

    while True:
        best_agent = -1
        best_votes = -1
        best_score = -1e9
        for local_index in range(active_count):
            if agent_taken[local_index]:
                continue
            waypoint_index = proposals[local_index]
            if waypoint_taken[waypoint_index]:
                continue
            if votes[local_index] < quorum and proposal_counts[waypoint_index] > 1:
                continue
            score = proposal_scores[local_index]
            if (
                votes[local_index] > best_votes
                or (
                    votes[local_index] == best_votes
                    and score > best_score
                )
            ):
                best_agent = local_index
                best_votes = votes[local_index]
                best_score = score
        if best_agent < 0:
            break
        assignments[best_agent] = proposals[best_agent]
        agent_taken[best_agent] = 1
        waypoint_taken[proposals[best_agent]] = 1
        committed_count += 1

    while True:
        best_agent = -1
        best_votes = -1
        best_score = -1e9
        for local_index in range(active_count):
            if agent_taken[local_index]:
                continue
            waypoint_index = proposals[local_index]
            if waypoint_taken[waypoint_index]:
                continue
            score = proposal_scores[local_index]
            if (
                votes[local_index] > best_votes
                or (
                    votes[local_index] == best_votes
                    and score > best_score
                )
            ):
                best_agent = local_index
                best_votes = votes[local_index]
                best_score = score
        if best_agent < 0:
            break
        assignments[best_agent] = proposals[best_agent]
        agent_taken[best_agent] = 1
        waypoint_taken[proposals[best_agent]] = 1

    for local_index in range(active_count):
        if agent_taken[local_index]:
            continue
        best_waypoint = -1
        best_score = -1e9
        for waypoint_index in range(waypoint_count):
            if waypoint_taken[waypoint_index]:
                continue
            score = score_matrix[local_index, waypoint_index]
            if score > best_score:
                best_score = score
                best_waypoint = waypoint_index
        if best_waypoint >= 0:
            assignments[local_index] = best_waypoint
            agent_taken[local_index] = 1
            waypoint_taken[best_waypoint] = 1

    return assignments, committed_count, contention_count


@njit(cache=True)
def _resolve_greedy_assignments(score_matrix: np.ndarray) -> np.ndarray:
    active_count, waypoint_count = score_matrix.shape
    assignments = np.full(active_count, -1, dtype=np.int32)
    agent_taken = np.zeros(active_count, dtype=np.uint8)
    waypoint_taken = np.zeros(waypoint_count, dtype=np.uint8)

    while True:
        best_agent = -1
        best_waypoint = -1
        best_score = -1e9
        for local_index in range(active_count):
            if agent_taken[local_index]:
                continue
            for waypoint_index in range(waypoint_count):
                if waypoint_taken[waypoint_index]:
                    continue
                score = score_matrix[local_index, waypoint_index]
                if score > best_score:
                    best_score = score
                    best_agent = local_index
                    best_waypoint = waypoint_index
        if best_agent < 0 or best_waypoint < 0:
            break
        assignments[best_agent] = best_waypoint
        agent_taken[best_agent] = 1
        waypoint_taken[best_waypoint] = 1

    return assignments


class SwarmSimulator:
    def __init__(
        self,
        config: SwarmConfig | None = None,
        seed: int = 7,
        registry: CollectorRegistry | None = None,
    ) -> None:
        self.config = config or SwarmConfig()
        self.base_seed = seed
        self.seed = seed
        self.reset_index = -1
        self.rng = np.random.default_rng(seed)
        self.metrics = SwarmMetrics(registry=registry)
        if self.config.assignment_strategy not in SUPPORTED_ASSIGNMENT_STRATEGIES:
            raise ValueError(
                f"assignment_strategy must be one of {SUPPORTED_ASSIGNMENT_STRATEGIES}, "
                f"got {self.config.assignment_strategy!r}."
            )
        self.navigation = NavigationGraph.build(
            width=self.config.width,
            height=self.config.height,
            cols=self.config.navigation_cols,
            rows=self.config.navigation_rows,
        )
        self.raft = RaftCoordinator(
            node_count=self.config.drone_count,
            rng=self.rng,
            heartbeat_ticks=self.config.raft_heartbeat_ticks,
            election_timeout_min_ticks=self.config.raft_election_timeout_min_ticks,
            election_timeout_max_ticks=self.config.raft_election_timeout_max_ticks,
        )
        self.swarmraft = SwarmRaftLocalizer(
            drone_count=self.config.drone_count,
            rng=self.rng,
            config=SwarmRaftConfig(
                width=float(self.config.width),
                height=float(self.config.height),
                gnss_noise_std=float(self.config.swarmraft_gnss_noise_std),
                ins_drift_std=float(self.config.swarmraft_ins_drift_std),
                range_noise_std=float(self.config.swarmraft_range_noise_std),
                residual_threshold=float(self.config.swarmraft_residual_threshold),
                min_peer_votes=int(self.config.swarmraft_min_peer_votes),
            ),
        )
        self.taichi_backend: TaichiBoidsBackend | None = None
        if self.config.physics_backend == "taichi":
            from swarm_sim.taichi_backend import TaichiBoidsBackend

            self.taichi_backend = TaichiBoidsBackend(self.config.drone_count)
        self.tick = 0
        self.elapsed_seconds = 0.0
        self.consensus_rounds = 0
        self.consensus_commits = 0
        self.waypoint_completions = 0
        self.total_collision_events = 0
        self.last_new_collisions = 0
        self.last_assignment_changes = 0
        self.pending_failure_recovery_deadline_tick: int | None = None
        self.pending_failure_recovery_since_tick: int | None = None
        self.pending_failure_waypoints: set[int] = set()
        self.last_failure_recovery_latency_ticks = 0
        self.failure_recoveries_total = 0
        self.last_collision_keys = np.empty(0, dtype=np.int64)
        self.events: deque[str] = deque(maxlen=8)

        self.agent_ids = [f"drone-{index + 1}" for index in range(self.config.drone_count)]
        self.waypoint_ids = [f"wp-{index + 1}" for index in range(self.config.waypoint_count)]

        self.positions = np.zeros((self.config.drone_count, 2), dtype=np.float32)
        self.velocities = np.zeros((self.config.drone_count, 2), dtype=np.float32)
        self.failed = np.zeros(self.config.drone_count, dtype=bool)
        self.target_waypoints = np.full(self.config.drone_count, -1, dtype=np.int32)
        self.route_nodes = np.full(self.config.drone_count, -1, dtype=np.int32)
        self.route_goal_nodes = np.full(self.config.drone_count, -1, dtype=np.int32)
        self.route_dirty = np.ones(self.config.drone_count, dtype=bool)

        self.waypoint_positions = np.zeros((self.config.waypoint_count, 2), dtype=np.float32)
        self.waypoint_priorities = np.ones(self.config.waypoint_count, dtype=np.float32)
        self.waypoint_claimed_by = np.full(self.config.waypoint_count, -1, dtype=np.int32)
        self.waypoint_completions_by_id = np.zeros(self.config.waypoint_count, dtype=np.int32)
        self.waypoint_nav_nodes = np.zeros(self.config.waypoint_count, dtype=np.int32)

        self.reset()

    def reset(self, seed: int | None = None) -> dict[str, Any]:
        if seed is not None:
            self.base_seed = seed
            self.reset_index = -1
        self.reset_index += 1
        effective_seed = self._effective_reset_seed()
        self.seed = effective_seed
        self.rng = np.random.default_rng(effective_seed)
        self.raft.rng = self.rng
        self.swarmraft.rng = self.rng

        self.tick = 0
        self.elapsed_seconds = 0.0
        self.consensus_rounds = 0
        self.consensus_commits = 0
        self.waypoint_completions = 0
        self.total_collision_events = 0
        self.last_new_collisions = 0
        self.last_assignment_changes = 0
        self.pending_failure_recovery_deadline_tick = None
        self.pending_failure_recovery_since_tick = None
        self.pending_failure_waypoints.clear()
        self.last_failure_recovery_latency_ticks = 0
        self.failure_recoveries_total = 0
        self.last_collision_keys = np.empty(0, dtype=np.int64)
        self.events.clear()

        self._spawn_drones()
        self._spawn_waypoints()
        self.failed.fill(False)
        self.target_waypoints.fill(-1)
        self.route_nodes.fill(-1)
        self.route_goal_nodes.fill(-1)
        self.route_dirty.fill(True)
        self.waypoint_claimed_by.fill(-1)
        self.waypoint_completions_by_id.fill(0)
        self._refresh_waypoint_nav_nodes()
        self.raft.reset(current_tick=self.tick)
        self.swarmraft.reset(self.positions)

        self.events.append("Simulation reset with vectorized SoA state.")
        snapshot = self.snapshot()
        self.metrics.observe_summary(snapshot["summary"])
        return snapshot

    def _effective_reset_seed(self) -> int:
        if self.reset_index <= 0:
            return int(self.base_seed)
        return int(
            np.random.SeedSequence([int(self.base_seed), int(self.reset_index)]).generate_state(
                1,
                dtype=np.uint32,
            )[0]
        )

    def snapshot(self) -> dict[str, Any]:
        summary = self._build_summary()
        return {
            "tick": self.tick,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "config": self.config.as_dict(),
            "raft": self.raft.status(self.failed, self.agent_ids),
            "swarmraft": self._serialize_swarmraft(),
            "drones": self._serialize_drones(),
            "waypoints": self._serialize_waypoints(),
            "events": list(self.events),
            "summary": summary,
        }

    def step(self) -> dict[str, Any]:
        self.tick += 1
        self.elapsed_seconds += self.config.tick_seconds

        if self.config.failure_tick is not None and self.tick == self.config.failure_tick:
            self.inject_random_failure()

        if self.config.assignment_strategy in {"raft", "swarmraft"}:
            for event in self.raft.tick(current_tick=self.tick, failed=self.failed):
                self.events.append(event.replace("node ", "drone-"))

        planning_due = self.tick == 1 or self.tick % self.config.planning_interval == 0
        recovery_due = self._failure_recovery_due()
        if recovery_due:
            self._run_failure_recovery()
        elif planning_due:
            self._plan_waypoints()

        self._refresh_routes()
        new_collisions = self._update_motion()
        completions = self._complete_waypoints()
        if self.config.assignment_strategy == "swarmraft":
            self._update_swarmraft_state()

        snapshot = self.snapshot()
        self.metrics.record_collisions(new_collisions)
        self.metrics.record_completions(completions)
        self.metrics.observe_summary(snapshot["summary"])
        return snapshot

    def inject_random_failure(self) -> str | None:
        active_indices = np.flatnonzero(~self.failed)
        if active_indices.size == 0:
            return None
        failed_index = int(self.rng.choice(active_indices))
        return self.inject_failure(self.agent_ids[failed_index])

    def inject_failure(self, drone_id: str) -> str | None:
        try:
            agent_index = self.agent_ids.index(drone_id)
        except ValueError:
            return None

        if self.failed[agent_index]:
            return None

        self.failed[agent_index] = True
        self.velocities[agent_index] = 0.0
        previous_target = int(self.target_waypoints[agent_index])
        self.target_waypoints[agent_index] = -1
        self.route_nodes[agent_index] = -1
        self.route_goal_nodes[agent_index] = -1
        self.route_dirty[agent_index] = False
        if previous_target >= 0:
            self.waypoint_claimed_by[previous_target] = -1
            self._schedule_failure_recovery(previous_target)
        self.events.append(
            f"{drone_id} dropped out at tick {self.tick}; routing marked dirty for reassignment."
        )
        return drone_id

    def update_config(
        self,
        *,
        tick_seconds: float | None = None,
        render_stride: int | None = None,
        assignment_strategy: str | None = None,
    ) -> dict[str, Any]:
        changed: list[str] = []
        if tick_seconds is not None:
            if tick_seconds <= 0:
                raise ValueError("tick_seconds must be greater than 0.")
            self.config.tick_seconds = float(tick_seconds)
            changed.append(f"tick_seconds={self.config.tick_seconds:.3f}")
        if render_stride is not None:
            if render_stride < 1:
                raise ValueError("render_stride must be at least 1.")
            self.config.render_stride = int(render_stride)
            changed.append(f"render_stride={self.config.render_stride}")
        if assignment_strategy is not None:
            if assignment_strategy not in SUPPORTED_ASSIGNMENT_STRATEGIES:
                raise ValueError(
                    f"assignment_strategy must be one of {SUPPORTED_ASSIGNMENT_STRATEGIES}."
                )
            self.config.assignment_strategy = assignment_strategy
            changed.append(f"assignment_strategy={self.config.assignment_strategy}")
            if assignment_strategy == "swarmraft":
                self.swarmraft.reset(self.positions)
        if changed:
            self.events.append(f"Runtime config updated: {', '.join(changed)}.")
        return self.config.as_dict()

    def _schedule_failure_recovery(self, waypoint_index: int) -> None:
        if self.config.failure_recovery_ticks < 0:
            raise ValueError("failure_recovery_ticks must be non-negative.")
        self.pending_failure_waypoints.add(int(waypoint_index))
        if self.pending_failure_recovery_since_tick is None:
            self.pending_failure_recovery_since_tick = self.tick
        deadline = self.tick + self.config.failure_recovery_ticks
        if (
            self.pending_failure_recovery_deadline_tick is None
            or deadline < self.pending_failure_recovery_deadline_tick
        ):
            self.pending_failure_recovery_deadline_tick = deadline

    def _failure_recovery_due(self) -> bool:
        if self.pending_failure_recovery_deadline_tick is None:
            return False
        return (
            self.tick == 1
            or self.tick % self.config.planning_interval == 0
            or self.tick >= self.pending_failure_recovery_deadline_tick
        )

    def _run_failure_recovery(self) -> None:
        orphaned_waypoints = sorted(self.pending_failure_waypoints)
        committed = self._plan_waypoints()
        if not committed:
            return

        latency = (
            self.tick - self.pending_failure_recovery_since_tick
            if self.pending_failure_recovery_since_tick is not None
            else 0
        )
        self.last_failure_recovery_latency_ticks = int(latency)
        self.failure_recoveries_total += 1

        if orphaned_waypoints:
            reassigned_count = int(
                np.count_nonzero(self.waypoint_claimed_by[np.asarray(orphaned_waypoints)] >= 0)
            )
            self.events.append(
                "Failure recovery election reassigned "
                f"{reassigned_count}/{len(orphaned_waypoints)} orphaned waypoints in "
                f"{self.last_failure_recovery_latency_ticks} tick(s)."
            )

        self.pending_failure_recovery_deadline_tick = None
        self.pending_failure_recovery_since_tick = None
        self.pending_failure_waypoints.clear()

    def _spawn_drones(self) -> None:
        center = self.rng.uniform(
            low=np.array([self.config.width * 0.28, self.config.height * 0.28], dtype=np.float32),
            high=np.array([self.config.width * 0.72, self.config.height * 0.72], dtype=np.float32),
        ).astype(np.float32)
        angles = np.sort(
            self.rng.uniform(
                0.0,
                float(2.0 * np.pi),
                size=self.config.drone_count,
            ).astype(np.float32)
        )
        rotation_offset = np.float32(self.rng.uniform(0.0, float(2.0 * np.pi)))
        angles = (angles + rotation_offset).astype(np.float32)
        radii = self.rng.uniform(95.0, 145.0, size=self.config.drone_count).astype(np.float32)
        jitter = self.rng.uniform(-14.0, 14.0, size=(self.config.drone_count, 2)).astype(np.float32)

        orbit = np.stack((np.cos(angles), np.sin(angles)), axis=1).astype(np.float32)
        tangential = np.stack((-np.sin(angles), np.cos(angles)), axis=1).astype(np.float32)
        self.positions = center + (orbit * radii[:, None]) + jitter

        velocity_scale = self.rng.uniform(8.0, 16.0, size=(self.config.drone_count, 1)).astype(
            np.float32
        )
        velocity_jitter = self.rng.uniform(-4.0, 4.0, size=(self.config.drone_count, 2)).astype(
            np.float32
        )
        self.velocities = (tangential * velocity_scale) + velocity_jitter
        self.positions[:, 0] = np.clip(self.positions[:, 0], 20.0, self.config.width - 20.0)
        self.positions[:, 1] = np.clip(self.positions[:, 1], 20.0, self.config.height - 20.0)

    def _spawn_waypoints(self) -> None:
        self.waypoint_positions = self._sample_scattered_points(
            self.config.waypoint_count,
            margin=80.0,
            min_distance=96.0,
        )
        self.waypoint_priorities = self.rng.uniform(
            0.8,
            1.25,
            size=self.config.waypoint_count,
        ).astype(np.float32)

    def _sample_scattered_points(
        self,
        count: int,
        *,
        margin: float,
        min_distance: float,
    ) -> np.ndarray:
        points = np.zeros((count, 2), dtype=np.float32)
        if count <= 0:
            return points

        accepted = 0
        rejection_count = 0
        spacing = float(min_distance)
        low = np.array([margin, margin], dtype=np.float32)
        high = np.array([self.config.width - margin, self.config.height - margin], dtype=np.float32)
        while accepted < count:
            candidate = self.rng.uniform(low=low, high=high).astype(np.float32)
            if accepted == 0:
                points[accepted] = candidate
                accepted += 1
                continue

            distances = np.linalg.norm(points[:accepted] - candidate, axis=1)
            if np.all(distances >= spacing):
                points[accepted] = candidate
                accepted += 1
                rejection_count = 0
                continue

            rejection_count += 1
            if rejection_count >= 128:
                spacing = max(spacing * 0.9, 28.0)
                rejection_count = 0
        return points

    def _refresh_waypoint_nav_nodes(self) -> None:
        self.waypoint_nav_nodes = self.navigation.nearest_nodes(self.waypoint_positions)

    def _score_matrix(self, active_indices: np.ndarray) -> np.ndarray:
        active_positions = self._assignment_reference_positions(active_indices)
        offsets = active_positions[:, None, :] - self.waypoint_positions[None, :, :]
        distances = np.linalg.norm(offsets, axis=2).astype(np.float32)
        distance_score = np.float32(2.4) - (
            (distances / np.float32(max(self.config.width, self.config.height))) * np.float32(2.2)
        )

        current_bonus = (
            self.target_waypoints[active_indices, None]
            == np.arange(self.config.waypoint_count, dtype=np.int32)[None, :]
        ).astype(np.float32) * np.float32(0.9)

        load_penalty = (
            (self.waypoint_claimed_by[None, :] >= 0)
            & (self.waypoint_claimed_by[None, :] != active_indices[:, None])
        ).astype(np.float32) * np.float32(1.1)

        active_nav_nodes = self.navigation.nearest_nodes(active_positions)
        route_costs = self.navigation.path_costs[
            active_nav_nodes[:, None],
            self.waypoint_nav_nodes[None, :],
        ]
        route_score = np.float32(0.35) - (
            (route_costs / np.float32(max(self.config.width, self.config.height))) * np.float32(0.3)
        )

        return (
            distance_score
            + route_score
            + self.waypoint_priorities[None, :]
            + current_bonus
            - load_penalty
        ).astype(np.float32)

    def _assignment_reference_positions(self, active_indices: np.ndarray) -> np.ndarray:
        if self.config.assignment_strategy == "swarmraft":
            return self.swarmraft.recovered_positions[active_indices]
        return self.positions[active_indices]

    def _apply_assignments(self, assignments_by_agent: np.ndarray) -> tuple[int, int]:
        previous_targets = self.target_waypoints.copy()

        self.target_waypoints.fill(-1)
        self.target_waypoints[:] = assignments_by_agent
        self.target_waypoints[self.failed] = -1

        self.waypoint_claimed_by.fill(-1)
        for agent_index in np.flatnonzero((~self.failed) & (self.target_waypoints >= 0)):
            self.waypoint_claimed_by[self.target_waypoints[agent_index]] = agent_index

        changed_mask = (previous_targets != self.target_waypoints) & (~self.failed)
        self.route_dirty[changed_mask] = True
        assignment_changes = int(np.count_nonzero(changed_mask))
        committed = int(np.count_nonzero((~self.failed) & (self.target_waypoints >= 0)))
        self.last_assignment_changes = assignment_changes
        self.consensus_rounds += 1
        self.consensus_commits += committed
        return assignment_changes, committed

    def _greedy_assignments_for_active(
        self,
        *,
        active_indices: np.ndarray,
        score_matrix: np.ndarray,
    ) -> np.ndarray:
        full_assignments = np.full(self.config.drone_count, -1, dtype=np.int32)
        active_assignments = _resolve_greedy_assignments(score_matrix)
        full_assignments[active_indices] = active_assignments
        full_assignments[self.failed] = -1
        return full_assignments

    def _plan_waypoints(self) -> bool:
        active_indices = np.flatnonzero(~self.failed)
        if active_indices.size == 0:
            return False

        score_matrix = self._score_matrix(active_indices)

        if self.config.assignment_strategy == "consensus":
            proposals = np.argmax(score_matrix, axis=1).astype(np.int32)
            proposal_scores = score_matrix[np.arange(active_indices.size), proposals].astype(np.float32)
            votes = _consensus_votes(
                self.positions[active_indices],
                proposals,
                proposal_scores,
                float(self.config.communication_radius),
            )
            assignments, committed, contention_count = _resolve_consensus_assignments(
                proposals,
                proposal_scores,
                votes,
                score_matrix,
                self.config.waypoint_count,
            )
            full_assignments = np.full(self.config.drone_count, -1, dtype=np.int32)
            full_assignments[active_indices] = assignments
            full_assignments[self.failed] = -1
            self._apply_assignments(full_assignments)
        elif self.config.assignment_strategy == "greedy":
            full_assignments = self._greedy_assignments_for_active(
                active_indices=active_indices,
                score_matrix=score_matrix,
            )
            self._apply_assignments(full_assignments)
            committed = int(np.count_nonzero(full_assignments >= 0))
            contention_count = 0
        elif self.config.assignment_strategy in {"raft", "swarmraft"}:
            proposed_assignments = self._greedy_assignments_for_active(
                active_indices=active_indices,
                score_matrix=score_matrix,
            )
            committed_assignments, raft_events = self.raft.propose_assignments(
                current_tick=self.tick,
                failed=self.failed,
                assignments=proposed_assignments,
            )
            if committed_assignments is None:
                self.last_assignment_changes = 0
                for event in raft_events:
                    self.events.append(event)
                return False
            self._apply_assignments(committed_assignments.astype(np.int32))
            committed = int(np.count_nonzero(committed_assignments >= 0))
            contention_count = 0
            for event in raft_events:
                self.events.append(event)
        else:
            raise ValueError(
                f"Unsupported assignment_strategy={self.config.assignment_strategy!r}"
            )

        if self.last_assignment_changes:
            self.events.append(
                f"Planning epoch {self.consensus_rounds} reassigned {self.last_assignment_changes} drones."
            )
        if contention_count:
            self.events.append(
                f"Planning epoch {self.consensus_rounds} resolved {contention_count} contested claims."
            )
        return True

    def _refresh_routes(self) -> None:
        active_indices = np.flatnonzero(~self.failed)
        if active_indices.size == 0:
            return

        active_targets = self.target_waypoints[active_indices]
        unassigned = active_targets < 0
        if np.any(unassigned):
            unassigned_indices = active_indices[unassigned]
            self.route_nodes[unassigned_indices] = -1
            self.route_goal_nodes[unassigned_indices] = -1
            self.route_dirty[unassigned_indices] = False

        dirty_mask = self.route_dirty[active_indices] & (active_targets >= 0)
        if np.any(dirty_mask):
            dirty_indices = active_indices[dirty_mask]
            start_nodes = self.navigation.nearest_nodes(self.positions[dirty_indices])
            goal_nodes = self.waypoint_nav_nodes[self.target_waypoints[dirty_indices]]
            self.route_nodes[dirty_indices] = self.navigation.next_hop[start_nodes, goal_nodes]
            self.route_goal_nodes[dirty_indices] = goal_nodes
            self.route_dirty[dirty_indices] = False

        routed_mask = (self.route_nodes[active_indices] >= 0) & (active_targets >= 0)
        if not np.any(routed_mask):
            return

        routed_indices = active_indices[routed_mask]
        route_targets = self.navigation.node_positions[self.route_nodes[routed_indices]]
        route_distances = np.linalg.norm(
            self.positions[routed_indices] - route_targets,
            axis=1,
        )
        reached_mask = route_distances <= self.config.route_reach_radius
        if not np.any(reached_mask):
            return

        reached_indices = routed_indices[reached_mask]
        current_nodes = self.route_nodes[reached_indices]
        goal_nodes = self.route_goal_nodes[reached_indices]
        next_nodes = self.navigation.next_hop[current_nodes, goal_nodes]
        finished_mask = current_nodes == goal_nodes
        self.route_nodes[reached_indices] = next_nodes
        self.route_nodes[reached_indices[finished_mask]] = -1

    def _target_points(self, active_indices: np.ndarray) -> np.ndarray:
        points = self.positions[active_indices].copy()
        active_targets = self.target_waypoints[active_indices]
        assigned_mask = active_targets >= 0
        if np.any(assigned_mask):
            assigned_indices = active_indices[assigned_mask]
            points[assigned_mask] = self.waypoint_positions[self.target_waypoints[assigned_indices]]

        route_mask = self.route_nodes[active_indices] >= 0
        if np.any(route_mask):
            route_nodes = self.route_nodes[active_indices[route_mask]]
            points[route_mask] = self.navigation.node_positions[route_nodes]
        return points

    def _target_points_full(self) -> np.ndarray:
        all_indices = np.arange(self.config.drone_count, dtype=np.int32)
        return self._target_points(all_indices)

    def _boundary_force(self, active_positions: np.ndarray) -> np.ndarray:
        margin = np.float32(90.0)
        force = np.zeros_like(active_positions, dtype=np.float32)

        left_mask = active_positions[:, 0] < margin
        right_mask = active_positions[:, 0] > (self.config.width - margin)
        top_mask = active_positions[:, 1] < margin
        bottom_mask = active_positions[:, 1] > (self.config.height - margin)

        force[left_mask, 0] += (margin - active_positions[left_mask, 0]) / margin
        force[right_mask, 0] -= (
            active_positions[right_mask, 0] - (self.config.width - margin)
        ) / margin
        force[top_mask, 1] += (margin - active_positions[top_mask, 1]) / margin
        force[bottom_mask, 1] -= (
            active_positions[bottom_mask, 1] - (self.config.height - margin)
        ) / margin
        return force

    def _update_motion(self) -> int:
        active_indices = np.flatnonzero(~self.failed)
        active_count = active_indices.size
        if active_count == 0:
            self.last_new_collisions = 0
            self.last_collision_keys = np.empty(0, dtype=np.int64)
            return 0

        if self.config.physics_backend == "taichi":
            assert self.taichi_backend is not None
            self.taichi_backend.step(
                positions=self.positions,
                velocities=self.velocities,
                target_points=self._target_points_full(),
                active_mask=(~self.failed).astype(np.int32),
                config=self.config,
            )
        else:
            active_positions = self.positions[active_indices]
            active_velocities = self.velocities[active_indices]
            tree = cKDTree(active_positions)

            if active_count > 1:
                neighbor_pairs = tree.query_pairs(self.config.neighbor_radius, output_type="ndarray")
            else:
                neighbor_pairs = np.empty((0, 2), dtype=np.int32)

            pair_left = (
                neighbor_pairs[:, 0].astype(np.int32)
                if neighbor_pairs.size
                else np.empty(0, dtype=np.int32)
            )
            pair_right = (
                neighbor_pairs[:, 1].astype(np.int32)
                if neighbor_pairs.size
                else np.empty(0, dtype=np.int32)
            )

            counts, position_sums, velocity_sums, separation = _accumulate_neighbor_data(
                active_count,
                pair_left,
                pair_right,
                active_positions.astype(np.float32),
                active_velocities.astype(np.float32),
                float(self.config.separation_radius),
            )

            cohesion = np.zeros_like(active_positions, dtype=np.float32)
            alignment = np.zeros_like(active_positions, dtype=np.float32)
            has_neighbors = counts > 0
            if np.any(has_neighbors):
                counts_float = counts[has_neighbors].astype(np.float32)[:, None]
                cohesion[has_neighbors] = (
                    position_sums[has_neighbors] / counts_float
                ) - active_positions[has_neighbors]
                alignment[has_neighbors] = (
                    velocity_sums[has_neighbors] / counts_float
                ) - active_velocities[has_neighbors]

            target_points = self._target_points(active_indices)
            target_offsets = target_points - active_positions
            target_distances = np.linalg.norm(target_offsets, axis=1, keepdims=True).astype(
                np.float32
            )
            target_force = np.zeros_like(target_offsets, dtype=np.float32)
            target_mask = target_distances[:, 0] > EPSILON
            if np.any(target_mask):
                target_force[target_mask] = target_offsets[target_mask] / target_distances[target_mask]
                target_force[target_mask] *= np.minimum(
                    target_distances[target_mask] / np.float32(55.0),
                    np.float32(3.0),
                )

            boundary_force = self._boundary_force(active_positions)

            total_force = (
                separation * np.float32(self.config.separation_weight)
                + alignment * np.float32(self.config.alignment_weight)
                + cohesion * np.float32(self.config.cohesion_weight)
                + target_force * np.float32(self.config.waypoint_weight)
                + boundary_force * np.float32(self.config.boundary_weight)
            ).astype(np.float32)

            _limit_and_move(
                self.positions,
                self.velocities,
                active_indices.astype(np.int32),
                total_force,
                float(self.config.tick_seconds),
                float(self.config.max_speed),
                float(self.config.width),
                float(self.config.height),
            )

        active_positions = self.positions[active_indices]
        tree = cKDTree(active_positions)
        if active_count > 1:
            collision_pairs = tree.query_pairs(self.config.collision_radius, output_type="ndarray")
        else:
            collision_pairs = np.empty((0, 2), dtype=np.int32)

        if collision_pairs.size == 0:
            collision_keys = np.empty(0, dtype=np.int64)
        else:
            global_pairs = active_indices[collision_pairs]
            collision_keys = (
                np.minimum(global_pairs[:, 0], global_pairs[:, 1]).astype(np.int64)
                * np.int64(self.config.drone_count)
                + np.maximum(global_pairs[:, 0], global_pairs[:, 1]).astype(np.int64)
            )
            collision_keys = np.unique(collision_keys)

        new_collision_count = int(
            np.setdiff1d(collision_keys, self.last_collision_keys, assume_unique=True).size
        )
        self.last_new_collisions = new_collision_count
        self.last_collision_keys = collision_keys
        if new_collision_count:
            self.events.append(
                f"Collision alert: {new_collision_count} new close-contact event(s) detected."
            )
        self.total_collision_events += new_collision_count
        return new_collision_count

    def _complete_waypoints(self) -> int:
        active_indices = np.flatnonzero((~self.failed) & (self.target_waypoints >= 0))
        if active_indices.size == 0:
            return 0

        waypoint_indices = self.target_waypoints[active_indices]
        distances = np.linalg.norm(
            self.positions[active_indices] - self.waypoint_positions[waypoint_indices],
            axis=1,
        )
        completed_mask = distances <= self.config.waypoint_capture_radius
        if not np.any(completed_mask):
            return 0

        completed_agents = active_indices[completed_mask]
        completed_waypoints = waypoint_indices[completed_mask]
        unique_waypoints, first_indices = np.unique(completed_waypoints, return_index=True)
        representative_agents = completed_agents[first_indices]

        completion_count = int(unique_waypoints.size)
        self.waypoint_completions += completion_count
        self.waypoint_completions_by_id[unique_waypoints] += 1
        self.waypoint_claimed_by[unique_waypoints] = -1

        self.target_waypoints[representative_agents] = -1
        self.route_nodes[representative_agents] = -1
        self.route_goal_nodes[representative_agents] = -1
        self.route_dirty[representative_agents] = False

        new_positions = self.rng.uniform(
            low=np.array([90.0, 90.0], dtype=np.float32),
            high=np.array([self.config.width - 90.0, self.config.height - 90.0], dtype=np.float32),
            size=(completion_count, 2),
        ).astype(np.float32)
        new_priorities = self.rng.uniform(0.8, 1.25, size=completion_count).astype(np.float32)
        self.waypoint_positions[unique_waypoints] = new_positions
        self.waypoint_priorities[unique_waypoints] = new_priorities
        self.waypoint_nav_nodes[unique_waypoints] = self.navigation.nearest_nodes(new_positions)

        if completion_count == 1:
            self.events.append(
                f"{self.agent_ids[int(representative_agents[0])]} completed {self.waypoint_ids[int(unique_waypoints[0])]}."
            )
        else:
            self.events.append(
                f"{completion_count} waypoints completed and recycled at tick {self.tick}."
            )

        return completion_count

    def _cohesion_score(self) -> float:
        active_positions = self.positions[~self.failed]
        if active_positions.size == 0:
            return 0.0
        centroid = active_positions.mean(axis=0)
        distances = np.linalg.norm(active_positions - centroid, axis=1)
        world_diagonal = np.hypot(self.config.width, self.config.height)
        return max(0.0, 1.0 - float(distances.mean()) / (float(world_diagonal) * 0.35))

    def _build_summary(self) -> dict[str, Any]:
        active_mask = ~self.failed
        active_count = int(np.count_nonzero(active_mask))
        average_speed = (
            float(np.linalg.norm(self.velocities[active_mask], axis=1).mean())
            if active_count
            else 0.0
        )
        committed_assignment_ratio = (
            float(np.count_nonzero(active_mask & (self.target_waypoints >= 0))) / active_count
            if active_count
            else 0.0
        )
        consensus_ratio = (
            committed_assignment_ratio
        )
        completion_rate = (
            self.waypoint_completions / max(self.elapsed_seconds / 60.0, 1e-6)
            if self.elapsed_seconds > 0
            else 0.0
        )
        raft_status = self.raft.status(self.failed, self.agent_ids)
        swarmraft_status = (
            self.swarmraft.summary(true_positions=self.positions, failed=self.failed)
            if self.config.assignment_strategy == "swarmraft"
            else {
                "enabled": False,
                "suspected_agents": 0,
                "recovered_agents": 0,
                "mean_gnss_error": 0.0,
                "mean_consensus_error": 0.0,
                "mean_residual": 0.0,
            }
        )
        return {
            "active_agents": active_count,
            "failed_agents": int(np.count_nonzero(self.failed)),
            "active_collision_pairs": int(self.last_collision_keys.size),
            "collision_events_total": self.total_collision_events,
            "new_collision_events": self.last_new_collisions,
            "cohesion_score": round(self._cohesion_score(), 3),
            "average_speed": round(average_speed, 2),
            "consensus_success_ratio": round(consensus_ratio, 3),
            "dropout_detected": bool(np.any(self.failed)),
            "assignment_changes": self.last_assignment_changes,
            "failure_recovery_pending": bool(self.pending_failure_waypoints),
            "last_failure_recovery_latency_ticks": self.last_failure_recovery_latency_ticks,
            "failure_recoveries_total": self.failure_recoveries_total,
            "raft_term": raft_status["term"],
            "raft_commit_index": raft_status["commit_index"],
            "raft_log_length": raft_status["log_length"],
            "raft_leader_id": raft_status["leader_id"],
            "raft_quorum_available": raft_status["quorum_available"],
            "swarmraft_enabled": swarmraft_status["enabled"],
            "swarmraft_suspected_agents": swarmraft_status["suspected_agents"],
            "swarmraft_recovered_agents": swarmraft_status["recovered_agents"],
            "swarmraft_mean_gnss_error": swarmraft_status["mean_gnss_error"],
            "swarmraft_mean_consensus_error": swarmraft_status["mean_consensus_error"],
            "swarmraft_mean_residual": swarmraft_status["mean_residual"],
            "waypoint_completions": self.waypoint_completions,
            "waypoint_completion_rate_per_min": round(completion_rate, 2),
        }

    def _serialize_drones(self) -> list[dict[str, Any]]:
        return [
            {
                "drone_id": self.agent_ids[index],
                "position": {
                    "x": round(float(self.positions[index, 0]), 2),
                    "y": round(float(self.positions[index, 1]), 2),
                },
                "velocity": {
                    "x": round(float(self.velocities[index, 0]), 2),
                    "y": round(float(self.velocities[index, 1]), 2),
                },
                "target_waypoint_id": (
                    self.waypoint_ids[int(self.target_waypoints[index])]
                    if self.target_waypoints[index] >= 0
                    else None
                ),
                "failed": bool(self.failed[index]),
                "swarmraft": self._serialize_swarmraft_drone(index),
            }
            for index in range(self.config.drone_count)
        ]

    def _serialize_waypoints(self) -> list[dict[str, Any]]:
        return [
            {
                "waypoint_id": self.waypoint_ids[index],
                "position": {
                    "x": round(float(self.waypoint_positions[index, 0]), 2),
                    "y": round(float(self.waypoint_positions[index, 1]), 2),
                },
                "priority": round(float(self.waypoint_priorities[index]), 2),
                "claimed_by": (
                    self.agent_ids[int(self.waypoint_claimed_by[index])]
                    if self.waypoint_claimed_by[index] >= 0
                    else None
                ),
                "completions": int(self.waypoint_completions_by_id[index]),
            }
            for index in range(self.config.waypoint_count)
        ]

    def _serialize_swarmraft(self) -> dict[str, Any]:
        if self.config.assignment_strategy != "swarmraft":
            return {"enabled": False}
        return {
            "enabled": True,
            "leader_id": self.raft.status(self.failed, self.agent_ids)["leader_id"],
            "residual_threshold": round(float(self.config.swarmraft_residual_threshold), 2),
            "suspected_agents": [
                self.agent_ids[index]
                for index in np.flatnonzero(self.swarmraft.suspected_faulty & (~self.failed))
            ],
        }

    def _serialize_swarmraft_drone(self, index: int) -> dict[str, Any] | None:
        if self.config.assignment_strategy != "swarmraft":
            return None
        return {
            "gnss_position": {
                "x": round(float(self.swarmraft.gnss_positions[index, 0]), 2),
                "y": round(float(self.swarmraft.gnss_positions[index, 1]), 2),
            },
            "ins_position": {
                "x": round(float(self.swarmraft.ins_positions[index, 0]), 2),
                "y": round(float(self.swarmraft.ins_positions[index, 1]), 2),
            },
            "fused_position": {
                "x": round(float(self.swarmraft.fused_positions[index, 0]), 2),
                "y": round(float(self.swarmraft.fused_positions[index, 1]), 2),
            },
            "recovered_position": {
                "x": round(float(self.swarmraft.recovered_positions[index, 0]), 2),
                "y": round(float(self.swarmraft.recovered_positions[index, 1]), 2),
            },
            "residual": round(float(self.swarmraft.residuals[index]), 2),
            "negative_votes": int(self.swarmraft.negative_votes[index]),
            "positive_votes": int(self.swarmraft.positive_votes[index]),
            "peer_count": int(self.swarmraft.peer_counts[index]),
            "suspected_faulty": bool(self.swarmraft.suspected_faulty[index]),
            "recovered": bool(self.swarmraft.recovered_mask[index]),
        }

    def _update_swarmraft_state(self) -> None:
        self.swarmraft.update(
            true_positions=self.positions,
            velocities=self.velocities,
            failed=self.failed,
            communication_radius=float(self.config.communication_radius),
            tick_seconds=float(self.config.tick_seconds),
        )
