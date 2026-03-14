from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


PROTOCOL_STEPS: tuple[str, ...] = (
    "Sense",
    "Inform",
    "Estimate",
    "Evaluate",
    "Recover",
    "Finalize",
)

RECOVERY_FUSED = 0
RECOVERY_MEDIAN = 1
RECOVERY_INS_FALLBACK = 2
RECOVERY_MODE_NAMES: tuple[str, ...] = (
    "fused",
    "median",
    "ins_fallback",
)


@dataclass(slots=True)
class SwarmRaftConfig:
    width: float
    height: float
    gnss_noise_std: float = 6.0
    ins_drift_std: float = 1.4
    range_noise_std: float = 4.0
    residual_threshold: float = 0.0
    min_peer_votes: int = 2
    fault_budget: int = 1
    threshold_k: float = 2.0
    attacked_drones: int = 0
    enable_gnss_attack: bool = False
    enable_range_attack: bool = False
    enable_collusion: bool = False
    gnss_attack_bias_std: float = 42.0
    range_attack_bias_std: float = 18.0


class SwarmRaftLocalizer:
    """Section 3-inspired SwarmRaft localization and recovery loop.

    The implementation keeps the simulator light, but follows the paper's main
    stages more closely than the original prototype:
    - local GNSS + INS reporting
    - leader-side peer/range estimate generation
    - calibrated residual thresholding
    - vote-threshold Byzantine detection tied to the fault budget
    - coordinate-wise median recovery and INS reset
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
        self.local_report_positions = np.zeros((drone_count, 2), dtype=np.float32)
        self.fused_positions = np.zeros((drone_count, 2), dtype=np.float32)
        self.recovered_positions = np.zeros((drone_count, 2), dtype=np.float32)
        self.residuals = np.zeros(drone_count, dtype=np.float32)
        self.negative_votes = np.zeros(drone_count, dtype=np.int32)
        self.positive_votes = np.zeros(drone_count, dtype=np.int32)
        self.peer_counts = np.zeros(drone_count, dtype=np.int32)
        self.suspected_faulty = np.zeros(drone_count, dtype=bool)
        self.recovered_mask = np.zeros(drone_count, dtype=bool)
        self.compromised_mask = np.zeros(drone_count, dtype=bool)
        self.recovery_modes = np.zeros(drone_count, dtype=np.int8)
        self.gnss_attack_vectors = np.zeros((drone_count, 2), dtype=np.float32)
        self.range_attack_biases = np.zeros(drone_count, dtype=np.float32)

        self.calibrated_residual_mean = np.float32(0.0)
        self.calibrated_residual_std = np.float32(0.0)
        self.current_threshold = np.float32(0.0)
        self.current_vote_threshold = 0
        self.last_leader_index = -1
        self.leader_round_applied = False
        self.protocol_phase = "Idle"
        self.true_positive_detections = 0
        self.false_positive_detections = 0
        self.false_negative_detections = 0

        self._recompute_threshold_calibration()

    def reset(self, positions: np.ndarray) -> None:
        base_positions = positions.astype(np.float32)
        self.gnss_positions[:] = base_positions
        self.ins_positions[:] = base_positions
        self.local_report_positions[:] = base_positions
        self.fused_positions[:] = base_positions
        self.recovered_positions[:] = base_positions
        self.residuals.fill(0.0)
        self.negative_votes.fill(0)
        self.positive_votes.fill(0)
        self.peer_counts.fill(0)
        self.suspected_faulty.fill(False)
        self.recovered_mask.fill(False)
        self.compromised_mask.fill(False)
        self.recovery_modes.fill(RECOVERY_FUSED)
        self.gnss_attack_vectors.fill(0.0)
        self.range_attack_biases.fill(0.0)
        self.last_leader_index = -1
        self.leader_round_applied = False
        self.protocol_phase = "Sense"
        self.true_positive_detections = 0
        self.false_positive_detections = 0
        self.false_negative_detections = 0

        self._recompute_threshold_calibration()
        attacked = min(max(int(self.config.attacked_drones), 0), self.drone_count)
        if attacked > 0:
            compromised = self.rng.choice(self.drone_count, size=attacked, replace=False)
            self.compromised_mask[np.asarray(compromised, dtype=np.int32)] = True

    def update(
        self,
        *,
        true_positions: np.ndarray,
        velocities: np.ndarray,
        failed: np.ndarray,
        communication_radius: float,
        tick_seconds: float,
        leader_index: int | None,
        quorum_available: bool,
    ) -> None:
        del communication_radius

        self.last_leader_index = int(leader_index) if leader_index is not None else -1
        self.leader_round_applied = bool(leader_index is not None and quorum_available)
        self.current_vote_threshold = max(int(self.config.fault_budget), 0)
        self.protocol_phase = "Sense"

        self._reset_failed_rows(true_positions, failed)
        active_indices = np.flatnonzero(~failed)
        if active_indices.size == 0:
            self.protocol_phase = "Idle"
            return

        self._advance_sensor_models(
            true_positions=true_positions,
            velocities=velocities,
            failed=failed,
            active_indices=active_indices,
            tick_seconds=tick_seconds,
        )

        if active_indices.size < 2 or leader_index is None or not quorum_available:
            self.protocol_phase = "Fallback"
            self._fallback_to_local_reports(active_indices=active_indices)
            self._compute_detection_quality(failed=failed)
            return

        self._leader_localization_round(
            true_positions=true_positions,
            active_indices=active_indices,
        )
        self.protocol_phase = "Finalize"
        self._compute_detection_quality(failed=failed)

    def summary(self, *, true_positions: np.ndarray, failed: np.ndarray) -> dict[str, Any]:
        active_mask = ~failed
        active_count = int(np.count_nonzero(active_mask))
        if active_count == 0:
            return {
                "enabled": True,
                "attacked_agents": 0,
                "suspected_agents": 0,
                "recovered_agents": 0,
                "true_positive_detections": 0,
                "false_positive_detections": 0,
                "false_negative_detections": 0,
                "mean_gnss_error": 0.0,
                "median_gnss_error": 0.0,
                "mean_consensus_error": 0.0,
                "median_consensus_error": 0.0,
                "mean_residual": 0.0,
                "residual_threshold": 0.0,
                "vote_threshold": 0,
                "leader_round_applied": False,
                "protocol_phase": "Idle",
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
            "attacked_agents": int(np.count_nonzero(self.compromised_mask[active_mask])),
            "suspected_agents": int(np.count_nonzero(self.suspected_faulty[active_mask])),
            "recovered_agents": int(np.count_nonzero(self.recovered_mask[active_mask])),
            "true_positive_detections": int(self.true_positive_detections),
            "false_positive_detections": int(self.false_positive_detections),
            "false_negative_detections": int(self.false_negative_detections),
            "mean_gnss_error": round(float(gnss_error.mean()), 2),
            "median_gnss_error": round(float(np.median(gnss_error)), 2),
            "mean_consensus_error": round(float(recovered_error.mean()), 2),
            "median_consensus_error": round(float(np.median(recovered_error)), 2),
            "mean_residual": round(float(self.residuals[active_mask].mean()), 2),
            "residual_threshold": round(float(self.current_threshold), 2),
            "vote_threshold": int(self.current_vote_threshold),
            "leader_round_applied": bool(self.leader_round_applied),
            "protocol_phase": self.protocol_phase,
        }

    def _advance_sensor_models(
        self,
        *,
        true_positions: np.ndarray,
        velocities: np.ndarray,
        failed: np.ndarray,
        active_indices: np.ndarray,
        tick_seconds: float,
    ) -> None:
        self._advance_attacks(active_indices)

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

        gnss_attack_mask = (
            self.compromised_mask
            & (~failed)
            & bool(self.config.enable_gnss_attack)
        )
        self.gnss_positions[active_indices] = true_positions[active_indices] + gnss_noise[active_indices]
        if np.any(gnss_attack_mask):
            self.gnss_positions[gnss_attack_mask] += self.gnss_attack_vectors[gnss_attack_mask]

        self.ins_positions[active_indices] = (
            self.ins_positions[active_indices]
            + velocities[active_indices] * np.float32(tick_seconds)
            + ins_noise[active_indices]
        ).astype(np.float32)

        self._clip_rows(self.gnss_positions, active_indices)
        self._clip_rows(self.ins_positions, active_indices)

        gnss_var = self._gnss_variance()
        ins_var = self._ins_variance()
        self.local_report_positions[active_indices] = self._variance_fuse_rows(
            primary=self.gnss_positions[active_indices],
            secondary=self.ins_positions[active_indices],
            primary_variance=gnss_var,
            secondary_variance=ins_var,
        )

        self.fused_positions[active_indices] = self.local_report_positions[active_indices]
        self.recovered_positions[active_indices] = self.local_report_positions[active_indices]
        self.residuals[active_indices] = np.linalg.norm(
            self.local_report_positions[active_indices] - self.gnss_positions[active_indices],
            axis=1,
        ).astype(np.float32)
        self.negative_votes[active_indices] = 0
        self.positive_votes[active_indices] = 0
        self.peer_counts[active_indices] = 0
        self.suspected_faulty[active_indices] = False
        self.recovered_mask[active_indices] = False
        self.recovery_modes[active_indices] = RECOVERY_FUSED

    def _leader_localization_round(
        self,
        *,
        true_positions: np.ndarray,
        active_indices: np.ndarray,
    ) -> None:
        active_positions = true_positions[active_indices].astype(np.float32)
        report_positions = self.local_report_positions[active_indices].astype(np.float32)
        report_deltas = report_positions[:, None, :] - report_positions[None, :, :]
        report_norms = np.linalg.norm(report_deltas, axis=2, keepdims=True).astype(np.float32)
        safe_report_norms = np.maximum(report_norms, np.float32(1e-4))
        directions = report_deltas / safe_report_norms

        true_deltas = active_positions[:, None, :] - active_positions[None, :, :]
        measured_ranges = np.linalg.norm(true_deltas, axis=2).astype(np.float32)
        measured_ranges += self.rng.normal(
            0.0,
            self.config.range_noise_std,
            size=measured_ranges.shape,
        ).astype(np.float32)

        if self.config.enable_range_attack:
            range_bias = self.range_attack_biases[active_indices]
            compromised = self.compromised_mask[active_indices]
            bias_matrix = (
                range_bias[:, None] * compromised[:, None].astype(np.float32)
                + range_bias[None, :] * compromised[None, :].astype(np.float32)
            ).astype(np.float32)
            measured_ranges += bias_matrix

        gnss_var = self._gnss_variance()
        range_var = self._range_estimate_variance()
        threshold = self.current_threshold

        for target_local, target_global in enumerate(active_indices.tolist()):
            peer_estimates: list[np.ndarray] = []
            positive_estimates: list[np.ndarray] = []
            negative_votes = 0
            positive_votes = 0

            for peer_local, peer_global in enumerate(active_indices.tolist()):
                if peer_local == target_local:
                    continue

                direction = directions[target_local, peer_local]
                if float(np.linalg.norm(direction)) <= 1e-4:
                    fallback = self.ins_positions[target_global] - self.ins_positions[peer_global]
                    fallback_norm = float(np.linalg.norm(fallback))
                    if fallback_norm > 1e-4:
                        direction = (fallback / fallback_norm).astype(np.float32)
                    else:
                        direction = np.array([1.0, 0.0], dtype=np.float32)

                range_estimate = (
                    self.local_report_positions[peer_global]
                    + direction * measured_ranges[target_local, peer_local]
                ).astype(np.float32)

                peer_fused = self._variance_fuse_row(
                    primary=self.gnss_positions[target_global],
                    secondary=range_estimate,
                    primary_variance=gnss_var,
                    secondary_variance=range_var,
                )
                peer_estimates.append(peer_fused)

                residual = float(np.linalg.norm(peer_fused - self.gnss_positions[target_global]))
                vote_negative = residual > threshold
                if self.config.enable_collusion and self.compromised_mask[peer_global]:
                    vote_negative = not bool(self.compromised_mask[target_global])

                if vote_negative:
                    negative_votes += 1
                else:
                    positive_votes += 1
                    positive_estimates.append(peer_fused)

            self.negative_votes[target_global] = negative_votes
            self.positive_votes[target_global] = positive_votes
            self.peer_counts[target_global] = negative_votes + positive_votes

            candidate_stack = positive_estimates if positive_estimates else peer_estimates
            if candidate_stack:
                self.fused_positions[target_global] = np.mean(
                    np.stack(candidate_stack, axis=0).astype(np.float32),
                    axis=0,
                ).astype(np.float32)
            else:
                self.fused_positions[target_global] = self.local_report_positions[target_global]

            self.residuals[target_global] = np.float32(
                np.linalg.norm(self.fused_positions[target_global] - self.gnss_positions[target_global])
            )

            suspected = (
                self.peer_counts[target_global] >= max(self.config.min_peer_votes, 1)
                and self.negative_votes[target_global] > self.current_vote_threshold
            )
            self.suspected_faulty[target_global] = suspected

            if suspected:
                trusted_candidates = positive_estimates
                if len(trusted_candidates) > self.current_vote_threshold:
                    peer_stack = np.stack(trusted_candidates, axis=0).astype(np.float32)
                    recovered = np.median(peer_stack, axis=0).astype(np.float32)
                    self.recovery_modes[target_global] = RECOVERY_MEDIAN
                else:
                    recovered = self.ins_positions[target_global].astype(np.float32)
                    self.recovery_modes[target_global] = RECOVERY_INS_FALLBACK
                self.recovered_positions[target_global] = recovered
                self.recovered_mask[target_global] = True
                self.ins_positions[target_global] = recovered
            else:
                self.recovered_positions[target_global] = self.fused_positions[target_global]
                self.recovered_mask[target_global] = False
                self.recovery_modes[target_global] = RECOVERY_FUSED

        self._clip_rows(self.fused_positions, active_indices)
        self._clip_rows(self.recovered_positions, active_indices)
        self._clip_rows(self.ins_positions, active_indices)

    def _fallback_to_local_reports(self, *, active_indices: np.ndarray) -> None:
        self.fused_positions[active_indices] = self.local_report_positions[active_indices]
        self.recovered_positions[active_indices] = self.local_report_positions[active_indices]
        self.residuals[active_indices] = np.linalg.norm(
            self.local_report_positions[active_indices] - self.gnss_positions[active_indices],
            axis=1,
        ).astype(np.float32)

    def _advance_attacks(self, active_indices: np.ndarray) -> None:
        if active_indices.size == 0:
            return
        compromised_active = self.compromised_mask[active_indices]
        if not np.any(compromised_active):
            return

        if self.config.enable_gnss_attack:
            step = self.rng.normal(
                0.0,
                max(self.config.gnss_attack_bias_std * 0.35, 1e-3),
                size=(active_indices.size, 2),
            ).astype(np.float32)
            updated = (
                self.gnss_attack_vectors[active_indices] * np.float32(0.72)
                + step
            ).astype(np.float32)
            limit = np.float32(max(self.config.gnss_attack_bias_std * 2.5, 1.0))
            updated = np.clip(updated, -limit, limit).astype(np.float32)
            self.gnss_attack_vectors[active_indices[compromised_active]] = updated[compromised_active]

        if self.config.enable_range_attack:
            step = self.rng.normal(
                0.0,
                max(self.config.range_attack_bias_std * 0.35, 1e-3),
                size=active_indices.size,
            ).astype(np.float32)
            updated = (
                self.range_attack_biases[active_indices] * np.float32(0.72)
                + step
            ).astype(np.float32)
            limit = np.float32(max(self.config.range_attack_bias_std * 2.5, 1.0))
            updated = np.clip(updated, -limit, limit).astype(np.float32)
            self.range_attack_biases[active_indices[compromised_active]] = updated[compromised_active]

    def _reset_failed_rows(self, true_positions: np.ndarray, failed: np.ndarray) -> None:
        self.gnss_positions[failed] = true_positions[failed].astype(np.float32)
        self.ins_positions[failed] = true_positions[failed].astype(np.float32)
        self.local_report_positions[failed] = true_positions[failed].astype(np.float32)
        self.fused_positions[failed] = true_positions[failed].astype(np.float32)
        self.recovered_positions[failed] = true_positions[failed].astype(np.float32)
        self.residuals[failed] = 0.0
        self.negative_votes[failed] = 0
        self.positive_votes[failed] = 0
        self.peer_counts[failed] = 0
        self.suspected_faulty[failed] = False
        self.recovered_mask[failed] = False
        self.recovery_modes[failed] = RECOVERY_FUSED

    def _compute_detection_quality(self, *, failed: np.ndarray) -> None:
        active_mask = ~failed
        compromised_active = self.compromised_mask & active_mask
        suspected_active = self.suspected_faulty & active_mask
        self.true_positive_detections = int(np.count_nonzero(compromised_active & suspected_active))
        self.false_positive_detections = int(np.count_nonzero((~self.compromised_mask) & suspected_active & active_mask))
        self.false_negative_detections = int(np.count_nonzero(compromised_active & (~suspected_active)))

    def _recompute_threshold_calibration(self) -> None:
        gnss_var = self._gnss_variance()
        range_var = self._range_estimate_variance()
        secondary_weight = gnss_var / (gnss_var + range_var)
        residual_axis_std = secondary_weight * np.sqrt(gnss_var + range_var)
        self.calibrated_residual_mean = np.float32(residual_axis_std * np.sqrt(np.pi / 2.0))
        self.calibrated_residual_std = np.float32(
            residual_axis_std * np.sqrt((4.0 - np.pi) / 2.0)
        )
        floor = np.float32(max(self.config.residual_threshold, 0.0))
        self.current_threshold = np.float32(
            max(
                float(floor),
                float(
                    self.calibrated_residual_mean
                    + np.float32(self.config.threshold_k) * self.calibrated_residual_std
                ),
            )
        )

    def _gnss_variance(self) -> np.float32:
        return np.float32(max(self.config.gnss_noise_std, 1e-3) ** 2)

    def _ins_variance(self) -> np.float32:
        return np.float32(max(self.config.ins_drift_std, 1e-3) ** 2)

    def _range_estimate_variance(self) -> np.float32:
        gnss_var = self._gnss_variance()
        ins_var = self._ins_variance()
        local_report_var = np.float32(1.0) / ((np.float32(1.0) / gnss_var) + (np.float32(1.0) / ins_var))
        range_var = np.float32(max(self.config.range_noise_std, 1e-3) ** 2)
        return local_report_var + range_var

    def _variance_fuse_rows(
        self,
        *,
        primary: np.ndarray,
        secondary: np.ndarray,
        primary_variance: np.float32,
        secondary_variance: np.float32,
    ) -> np.ndarray:
        weight_primary = secondary_variance / (primary_variance + secondary_variance)
        weight_secondary = np.float32(1.0) - weight_primary
        return (
            primary * np.float32(weight_primary) + secondary * np.float32(weight_secondary)
        ).astype(np.float32)

    def _variance_fuse_row(
        self,
        *,
        primary: np.ndarray,
        secondary: np.ndarray,
        primary_variance: np.float32,
        secondary_variance: np.float32,
    ) -> np.ndarray:
        fused = self._variance_fuse_rows(
            primary=primary[None, :].astype(np.float32),
            secondary=secondary[None, :].astype(np.float32),
            primary_variance=primary_variance,
            secondary_variance=secondary_variance,
        )
        return fused[0]

    def _clip_rows(self, values: np.ndarray, rows: np.ndarray) -> None:
        if rows.size == 0:
            return
        values[rows, 0] = np.clip(values[rows, 0], 0.0, self.config.width).astype(np.float32)
        values[rows, 1] = np.clip(values[rows, 1], 0.0, self.config.height).astype(np.float32)
