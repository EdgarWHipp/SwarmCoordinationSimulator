from __future__ import annotations

import argparse
import json
import os
import sys
import time
from statistics import fmean
from typing import Any

from swarm_sim.simulator import SwarmConfig, SwarmSimulator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the swarm simulator in a terminal and print metrics."
    )
    parser.add_argument("--steps", type=int, default=240, help="Number of simulation ticks to run.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed for repeatable runs.")
    parser.add_argument("--agents", type=int, default=12, help="Number of drones.")
    parser.add_argument("--waypoints", type=int, default=None, help="Number of waypoints.")
    parser.add_argument(
        "--assignment-strategy",
        choices=("consensus", "greedy"),
        default="consensus",
        help="Waypoint assignment strategy.",
    )
    parser.add_argument(
        "--backend",
        choices=("numpy", "taichi"),
        default="numpy",
        help="Physics backend to use.",
    )
    parser.add_argument(
        "--failure-tick",
        type=int,
        default=240,
        help="Tick to inject a random failure. Use -1 to disable.",
    )
    parser.add_argument(
        "--planning-interval",
        type=int,
        default=6,
        help="Ticks between planning epochs.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Render an ASCII 2D view while the simulation runs.",
    )
    parser.add_argument(
        "--render-every",
        type=int,
        default=4,
        help="Render every N ticks in live mode.",
    )
    parser.add_argument(
        "--cols",
        type=int,
        default=64,
        help="ASCII viewport width in characters.",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=24,
        help="ASCII viewport height in characters.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Optional delay between rendered frames in seconds.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the final metrics payload as JSON.",
    )
    return parser.parse_args()


def _grid_index(value: float, maximum: float, cells: int) -> int:
    if cells <= 1 or maximum <= 0:
        return 0
    ratio = min(max(value / maximum, 0.0), 0.999999)
    return int(ratio * cells)


def render_ascii(snapshot: dict[str, Any], *, cols: int, rows: int) -> str:
    config = snapshot["config"]
    grid = [[" " for _ in range(cols)] for _ in range(rows)]

    def place(x: float, y: float, char: str) -> None:
        col = _grid_index(x, float(config["width"]), cols)
        row = _grid_index(y, float(config["height"]), rows)
        current = grid[row][col]
        if current == " ":
            grid[row][col] = char
        elif current != char:
            grid[row][col] = "@"

    for waypoint in snapshot["waypoints"]:
        char = "w" if waypoint["claimed_by"] is None else "W"
        place(waypoint["position"]["x"], waypoint["position"]["y"], char)

    for drone in snapshot["drones"]:
        char = "x" if drone["failed"] else "d"
        place(drone["position"]["x"], drone["position"]["y"], char)

    body = "\n".join("".join(row) for row in grid)
    summary = snapshot["summary"]
    header = (
        f"tick={snapshot['tick']} elapsed={snapshot['elapsed_seconds']:.2f}s "
        f"active={summary['active_agents']} failed={summary['failed_agents']} "
        f"collisions={summary['active_collision_pairs']} completions={summary['waypoint_completions']}"
    )
    legend = "legend: d=drone x=failed drone w=free waypoint W=claimed waypoint @=overlap"
    border = "+" + ("-" * cols) + "+"
    framed = "\n".join(f"|{row}|" for row in body.splitlines())
    return "\n".join((header, legend, border, framed, border))


def summarize_metrics(
    *,
    summaries: list[dict[str, Any]],
    final_snapshot: dict[str, Any],
    wall_seconds: float,
) -> dict[str, Any]:
    final_summary = final_snapshot["summary"]
    return {
        "tick": final_snapshot["tick"],
        "elapsed_seconds": final_snapshot["elapsed_seconds"],
        "wall_seconds": round(wall_seconds, 3),
        "ticks_per_wall_second": round(final_snapshot["tick"] / max(wall_seconds, 1e-6), 2),
        "final": final_summary,
        "mean_cohesion_score": round(fmean(item["cohesion_score"] for item in summaries), 4),
        "mean_consensus_success_ratio": round(
            fmean(item["consensus_success_ratio"] for item in summaries), 4
        ),
        "mean_active_collision_pairs": round(
            fmean(item["active_collision_pairs"] for item in summaries), 4
        ),
        "max_waypoint_completion_rate_per_min": round(
            max(item["waypoint_completion_rate_per_min"] for item in summaries),
            2,
        ),
        "events_tail": final_snapshot["events"][-5:],
    }


