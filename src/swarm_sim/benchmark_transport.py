from __future__ import annotations

import argparse
import json

from swarm_sim.simulator import SwarmConfig, SwarmSimulator
from swarm_sim.transport import benchmark_snapshot_encodings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark snapshot transport encodings.")
    parser.add_argument("--agents", type=int, default=128, help="Number of drones and waypoints.")
    parser.add_argument("--steps", type=int, default=24, help="Steps to advance before benchmarking.")
    parser.add_argument(
        "--iterations",
        type=int,
        default=1000,
        help="How many encode/decode iterations to time.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
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
    snapshot = simulator.snapshot()
    for _ in range(args.steps):
        snapshot = simulator.step()

    results = benchmark_snapshot_encodings(snapshot, iterations=args.iterations)
    results["agents"] = args.agents
    results["steps"] = args.steps

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print("Transport Benchmark")
    print(f"agents: {results['agents']}")
    print(f"steps: {results['steps']}")
    print(f"iterations: {results['iterations']}")
    print(f"json_backend: {results['json_backend']}")
    print(f"json_encode_seconds: {results['json_encode_seconds']}")
    print(f"json_size_bytes: {results['json_size_bytes']}")
    print(f"msgpack_encode_seconds: {results['msgpack_encode_seconds']}")
    print(f"msgpack_size_bytes: {results['msgpack_size_bytes']}")
    print(f"msgpack_decode_seconds: {results['msgpack_decode_seconds']}")


if __name__ == "__main__":
    main()
