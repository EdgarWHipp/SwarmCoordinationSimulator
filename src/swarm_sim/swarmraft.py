from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.spatial import cKDTree


@dataclass(slots=True)
class SwarmRaftConfig:
    width: float
    height: float
    gnss_noise_std: float = 6.0
    ins_drift_std: float = 1.4
    range_noise_std: float = 4.0
    residual_threshold: float = 18.0
    min_peer_votes: int = 2


class SwarmRaftLocalizer:
    """Section 3-inspired 2D localization and recovery for SwarmRaft.

    The implementation keeps the simulator lightweight while preserving the
    paper's main stages: noisy local sensing, peer-derived estimates, residual
    voting, and coordinate-wise median recovery.
    """

    def __init__(
        self,
        *,
        drone_count: int,
        rng: np.random.Generator,
        config: SwarmRaftConfig,
    ) -> None:
        self.drone_count = drone_count
        self.rng = rng
        self.config = config
        self.gnss_positions = np.zeros((drone_count, 2), dtype=np.float32)
        self.ins_positions = np.zeros((drone_count, 2), dtype=np.float32)
        self.fused_positions = np.zeros((drone_count, 2), dtype=np.float32)
        self.recovered_positions = np.zeros((drone_count, 2), dtype=np.float32)
        self.residuals = np.zeros(drone_count, dtype=np.float32)
        self.negative_votes = np.zeros(drone_count, dtype=np.int32)
        self.positive_votes = np.zeros(drone_count, dtype=np.int32)
        self.peer_counts = np.zeros(drone_count, dtype=np.int32)
        self.suspected_faulty = np.zeros(drone_count, dtype=bool)
        self.recovered_mask = np.zeros(drone_count, dtype=bool)

    def reset(self, positions: np.ndarray) -> None:
        self.gnss_positions[:] = positions.astype(np.float32)
        self.ins_positions[:] = positions.astype(np.float32)
        self.fused_positions[:] = positions.astype(np.float32)
        self.recovered_positions[:] = positions.astype(np.float32)
        self.residuals.fill(0.0)
        self.negative_votes.fill(0)
        self.positive_votes.fill(0)
        self.peer_counts.fill(0)
        self.suspected_faulty.fill(False)
        self.recovered_mask.fill(False)

    def update(
        self,
        *,
        true_positions: np.ndarray,
        velocities: np.ndarray,
        failed: np.ndarray,
        communication_radius: float,
        tick_seconds: float,
    ) -> None:
        self.gnss_positions[:] = true_positions.astype(np.float32)
        self.ins_positions[failed] = true_positions[failed].astype(np.float32)
        self.fused_positions[failed] = true_positions[failed].astype(np.float32)
        self.recovered_positions[failed] = true_positions[failed].astype(np.float32)
        self.residuals[failed] = 0.0
        self.negative_votes[failed] = 0
        self.positive_votes[failed] = 0
        self.peer_counts[failed] = 0
        self.suspected_faulty[failed] = False
        self.recovered_mask[failed] = False

        active_indices = np.flatnonzero(~failed)
        if active_indices.size == 0:
            return

        gnss_noise = self.rng.normal(
            0.0,
            self.config.gnss_noise_std,
            size=(self.drone_count, 2),
        ).astype(np.float32)
        ins_noise = self.rng.normal(
            0.0,
            self.config.ins_drift_std,
            size=(self.drone_count, 2),
        ).astype(np.float32)
        self.gnss_positions[active_indices] = true_positions[active_indices] + gnss_noise[active_indices]
        self.ins_positions[active_indices] = (
            self.ins_positions[active_indices]
            + velocities[active_indices] * np.float32(tick_seconds)
            + ins_noise[active_indices]
        ).astype(np.float32)
        self._clip_rows(self.gnss_positions, active_indices)
        self._clip_rows(self.ins_positions, active_indices)

        self.fused_positions[active_indices] = (
            (self.gnss_positions[active_indices] * np.float32(0.58))
            + (self.ins_positions[active_indices] * np.float32(0.42))
        ).astype(np.float32)
        self.recovered_positions[active_indices] = self.fused_positions[active_indices]
        self.residuals[active_indices] = np.linalg.norm(
            self.fused_positions[active_indices] - self.gnss_positions[active_indices],
            axis=1,
        ).astype(np.float32)
        self.negative_votes[active_indices] = 0
        self.positive_votes[active_indices] = 0
        self.peer_counts[active_indices] = 0
        self.suspected_faulty[active_indices] = False
        self.recovered_mask[active_indices] = False

        active_positions = true_positions[active_indices]
        if active_indices.size > 1:
            tree = cKDTree(active_positions)
            neighbor_pairs = tree.query_pairs(communication_radius, output_type="ndarray")
        else:
            neighbor_pairs = np.empty((0, 2), dtype=np.int32)

        peer_candidates: list[list[np.ndarray]] = [[] for _ in range(self.drone_count)]
        fused_candidates: list[list[np.ndarray]] = [[] for _ in range(self.drone_count)]
        for index in active_indices.tolist():
            fused_candidates[index].append(self.fused_positions[index].copy())

        for local_left, local_right in neighbor_pairs.tolist():
            left = int(active_indices[local_left])
            right = int(active_indices[local_right])

            left_noise = self.rng.normal(0.0, self.config.range_noise_std, size=2).astype(np.float32)
            right_noise = self.rng.normal(0.0, self.config.range_noise_std, size=2).astype(np.float32)

            estimate_left = (
                self.recovered_positions[right]
                + (true_positions[left] - true_positions[right]).astype(np.float32)
                + left_noise
            ).astype(np.float32)
            estimate_right = (
                self.recovered_positions[left]
                + (true_positions[right] - true_positions[left]).astype(np.float32)
                + right_noise
            ).astype(np.float32)

            peer_candidates[left].append(estimate_left)
            peer_candidates[right].append(estimate_right)
            fused_candidates[left].append(estimate_left)
            fused_candidates[right].append(estimate_right)

            if np.linalg.norm(estimate_left - self.gnss_positions[left]) > self.config.residual_threshold:
                self.negative_votes[left] += 1
            else:
                self.positive_votes[left] += 1
            if np.linalg.norm(estimate_right - self.gnss_positions[right]) > self.config.residual_threshold:
                self.negative_votes[right] += 1
            else:
                self.positive_votes[right] += 1

        self.peer_counts[active_indices] = (
            self.negative_votes[active_indices] + self.positive_votes[active_indices]
        )

        for index in active_indices.tolist():
            candidate_list = fused_candidates[index]
            if len(candidate_list) > 1:
                stacked = np.stack(candidate_list, axis=0).astype(np.float32)
                primary = stacked[0] * np.float32(1.75)
                if stacked.shape[0] == 2:
                    fused = (primary + stacked[1]) / np.float32(2.75)
                else:
                    fused = (primary + stacked[1:].sum(axis=0)) / np.float32(stacked.shape[0] + 0.75)
                self.fused_positions[index] = fused.astype(np.float32)

            self.residuals[index] = np.float32(
                np.linalg.norm(self.fused_positions[index] - self.gnss_positions[index])
            )
            vote_total = int(self.peer_counts[index])
            suspected = (
                (
                    vote_total >= self.config.min_peer_votes
                    and self.negative_votes[index] > self.positive_votes[index]
                )
                or self.residuals[index] > (self.config.residual_threshold * np.float32(1.25))
            )
            self.suspected_faulty[index] = suspected

            if suspected and len(peer_candidates[index]) >= self.config.min_peer_votes:
                peer_stack = np.stack(peer_candidates[index], axis=0).astype(np.float32)
                self.recovered_positions[index] = np.median(peer_stack, axis=0).astype(np.float32)
                self.recovered_mask[index] = True
            else:
                self.recovered_positions[index] = self.fused_positions[index]
                self.recovered_mask[index] = False

        self._clip_rows(self.fused_positions, active_indices)
        self._clip_rows(self.recovered_positions, active_indices)

    def summary(self, *, true_positions: np.ndarray, failed: np.ndarray) -> dict[str, Any]:
        active_mask = ~failed
        active_count = int(np.count_nonzero(active_mask))
        if active_count == 0:
            return {
                "enabled": True,
                "suspected_agents": 0,
                "recovered_agents": 0,
                "mean_gnss_error": 0.0,
                "mean_consensus_error": 0.0,
                "mean_residual": 0.0,
            }

        gnss_error = np.linalg.norm(
            self.gnss_positions[active_mask] - true_positions[active_mask],
            axis=1,
        )
        recovered_error = np.linalg.norm(
            self.recovered_positions[active_mask] - true_positions[active_mask],
            axis=1,
        )
        return {
            "enabled": True,
            "suspected_agents": int(np.count_nonzero(self.suspected_faulty[active_mask])),
            "recovered_agents": int(np.count_nonzero(self.recovered_mask[active_mask])),
            "mean_gnss_error": round(float(gnss_error.mean()), 2),
            "mean_consensus_error": round(float(recovered_error.mean()), 2),
            "mean_residual": round(float(self.residuals[active_mask].mean()), 2),
        }

    def _clip_rows(self, values: np.ndarray, rows: np.ndarray) -> None:
        if rows.size == 0:
            return
        values[rows, 0] = np.clip(values[rows, 0], 0.0, self.config.width).astype(np.float32)
        values[rows, 1] = np.clip(values[rows, 1], 0.0, self.config.height).astype(np.float32)