def print_live_frame(snapshot: dict[str, Any], *, cols: int, rows: int) -> None:
    frame = render_ascii(snapshot, cols=cols, rows=rows)
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.write(frame)
    sys.stdout.write("\n")
    sys.stdout.flush()


def format_metrics_text(metrics: dict[str, Any]) -> str:
    final = metrics["final"]
    lines = [
        "Simulation Metrics",
        f"tick: {metrics['tick']}",
        f"simulated_seconds: {metrics['elapsed_seconds']}",
        f"wall_seconds: {metrics['wall_seconds']}",
        f"ticks_per_wall_second: {metrics['ticks_per_wall_second']}",
        f"active_agents: {final['active_agents']}",
        f"failed_agents: {final['failed_agents']}",
        f"active_collision_pairs: {final['active_collision_pairs']}",
        f"collision_events_total: {final['collision_events_total']}",
        f"waypoint_completions: {final['waypoint_completions']}",
        f"waypoint_completion_rate_per_min: {final['waypoint_completion_rate_per_min']}",
        f"cohesion_score: {final['cohesion_score']}",
        f"average_speed: {final['average_speed']}",
        f"consensus_success_ratio: {final['consensus_success_ratio']}",
        f"assignment_changes: {final['assignment_changes']}",
        f"dropout_detected: {final['dropout_detected']}",
        f"mean_cohesion_score: {metrics['mean_cohesion_score']}",
        f"mean_consensus_success_ratio: {metrics['mean_consensus_success_ratio']}",
        f"mean_active_collision_pairs: {metrics['mean_active_collision_pairs']}",
        f"max_waypoint_completion_rate_per_min: {metrics['max_waypoint_completion_rate_per_min']}",
    ]
    if metrics["events_tail"]:
        lines.append("events_tail:")
        lines.extend(f"  - {event}" for event in metrics["events_tail"])
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    waypoint_count = args.waypoints if args.waypoints is not None else args.agents
    failure_tick = None if args.failure_tick < 0 else args.failure_tick
    simulator = SwarmSimulator(
        config=SwarmConfig(
            drone_count=args.agents,
            waypoint_count=waypoint_count,
            planning_interval=args.planning_interval,
            assignment_strategy=args.assignment_strategy,
            physics_backend=args.backend,
            failure_tick=failure_tick,
        ),
        seed=args.seed,
    )

    summaries: list[dict[str, Any]] = []
    snapshot = simulator.snapshot()
    if args.live:
        print_live_frame(snapshot, cols=args.cols, rows=args.rows)
        if args.sleep > 0:
            time.sleep(args.sleep)

    start = time.perf_counter()
    for _ in range(args.steps):
        snapshot = simulator.step()
        summaries.append(snapshot["summary"])
        if args.live and (
            snapshot["tick"] % max(1, args.render_every) == 0 or snapshot["tick"] == args.steps
        ):
            print_live_frame(snapshot, cols=args.cols, rows=args.rows)
            if args.sleep > 0:
                time.sleep(args.sleep)
    wall_seconds = time.perf_counter() - start

    metrics = summarize_metrics(
        summaries=summaries or [snapshot["summary"]],
        final_snapshot=snapshot,
        wall_seconds=wall_seconds,
    )
    if args.live and os.environ.get("TERM"):
        sys.stdout.write("\n")

    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(format_metrics_text(metrics))


if __name__ == "__main__":
    main()
