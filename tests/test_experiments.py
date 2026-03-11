from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from swarm_sim.experiments import ExperimentScenario, run_experiments


class ExperimentRunnerTest(unittest.TestCase):
    def test_runner_writes_manifest_and_playback_files(self) -> None:
        scenario = ExperimentScenario(
            name="smoke",
            description="Short smoke scenario for artifact generation.",
            steps=16,
            seeds=(3, 5),
            frame_stride=4,
            config_overrides={
                "drone_count": 4,
                "waypoint_count": 4,
                "planning_interval": 1,
                "failure_tick": None,
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "artifacts"
            manifest = run_experiments(
                scenarios=(scenario,),
                output_dir=output_dir,
            )

            self.assertEqual(manifest["default_scenario"], "smoke")
            self.assertTrue((output_dir / "manifest.json").exists())
            self.assertTrue((output_dir / "run_summaries.json").exists())
            self.assertTrue((output_dir / "summary.csv").exists())

            playback_path = output_dir / manifest["scenarios"][0]["playback_path"]
            self.assertTrue(playback_path.exists())

            playback = json.loads(playback_path.read_text(encoding="utf-8"))
            self.assertEqual(playback["scenario_name"], "smoke")
            self.assertGreaterEqual(len(playback["frames"]), 2)
            self.assertIn("summary", playback["frames"][0])


if __name__ == "__main__":
    unittest.main()
