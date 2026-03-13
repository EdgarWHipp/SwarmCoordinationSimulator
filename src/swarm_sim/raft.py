from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


RAFT_FOLLOWER = 0
RAFT_CANDIDATE = 1
RAFT_LEADER = 2


@dataclass(slots=True)
class RaftLogEntry:
    index: int
    term: int
    assignments: tuple[int, ...]


class RaftCoordinator:
    def __init__(
        self,
        *,
        node_count: int,
        rng: np.random.Generator,
        heartbeat_ticks: int,
        election_timeout_min_ticks: int,
        election_timeout_max_ticks: int,
    ) -> None:
        self.node_count = node_count
        self.rng = rng
        self.heartbeat_ticks = heartbeat_ticks
        self.election_timeout_min_ticks = election_timeout_min_ticks
        self.election_timeout_max_ticks = election_timeout_max_ticks
        if self.heartbeat_ticks < 1:
            raise ValueError("heartbeat_ticks must be at least 1.")
        if self.election_timeout_min_ticks < 1:
            raise ValueError("election_timeout_min_ticks must be at least 1.")
        if self.election_timeout_max_ticks < self.election_timeout_min_ticks:
            raise ValueError(
                "election_timeout_max_ticks must be greater than or equal to election_timeout_min_ticks."
            )

        self.current_term = np.zeros(node_count, dtype=np.int32)
        self.voted_for = np.full(node_count, -1, dtype=np.int32)
        self.role = np.full(node_count, RAFT_FOLLOWER, dtype=np.int8)
        self.known_leader = np.full(node_count, -1, dtype=np.int32)
        self.election_deadline_tick = np.zeros(node_count, dtype=np.int32)
        self.commit_index = np.full(node_count, -1, dtype=np.int32)
        self.last_applied = np.full(node_count, -1, dtype=np.int32)
        self.next_index = np.zeros(node_count, dtype=np.int32)
        self.match_index = np.full(node_count, -1, dtype=np.int32)
        self.logs: list[list[RaftLogEntry]] = [[] for _ in range(node_count)]

        self.current_leader = -1
        self.cluster_commit_index = -1
        self.global_last_applied = -1
        self.next_heartbeat_tick = 0
        self.last_election_term = 0
        self.last_elected_leader = -1

    def reset(self, *, current_tick: int) -> None:
        self.current_term.fill(0)
        self.voted_for.fill(-1)
        self.role.fill(RAFT_FOLLOWER)
        self.known_leader.fill(-1)
        self.commit_index.fill(-1)
        self.last_applied.fill(-1)
        self.next_index.fill(0)
        self.match_index.fill(-1)
        self.logs = [[] for _ in range(self.node_count)]
        self.current_leader = -1
        self.cluster_commit_index = -1
        self.global_last_applied = -1
        self.next_heartbeat_tick = current_tick
        self.last_election_term = 0
        self.last_elected_leader = -1

        for node_index in range(self.node_count):
            self.election_deadline_tick[node_index] = (
                current_tick + self._sample_election_timeout()
            )

    def majority_size(self) -> int:
        return (self.node_count // 2) + 1

    def active_nodes(self, failed: np.ndarray) -> np.ndarray:
        return np.flatnonzero(~failed)

    def leader_id(self, failed: np.ndarray) -> int:
        if self.current_leader < 0:
            return -1
        if failed[self.current_leader]:
            return -1
        if self.role[self.current_leader] != RAFT_LEADER:
            return -1
        return self.current_leader

    def quorum_available(self, failed: np.ndarray) -> bool:
        return int(np.count_nonzero(~failed)) >= self.majority_size()

    def status(self, failed: np.ndarray, agent_ids: list[str]) -> dict[str, Any]:
        leader = self.leader_id(failed)
        term = int(self.current_term.max()) if self.current_term.size else 0
        return {
            "leader_id": agent_ids[leader] if leader >= 0 else None,
            "term": term,
            "commit_index": int(self.cluster_commit_index),
            "log_length": max((len(log) for log in self.logs), default=0),
            "quorum_size": self.majority_size(),
            "quorum_available": self.quorum_available(failed),
        }

    def tick(
        self,
        *,
        current_tick: int,
        failed: np.ndarray,
    ) -> list[str]:
        events: list[str] = []
        leader = self.leader_id(failed)
        if leader < 0 and self.current_leader >= 0:
            self.current_leader = -1

        leader = self.leader_id(failed)
        if leader >= 0 and current_tick >= self.next_heartbeat_tick:
            self._send_heartbeats(leader=leader, current_tick=current_tick, failed=failed)

        if self.leader_id(failed) >= 0:
            return events

        timed_out = [
            int(node_index)
            for node_index in self.active_nodes(failed)
            if current_tick >= self.election_deadline_tick[node_index]
        ]
        timed_out.sort(key=lambda node_index: (self.election_deadline_tick[node_index], node_index))
        for node_index in timed_out:
            if self.leader_id(failed) >= 0:
                break
            if self._start_election(node_index=node_index, current_tick=current_tick, failed=failed):
                leader = self.leader_id(failed)
                if leader >= 0:
                    self.last_election_term = int(self.current_term[leader])
                    self.last_elected_leader = leader
                    events.append(
                        f"Raft leader elected: node {leader + 1} in term {self.last_election_term}."
                    )
        return events

    def propose_assignments(
        self,
        *,
        current_tick: int,
        failed: np.ndarray,
        assignments: np.ndarray,
    ) -> tuple[np.ndarray | None, list[str]]:
        events: list[str] = []
        leader = self.leader_id(failed)
        if leader < 0:
            events.append("Raft proposal blocked: no leader elected.")
            return None, events
        if not self.quorum_available(failed):
            events.append("Raft proposal blocked: majority quorum unavailable.")
            return None, events

        leader_log = self.logs[leader]
        entry = RaftLogEntry(
            index=len(leader_log),
            term=int(self.current_term[leader]),
            assignments=tuple(int(value) for value in assignments.tolist()),
        )
        leader_log.append(entry)
        self.match_index[leader] = entry.index
        self.next_index[leader] = len(leader_log)

        self._replicate_all(leader=leader, current_tick=current_tick, failed=failed)
        committed = self._advance_commit_index(leader=leader)
        self._replicate_all(leader=leader, current_tick=current_tick, failed=failed)

        if committed is None:
            events.append(
                f"Raft append in term {self.current_term[leader]} could not commit without majority."
            )
            return None, events

        return np.asarray(committed.assignments, dtype=np.int32), events

    def _reset_deadline(self, *, node_index: int, current_tick: int) -> None:
        self.election_deadline_tick[node_index] = current_tick + self._sample_election_timeout()

    def _sample_election_timeout(self) -> int:
        return int(
            self.rng.integers(
                self.election_timeout_min_ticks,
                self.election_timeout_max_ticks + 1,
            )
        )

    def _log_last_index(self, node_index: int) -> int:
        return len(self.logs[node_index]) - 1

    def _log_last_term(self, node_index: int) -> int:
        if not self.logs[node_index]:
            return 0
        return self.logs[node_index][-1].term

    def _candidate_is_up_to_date(self, candidate: int, voter: int) -> bool:
        candidate_last_term = self._log_last_term(candidate)
        voter_last_term = self._log_last_term(voter)
        if candidate_last_term != voter_last_term:
            return candidate_last_term > voter_last_term
        return self._log_last_index(candidate) >= self._log_last_index(voter)

    def _become_follower(
        self,
        *,
        node_index: int,
        term: int,
        current_tick: int,
        leader_index: int | None = None,
    ) -> None:
        if term > self.current_term[node_index]:
            self.current_term[node_index] = term
            self.voted_for[node_index] = -1
        self.role[node_index] = RAFT_FOLLOWER
        self.known_leader[node_index] = -1 if leader_index is None else leader_index
        self._reset_deadline(node_index=node_index, current_tick=current_tick)
        if node_index == self.current_leader and leader_index is None:
            self.current_leader = -1

    def _become_leader(self, *, node_index: int, current_tick: int, failed: np.ndarray) -> None:
        self.current_leader = node_index
        self.role[node_index] = RAFT_LEADER
        self.known_leader[node_index] = node_index
        self.match_index[node_index] = self._log_last_index(node_index)
        self.next_index[node_index] = len(self.logs[node_index])

        for follower_index in range(self.node_count):
            if follower_index == node_index:
                continue
            if not failed[follower_index]:
                self.role[follower_index] = RAFT_FOLLOWER
                if self.current_term[follower_index] < self.current_term[node_index]:
                    self.current_term[follower_index] = self.current_term[node_index]
                    self.voted_for[follower_index] = -1
                self.known_leader[follower_index] = node_index
                self._reset_deadline(node_index=follower_index, current_tick=current_tick)
            self.next_index[follower_index] = len(self.logs[node_index])
            self.match_index[follower_index] = self._log_last_index(follower_index)
        self.next_heartbeat_tick = current_tick
        self._send_heartbeats(leader=node_index, current_tick=current_tick, failed=failed)

    def _start_election(self, *, node_index: int, current_tick: int, failed: np.ndarray) -> bool:
        if failed[node_index]:
            return False

        self.current_term[node_index] += 1
        current_term = int(self.current_term[node_index])
        self.role[node_index] = RAFT_CANDIDATE
        self.voted_for[node_index] = node_index
        self.known_leader[node_index] = -1
        self.current_leader = -1
        self._reset_deadline(node_index=node_index, current_tick=current_tick)
        votes = 1

        for voter_index in self.active_nodes(failed):
            if voter_index == node_index:
                continue
            if self.current_term[voter_index] > current_term:
                self._become_follower(
                    node_index=node_index,
                    term=int(self.current_term[voter_index]),
                    current_tick=current_tick,
                )
                return False
            if current_term > self.current_term[voter_index]:
                self.current_term[voter_index] = current_term
                self.voted_for[voter_index] = -1
                self.role[voter_index] = RAFT_FOLLOWER
                self.known_leader[voter_index] = -1
            if self.voted_for[voter_index] not in (-1, node_index):
                continue
            if not self._candidate_is_up_to_date(node_index, int(voter_index)):
                continue
            self.voted_for[voter_index] = node_index
            self._reset_deadline(node_index=int(voter_index), current_tick=current_tick)
            votes += 1

        if votes < self.majority_size():
            return False

        self._become_leader(node_index=node_index, current_tick=current_tick, failed=failed)
        return True

    def _replicate_all(self, *, leader: int, current_tick: int, failed: np.ndarray) -> None:
        if failed[leader]:
            self.current_leader = -1
            return
        self.match_index[leader] = self._log_last_index(leader)
        self.next_index[leader] = len(self.logs[leader])
        for follower_index in self.active_nodes(failed):
            if follower_index == leader:
                continue
            self._replicate_to_follower(
                leader=leader,
                follower=int(follower_index),
                current_tick=current_tick,
                failed=failed,
            )

    def _replicate_to_follower(
        self,
        *,
        leader: int,
        follower: int,
        current_tick: int,
        failed: np.ndarray,
    ) -> bool:
        if failed[follower]:
            return False
        if self.current_term[follower] > self.current_term[leader]:
            self._become_follower(
                node_index=leader,
                term=int(self.current_term[follower]),
                current_tick=current_tick,
            )
            return False

        self._become_follower(
            node_index=follower,
            term=int(self.current_term[leader]),
            current_tick=current_tick,
            leader_index=leader,
        )

        while True:
            next_index = int(min(self.next_index[follower], len(self.logs[leader])))
            self.next_index[follower] = next_index
            prev_index = next_index - 1
            follower_log = self.logs[follower]
            if prev_index >= len(follower_log):
                self.next_index[follower] = len(follower_log)
                continue
            if prev_index >= 0:
                leader_prev_term = self.logs[leader][prev_index].term
                if follower_log[prev_index].term != leader_prev_term:
                    del follower_log[prev_index:]
                    self.next_index[follower] = len(follower_log)
                    continue
            break

        leader_entries = self.logs[leader]
        follower_log = self.logs[follower]
        append_from = int(self.next_index[follower])

        conflict_index = append_from
        while conflict_index < len(follower_log) and conflict_index < len(leader_entries):
            if follower_log[conflict_index].term != leader_entries[conflict_index].term:
                del follower_log[conflict_index:]
                break
            conflict_index += 1

        if append_from < len(leader_entries):
            follower_log.extend(leader_entries[append_from:])

        self.match_index[follower] = len(follower_log) - 1
        self.next_index[follower] = len(follower_log)
        self.commit_index[follower] = min(self.commit_index[leader], len(follower_log) - 1)
        return True

    def _send_heartbeats(self, *, leader: int, current_tick: int, failed: np.ndarray) -> None:
        self._replicate_all(leader=leader, current_tick=current_tick, failed=failed)
        self.next_heartbeat_tick = current_tick + max(1, self.heartbeat_ticks)

    def _advance_commit_index(self, *, leader: int) -> RaftLogEntry | None:
        if not self.logs[leader]:
            return None

        current_commit = int(self.cluster_commit_index)
        leader_log = self.logs[leader]
        for candidate_index in range(len(leader_log) - 1, current_commit, -1):
            candidate_entry = leader_log[candidate_index]
            if candidate_entry.term != self.current_term[leader]:
                continue
            replicated = sum(
                1
                for node_index in range(self.node_count)
                if len(self.logs[node_index]) > candidate_index
                and self.logs[node_index][candidate_index].term == candidate_entry.term
            )
            if replicated < self.majority_size():
                continue
            self.cluster_commit_index = candidate_index
            for node_index in range(self.node_count):
                self.commit_index[node_index] = min(candidate_index, len(self.logs[node_index]) - 1)
                self.last_applied[node_index] = max(
                    self.last_applied[node_index],
                    self.commit_index[node_index],
                )
            if self.cluster_commit_index > self.global_last_applied:
                self.global_last_applied = self.cluster_commit_index
                return candidate_entry
            return None
        return None
