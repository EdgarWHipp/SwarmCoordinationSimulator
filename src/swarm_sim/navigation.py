from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush

import numpy as np
from scipy.spatial import cKDTree


@dataclass(slots=True)
class NavigationGraph:
    width: int
    height: int
    cols: int
    rows: int
    node_positions: np.ndarray
    neighbor_indices: np.ndarray
    edge_costs: np.ndarray
    next_hop: np.ndarray
    path_costs: np.ndarray
    tree: cKDTree

    @classmethod
    def build(
        cls,
        *,
        width: int,
        height: int,
        cols: int,
        rows: int,
    ) -> "NavigationGraph":
        xs = np.linspace(40.0, width - 40.0, cols, dtype=np.float32)
        ys = np.linspace(40.0, height - 40.0, rows, dtype=np.float32)
        grid_x, grid_y = np.meshgrid(xs, ys)
        node_positions = np.stack((grid_x.ravel(), grid_y.ravel()), axis=1).astype(np.float32)

        node_count = node_positions.shape[0]
        neighbor_indices = np.full((node_count, 4), -1, dtype=np.int32)
        edge_costs = np.full((node_count, 4), np.inf, dtype=np.float32)

        def node_id(row: int, col: int) -> int:
            return row * cols + col

        for row in range(rows):
            for col in range(cols):
                current = node_id(row, col)
                slots = 0
                for delta_row, delta_col in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    next_row = row + delta_row
                    next_col = col + delta_col
                    if next_row < 0 or next_row >= rows or next_col < 0 or next_col >= cols:
                        continue
                    neighbor = node_id(next_row, next_col)
                    neighbor_indices[current, slots] = neighbor
                    edge_costs[current, slots] = np.float32(
                        np.linalg.norm(node_positions[current] - node_positions[neighbor])
                    )
                    slots += 1

        next_hop = np.full((node_count, node_count), -1, dtype=np.int32)
        path_costs = np.full((node_count, node_count), np.inf, dtype=np.float32)

        for start in range(node_count):
            next_hop[start, start] = start
            path_costs[start, start] = np.float32(0.0)
            for goal in range(node_count):
                if start == goal:
                    continue
                path, cost = _a_star(
                    start=start,
                    goal=goal,
                    node_positions=node_positions,
                    neighbor_indices=neighbor_indices,
                    edge_costs=edge_costs,
                )
                if not path:
                    continue
                next_hop[start, goal] = path[1] if len(path) > 1 else goal
                path_costs[start, goal] = np.float32(cost)

        return cls(
            width=width,
            height=height,
            cols=cols,
            rows=rows,
            node_positions=node_positions,
            neighbor_indices=neighbor_indices,
            edge_costs=edge_costs,
            next_hop=next_hop,
            path_costs=path_costs,
            tree=cKDTree(node_positions),
        )

    def nearest_nodes(self, points: np.ndarray) -> np.ndarray:
        if points.size == 0:
            return np.empty(0, dtype=np.int32)
        _, indices = self.tree.query(points, workers=1)
        return np.asarray(indices, dtype=np.int32)


def _a_star(
    *,
    start: int,
    goal: int,
    node_positions: np.ndarray,
    neighbor_indices: np.ndarray,
    edge_costs: np.ndarray,
) -> tuple[list[int], float]:
    frontier: list[tuple[float, int]] = []
    heappush(frontier, (0.0, start))

    came_from: dict[int, int] = {}
    g_score = {start: 0.0}

    while frontier:
        _, current = heappop(frontier)
        if current == goal:
            break

        for slot in range(neighbor_indices.shape[1]):
            neighbor = int(neighbor_indices[current, slot])
            if neighbor < 0:
                continue
            tentative = g_score[current] + float(edge_costs[current, slot])
            if tentative >= g_score.get(neighbor, float("inf")):
                continue
            came_from[neighbor] = current
            g_score[neighbor] = tentative
            heuristic = float(
                np.linalg.norm(node_positions[neighbor] - node_positions[goal])
            )
            heappush(frontier, (tentative + heuristic, neighbor))

    if goal not in g_score:
        return [], float("inf")

    path = [goal]
    cursor = goal
    while cursor != start:
        cursor = came_from[cursor]
        path.append(cursor)
    path.reverse()
    return path, g_score[goal]
