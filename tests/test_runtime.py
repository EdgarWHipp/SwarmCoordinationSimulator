from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from swarm_sim.runtime import SimulationRuntime
from swarm_sim.simulator import SwarmConfig, SwarmSimulator
from swarm_sim.transport import benchmark_snapshot_encodings


class SimulationRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runtime = SimulationRuntime(
            config=SwarmConfig(drone_count=4, waypoint_count=4, failure_tick=None),
            seed=31,
        )
        await self.runtime.start()

    async def asyncTearDown(self) -> None:
        await self.runtime.stop()

    async def test_runtime_updates_tick_seconds_and_render_stride_live(self) -> None:
        updated = await self.runtime.update_config(
            drone_count=8,
            waypoint_count=8,
            tick_seconds=0.04,
            render_stride=2,
            speed_multiplier=4.0,
            assignment_strategy="swarmraft",
            swarmraft_attacked_drones=1,
            swarmraft_fault_budget=1,
            swarmraft_enable_gnss_attack=True,
            swarmraft_enable_range_attack=True,
        )

        self.assertEqual(updated["drone_count"], 8)
        self.assertEqual(updated["waypoint_count"], 8)
        self.assertEqual(updated["tick_seconds"], 0.04)
        self.assertEqual(updated["render_stride"], 2)
        self.assertEqual(updated["speed_multiplier"], 4.0)
        self.assertEqual(updated["assignment_strategy"], "swarmraft")
        self.assertEqual(updated["swarmraft_attacked_drones"], 1)
        self.assertEqual(updated["swarmraft_fault_budget"], 1)
        self.assertTrue(updated["swarmraft_enable_gnss_attack"])
        self.assertTrue(updated["swarmraft_enable_range_attack"])
        self.assertTrue(self.runtime.process.is_alive())

        snapshot = await self.runtime.snapshot()
        self.assertEqual(snapshot["config"]["drone_count"], 8)
        self.assertEqual(snapshot["config"]["waypoint_count"], 8)
        self.assertEqual(snapshot["config"]["tick_seconds"], 0.04)
        self.assertEqual(snapshot["config"]["render_stride"], 2)
        self.assertEqual(snapshot["config"]["speed_multiplier"], 4.0)
        self.assertEqual(snapshot["config"]["assignment_strategy"], "swarmraft")
        self.assertEqual(snapshot["config"]["swarmraft_attacked_drones"], 1)
        self.assertEqual(snapshot["config"]["swarmraft_fault_budget"], 1)
        self.assertEqual(len(snapshot["drones"]), 8)
        self.assertEqual(len(snapshot["waypoints"]), 8)
        self.assertIsInstance(self.runtime.latest_snapshot_msgpack, bytes)


class TransportBenchmarkTest(unittest.TestCase):
    def test_transport_benchmark_returns_expected_fields(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(drone_count=4, waypoint_count=4, planning_interval=1, failure_tick=None),
            seed=29,
        )
        snapshot = simulator.step()

        results = benchmark_snapshot_encodings(snapshot, iterations=5)

        self.assertIn("json_backend", results)
        self.assertIn("json_encode_seconds", results)
        self.assertIn("msgpack_encode_seconds", results)
        self.assertIn("msgpack_decode_seconds", results)


if __name__ == "__main__":
    unittest.main()
