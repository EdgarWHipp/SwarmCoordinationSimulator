from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from swarm_sim.simulator import SwarmConfig, SwarmSimulator
from swarm_sim.taichi_backend import taichi_available


class SwarmSimulatorTest(unittest.TestCase):
    def test_invalid_raft_timeout_config_raises(self) -> None:
        with self.assertRaises(ValueError):
            SwarmSimulator(
                config=SwarmConfig(
                    drone_count=4,
                    waypoint_count=4,
                    failure_tick=None,
                    assignment_strategy="raft",
                    raft_election_timeout_min_ticks=5,
                    raft_election_timeout_max_ticks=4,
                ),
                seed=3,
            )

    def test_consensus_assigns_unique_waypoints(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(
                drone_count=5,
                waypoint_count=5,
                planning_interval=1,
                failure_tick=None,
                assignment_strategy="consensus",
            ),
            seed=11,
        )

        snapshot = simulator.step()
        targets = [
            drone["target_waypoint_id"]
            for drone in snapshot["drones"]
            if not drone["failed"]
        ]

        self.assertEqual(len(targets), 5)
        self.assertEqual(len(set(targets)), 5)

    def test_failure_injection_marks_dropout(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(
                drone_count=4,
                waypoint_count=4,
                planning_interval=1,
                failure_tick=1,
                assignment_strategy="raft",
                raft_election_timeout_min_ticks=1,
                raft_election_timeout_max_ticks=2,
            ),
            seed=5,
        )

        snapshot = simulator.step()

        self.assertEqual(snapshot["summary"]["failed_agents"], 1)
        self.assertTrue(snapshot["summary"]["dropout_detected"])

    def test_snapshot_contains_metrics_summary(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(
                drone_count=3,
                waypoint_count=3,
                planning_interval=1,
                failure_tick=None,
                assignment_strategy="raft",
                raft_election_timeout_min_ticks=1,
                raft_election_timeout_max_ticks=2,
            ),
            seed=21,
        )

        snapshot = simulator.step()

        self.assertIn("summary", snapshot)
        self.assertIn("cohesion_score", snapshot["summary"])
        self.assertIn("consensus_success_ratio", snapshot["summary"])

    def test_snapshot_config_round_trips_non_default_weights(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(
                drone_count=3,
                waypoint_count=3,
                failure_tick=None,
                cohesion_weight=0.25,
                alignment_weight=0.31,
                separation_weight=4.2,
                waypoint_weight=3.1,
                boundary_weight=0.9,
            ),
            seed=19,
        )

        snapshot = simulator.snapshot()

        self.assertEqual(snapshot["config"]["cohesion_weight"], 0.25)
        self.assertEqual(snapshot["config"]["alignment_weight"], 0.31)
        self.assertEqual(snapshot["config"]["separation_weight"], 4.2)
        self.assertEqual(snapshot["config"]["waypoint_weight"], 3.1)
        self.assertEqual(snapshot["config"]["boundary_weight"], 0.9)

    def test_failure_recovery_reassigns_within_window(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(
                drone_count=5,
                waypoint_count=4,
                planning_interval=10,
                failure_tick=None,
                failure_recovery_ticks=2,
                assignment_strategy="raft",
                raft_election_timeout_min_ticks=1,
                raft_election_timeout_max_ticks=2,
            ),
            seed=17,
        )

        first_snapshot = simulator.step()
        assigned_drone = next(
            drone["drone_id"]
            for drone in first_snapshot["drones"]
            if not drone["failed"] and drone["target_waypoint_id"] is not None
        )
        simulator.inject_failure(assigned_drone)

        recovery_snapshot = simulator.step()
        recovery_snapshot = simulator.step()

        self.assertEqual(recovery_snapshot["summary"]["failure_recoveries_total"], 1)
        self.assertLessEqual(
            recovery_snapshot["summary"]["last_failure_recovery_latency_ticks"],
            2,
        )
        self.assertFalse(recovery_snapshot["summary"]["failure_recovery_pending"])

    def test_raft_elects_and_persists_leader_until_failure(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(
                drone_count=5,
                waypoint_count=5,
                planning_interval=2,
                failure_tick=None,
                assignment_strategy="raft",
                raft_election_timeout_min_ticks=1,
                raft_election_timeout_max_ticks=2,
            ),
            seed=41,
        )

        first_snapshot = simulator.step()
        leader_id = first_snapshot["summary"]["raft_leader_id"]
        self.assertIsNotNone(leader_id)

        second_snapshot = simulator.step()
        self.assertEqual(second_snapshot["summary"]["raft_leader_id"], leader_id)

        simulator.inject_failure(leader_id)
        third_snapshot = simulator.step()
        fourth_snapshot = simulator.step()
        self.assertNotEqual(fourth_snapshot["summary"]["raft_leader_id"], leader_id)
        self.assertIsNotNone(fourth_snapshot["summary"]["raft_leader_id"])

    def test_raft_reset_respects_configured_election_timeout_bounds(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(
                drone_count=4,
                waypoint_count=4,
                failure_tick=None,
                assignment_strategy="raft",
                raft_election_timeout_min_ticks=5,
                raft_election_timeout_max_ticks=5,
            ),
            seed=13,
        )

        self.assertTrue((simulator.raft.election_deadline_tick == 5).all())

    def test_dynamic_tick_update_keeps_elapsed_time_monotonic(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(
                drone_count=4,
                waypoint_count=4,
                planning_interval=1,
                failure_tick=None,
                assignment_strategy="raft",
                raft_election_timeout_min_ticks=1,
                raft_election_timeout_max_ticks=2,
            ),
            seed=23,
        )

        simulator.step()
        simulator.update_config(tick_seconds=0.04, render_stride=2)
        snapshot = simulator.step()

        self.assertEqual(snapshot["config"]["tick_seconds"], 0.04)
        self.assertEqual(snapshot["config"]["render_stride"], 2)
        self.assertEqual(snapshot["elapsed_seconds"], 0.12)

    def test_elapsed_seconds_keeps_subcentisecond_precision(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(
                drone_count=4,
                waypoint_count=4,
                planning_interval=1,
                failure_tick=None,
                tick_seconds=0.005,
                assignment_strategy="raft",
                raft_election_timeout_min_ticks=1,
                raft_election_timeout_max_ticks=2,
            ),
            seed=27,
        )

        simulator.step()
        simulator.step()
        simulator.step()

        self.assertAlmostEqual(simulator.elapsed_seconds, 0.015, places=9)

    def test_taichi_backend_smoke(self) -> None:
        if not taichi_available():
            self.skipTest("Taichi is not installed")

        simulator = SwarmSimulator(
            config=SwarmConfig(
                drone_count=4,
                waypoint_count=4,
                planning_interval=1,
                failure_tick=None,
                physics_backend="taichi",
                assignment_strategy="raft",
                raft_election_timeout_min_ticks=1,
                raft_election_timeout_max_ticks=2,
            ),
            seed=9,
        )

        snapshot = simulator.step()

        self.assertEqual(len(snapshot["drones"]), 4)
        self.assertIn("summary", snapshot)


if __name__ == "__main__":
    unittest.main()
