from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from swarm_sim.cli import INSTALL_URL, build_parser, format_swarm_banner, frame_delay_seconds, render_ascii, summarize_metrics
from swarm_sim.simulator import SwarmConfig, SwarmSimulator


class SwarmCliTest(unittest.TestCase):
    def test_swarm_banner_contains_wordmark(self) -> None:
        banner = format_swarm_banner()

        self.assertIn("####", banner)
        self.assertIn("#   #", banner)

    def test_cli_parser_help_contains_install_and_help(self) -> None:
        help_text = build_parser().format_help()

        self.assertIn(INSTALL_URL, help_text)
        self.assertIn("swarm-cli --help", help_text)

    def test_render_ascii_includes_header_and_legend(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(drone_count=3, waypoint_count=3, failure_tick=None),
            seed=5,
        )
        snapshot = simulator.snapshot()

        output = render_ascii(snapshot, cols=20, rows=8)

        self.assertIn("tick=0", output)
        self.assertIn("legend:", output)
        self.assertIn("+--------------------+", output)

    def test_summarize_metrics_returns_expected_shape(self) -> None:
        simulator = SwarmSimulator(
            config=SwarmConfig(drone_count=4, waypoint_count=4, planning_interval=1, failure_tick=None),
            seed=7,
        )
        snapshots = [simulator.step() for _ in range(4)]

        metrics = summarize_metrics(
            summaries=[snapshot["summary"] for snapshot in snapshots],
            final_snapshot=snapshots[-1],
            wall_seconds=0.5,
        )

        self.assertIn("final", metrics)
        self.assertIn("mean_cohesion_score", metrics)
        self.assertEqual(metrics["tick"], snapshots[-1]["tick"])

    def test_frame_delay_seconds_uses_speed_factor(self) -> None:
        self.assertAlmostEqual(
            frame_delay_seconds(tick_seconds=0.08, render_every=4, factor=2.0),
            0.16,
        )

    def test_cli_json_output(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "swarm_sim.cli",
                "--steps",
                "6",
                "--agents",
                "4",
                "--waypoints",
                "4",
                "--failure-tick",
                "-1",
                "--json",
            ],
            cwd=ROOT,
            env={
                **os.environ,
                **{"PYTHONPATH": str(SRC)},
            },
            capture_output=True,
            text=True,
            check=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["tick"], 6)
        self.assertIn("final", payload)
        self.assertIn("waypoint_completions", payload["final"])

    def test_cli_without_args_shows_start_screen(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "swarm_sim.cli",
            ],
            cwd=ROOT,
            env={
                **os.environ,
                **{"PYTHONPATH": str(SRC)},
            },
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("error: not enough parameters", result.stderr)
        self.assertIn("swarm-cli --help", result.stderr)
        self.assertIn("####", result.stderr)

    def test_cli_json_output_prints_banner_to_stderr_only(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "swarm_sim.cli",
                "--steps",
                "2",
                "--agents",
                "4",
                "--waypoints",
                "4",
                "--failure-tick",
                "-1",
                "--json",
            ],
            cwd=ROOT,
            env={
                **os.environ,
                **{"PYTHONPATH": str(SRC)},
            },
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertIn("####", result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tick"], 2)


if __name__ == "__main__":
    unittest.main()
