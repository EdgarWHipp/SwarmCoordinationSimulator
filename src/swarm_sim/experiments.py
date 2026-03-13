from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

from swarm_sim.simulator import SwarmConfig, SwarmSimulator


DEFAULT_OUTPUT_DIR = Path("artifacts/experiments/latest")


@dataclass(slots=True)
class ExperimentScenario:
    name: str
    description: str
    steps: int = 360
    seeds: tuple[int, ...] = (7, 13, 21)
    frame_stride: int = 4
    config_overrides: dict[str, Any] = field(default_factory=dict)


DEFAULT_SCENARIOS: tuple[ExperimentScenario, ...] = (
    ExperimentScenario(
        name="raft-baseline",
        description="Raft leader election with replicated waypoint assignments and no failures.",
        config_overrides={
            "assignment_strategy": "raft",
            "failure_tick": None,
        },
    ),
    ExperimentScenario(
        name="raft-dropout",
        description="Raft assignment under single-agent dropout with leader failover if needed.",
        config_overrides={
            "assignment_strategy": "raft",
            "failure_tick": 240,
        },
    ),
    ExperimentScenario(
        name="swarmraft-baseline",
        description="SwarmRaft localization fusion with Raft coordination and no failures.",
        config_overrides={
            "assignment_strategy": "swarmraft",
            "failure_tick": None,
        },
    ),
    ExperimentScenario(
        name="greedy-dropout",
        description="Nearest-waypoint greedy assignment under dropout for comparison.",
        config_overrides={
            "assignment_strategy": "greedy",
            "failure_tick": 240,
        },
    ),
    ExperimentScenario(
        name="heuristic-consensus-dropout",
        description="Legacy local-vote consensus heuristic under dropout for comparison against Raft.",
        config_overrides={
            "assignment_strategy": "consensus",
            "failure_tick": 240,
            "communication_radius": 140.0,
        },
    ),
)


def minimize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "tick": snapshot["tick"],
        "elapsed_seconds": snapshot["elapsed_seconds"],
        "summary": snapshot["summary"],
        "drones": snapshot["drones"],
        "waypoints": snapshot["waypoints"],
        "events": snapshot["events"][-3:],
    }


