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
    def test_consensus_assigns_unique_waypoints(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(drone_count=5, waypoint_count=5, planning_interval=1, failure_tick=None),
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
            config=SwarmConfig(drone_count=4, waypoint_count=4, planning_interval=1, failure_tick=1),
            seed=5,
        )

        snapshot = simulator.step()

        self.assertEqual(snapshot["summary"]["failed_agents"], 1)
        self.assertTrue(snapshot["summary"]["dropout_detected"])

    def test_snapshot_contains_metrics_summary(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(drone_count=3, waypoint_count=3, planning_interval=1, failure_tick=None),
            seed=21,
        )

        snapshot = simulator.step()

        self.assertIn("summary", snapshot)
        self.assertIn("cohesion_score", snapshot["summary"])
        self.assertIn("consensus_success_ratio", snapshot["summary"])

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
            ),
            seed=9,
        )

        snapshot = simulator.step()

        self.assertEqual(len(snapshot["drones"]), 4)
        self.assertIn("summary", snapshot)


if __name__ == "__main__":
    unittest.main()
