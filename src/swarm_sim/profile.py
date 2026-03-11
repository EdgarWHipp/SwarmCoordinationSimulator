from __future__ import annotations

import argparse
import cProfile
import pstats
from pathlib import Path

from swarm_sim.simulator import SwarmConfig, SwarmSimulator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile the swarm simulator hot path.")
    parser.add_argument("--agents", type=int, default=256, help="Number of drones and waypoints.")
    parser.add_argument("--steps", type=int, default=240, help="Number of profiled simulation steps.")
    parser.add_argument("--warmup", type=int, default=8, help="Warm-up steps before profiling.")
    parser.add_argument("--top", type=int, default=20, help="How many profiler rows to print.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write a .prof file for snakeviz.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    simulator = SwarmSimulator(
        config=SwarmConfig(
            drone_count=args.agents,
            waypoint_count=args.agents,
            planning_interval=4,
            failure_tick=None,
        )
    )

    for _ in range(args.warmup):
        simulator.step()

    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(args.steps):
        simulator.step()
    profiler.disable()

    if args.output is not None:
        profiler.dump_stats(str(args.output))

    stats = pstats.Stats(profiler)
    stats.sort_stats("cumtime").print_stats(args.top)

    if args.output is not None:
        print(f"\nProfile written to {args.output}")
        print(f"Open with: snakeviz {args.output}")