def summarize_run(
    *,
    scenario: ExperimentScenario,
    seed: int,
    config: SwarmConfig,
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    summaries = [snapshot["summary"] for snapshot in snapshots]
    first_completion = next(
        (
            snapshot
            for snapshot in snapshots
            if snapshot["summary"]["waypoint_completions"] > 0
        ),
        None,
    )

    recovery_tick: int | None = None
    if config.failure_tick is not None:
        for snapshot in snapshots:
            if snapshot["tick"] < config.failure_tick:
                continue
            active_with_targets = [
                drone
                for drone in snapshot["drones"]
                if not drone["failed"] and drone["target_waypoint_id"]
            ]
            active_count = snapshot["summary"]["active_agents"]
            if len(active_with_targets) == active_count:
                recovery_tick = snapshot["tick"] - config.failure_tick
                break

    final_summary = summaries[-1]
    return {
        "scenario_name": scenario.name,
        "seed": seed,
        "steps": scenario.steps,
        "frame_stride": scenario.frame_stride,
        "assignment_strategy": config.assignment_strategy,
        "failure_tick": config.failure_tick,
        "communication_radius": config.communication_radius,
        "final_waypoint_completions": final_summary["waypoint_completions"],
        "final_collision_events_total": final_summary["collision_events_total"],
        "final_completion_rate_per_min": final_summary["waypoint_completion_rate_per_min"],
        "mean_cohesion_score": round(fmean(item["cohesion_score"] for item in summaries), 4),
        "mean_consensus_success_ratio": round(
            fmean(item["consensus_success_ratio"] for item in summaries), 4
        ),
        "mean_active_collision_pairs": round(
            fmean(item["active_collision_pairs"] for item in summaries), 4
        ),
        "mean_assignment_changes": round(
            fmean(item["assignment_changes"] for item in summaries), 4
        ),
        "time_to_first_completion_seconds": (
            first_completion["elapsed_seconds"] if first_completion else None
        ),
        "dropout_recovery_ticks": recovery_tick,
        "dropout_detected": final_summary["dropout_detected"],
        "final_active_agents": final_summary["active_agents"],
    }


def aggregate_runs(runs: list[dict[str, Any]], metric_keys: list[str]) -> dict[str, dict[str, float | None]]:
    aggregate: dict[str, dict[str, float | None]] = {}
    for key in metric_keys:
        values = [run[key] for run in runs if run[key] is not None]
        if not values:
            aggregate[key] = {"mean": None, "stdev": None}
            continue
        aggregate[key] = {
            "mean": round(fmean(values), 4),
            "stdev": round(pstdev(values), 4),
        }
    return aggregate


def select_representative_run(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if len(runs) == 1:
        return runs[0]
    completion_mean = fmean(run["final_waypoint_completions"] for run in runs)
    collision_mean = fmean(run["final_collision_events_total"] for run in runs)
    cohesion_mean = fmean(run["mean_cohesion_score"] for run in runs)
    return min(
        runs,
        key=lambda run: (
            abs(run["final_waypoint_completions"] - completion_mean)
            + abs(run["final_collision_events_total"] - collision_mean)
            + abs(run["mean_cohesion_score"] - cohesion_mean)
        ),
    )


def run_experiments(
    *,
    scenarios: tuple[ExperimentScenario, ...] = DEFAULT_SCENARIOS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    publish_dir: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    playback_dir = output_dir / "playbacks"
    playback_dir.mkdir(parents=True, exist_ok=True)

    all_runs: list[dict[str, Any]] = []
    scenario_records: list[dict[str, Any]] = []

    for scenario in scenarios:
        run_summaries: list[dict[str, Any]] = []
        traces_by_seed: dict[int, dict[str, Any]] = {}

        for seed in scenario.seeds:
            config = SwarmConfig(**scenario.config_overrides)
            simulator = SwarmSimulator(config=config, seed=seed)
            snapshots: list[dict[str, Any]] = []
            frames = [minimize_snapshot(simulator.snapshot())]

            for _ in range(scenario.steps):
                snapshot = simulator.step()
                snapshots.append(snapshot)
                if (
                    snapshot["tick"] % scenario.frame_stride == 0
                    or snapshot["tick"] == scenario.steps
                ):
                    frames.append(minimize_snapshot(snapshot))

            run_summary = summarize_run(
                scenario=scenario,
                seed=seed,
                config=config,
                snapshots=snapshots,
            )
            run_summaries.append(run_summary)
            all_runs.append(run_summary)
            traces_by_seed[seed] = {
                "scenario_name": scenario.name,
                "description": scenario.description,
                "seed": seed,
                "config": config.as_dict(),
                "frames": frames,
            }

        representative = select_representative_run(run_summaries)
        representative_seed = representative["seed"]
        playback_name = f"{scenario.name}.json"
        playback_path = playback_dir / playback_name
        playback_path.write_text(
            json.dumps(traces_by_seed[representative_seed], indent=2),
            encoding="utf-8",
        )

        scenario_records.append(
            {
                "name": scenario.name,
                "description": scenario.description,
                "steps": scenario.steps,
                "seeds": list(scenario.seeds),
                "frame_stride": scenario.frame_stride,
                "config_overrides": scenario.config_overrides,
                "representative_seed": representative_seed,
                "playback_path": str(Path("playbacks") / playback_name),
                "aggregate_metrics": aggregate_runs(
                    run_summaries,
                    [
                        "final_waypoint_completions",
                        "final_collision_events_total",
                        "final_completion_rate_per_min",
                        "mean_cohesion_score",
                        "mean_consensus_success_ratio",
                        "mean_active_collision_pairs",
                        "time_to_first_completion_seconds",
                        "dropout_recovery_ticks",
                    ],
                ),
                "runs": run_summaries,
            }
        )

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "version": 1,
        "default_scenario": scenario_records[0]["name"] if scenario_records else None,
        "scenarios": scenario_records,
    }

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    (output_dir / "run_summaries.json").write_text(
        json.dumps(all_runs, indent=2),
        encoding="utf-8",
    )

    summary_csv_path = output_dir / "summary.csv"
    if all_runs:
        with summary_csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(all_runs[0].keys()))
            writer.writeheader()
            writer.writerows(all_runs)

    if publish_dir is not None:
        publish_dir.mkdir(parents=True, exist_ok=True)
        for item in output_dir.iterdir():
            target = publish_dir / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)

    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run repeatable swarm simulation experiments and export artifacts."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for manifest, summary CSV, and playback JSON files.",
    )
    parser.add_argument(
        "--publish-dir",
        default=None,
        help="Optional directory to mirror the generated artifacts into, such as web/public/data/latest.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = run_experiments(
        output_dir=Path(args.output_dir),
        publish_dir=Path(args.publish_dir) if args.publish_dir else None,
    )
    print(
        json.dumps(
            {
                "generated_at_utc": manifest["generated_at_utc"],
                "scenarios": [scenario["name"] for scenario in manifest["scenarios"]],
                "output_dir": args.output_dir,
                "publish_dir": args.publish_dir,
            },
            indent=2,
        )
    )
