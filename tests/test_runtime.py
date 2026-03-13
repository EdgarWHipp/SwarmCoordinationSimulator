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
            tick_seconds=0.04,
            render_stride=2,
            assignment_strategy="swarmraft",
        )

        self.assertEqual(updated["tick_seconds"], 0.04)
        self.assertEqual(updated["render_stride"], 2)
        self.assertEqual(updated["assignment_strategy"], "swarmraft")
        self.assertTrue(self.runtime.process.is_alive())

        snapshot = await self.runtime.snapshot()
        self.assertEqual(snapshot["config"]["tick_seconds"], 0.04)
        self.assertEqual(snapshot["config"]["render_stride"], 2)
        self.assertEqual(snapshot["config"]["assignment_strategy"], "swarmraft")
        self.assertIsInstance(self.runtime.latest_snapshot_msgpack, bytes)

    async def test_runtime_can_advance_multiple_ticks_immediately(self) -> None:
        await self.runtime.pause()
        starting_tick = (await self.runtime.snapshot())["tick"]

        payload = await self.runtime.advance(12)

        self.assertEqual(payload["advanced_steps"], 12)
        self.assertGreaterEqual(payload["snapshot"]["tick"], starting_tick + 12)


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
