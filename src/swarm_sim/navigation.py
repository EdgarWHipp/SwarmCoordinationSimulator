from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import shortest_path
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

        # Collect edges for the sparse matrix
        edges_row = []
        edges_col = []
        edges_data = []

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
                    cost = float(np.linalg.norm(node_positions[current] - node_positions[neighbor]))
                    
                    neighbor_indices[current, slots] = neighbor
                    edge_costs[current, slots] = np.float32(cost)
                    slots += 1

                    edges_row.append(current)
                    edges_col.append(neighbor)
                    edges_data.append(cost)

        graph_sparse = csr_matrix((edges_data, (edges_row, edges_col)), shape=(node_count, node_count))
        
        path_costs, predecessors = shortest_path(
            csgraph=graph_sparse, 
            directed=False, 
            return_predecessors=True
        )
        
        path_costs = path_costs.astype(np.float32)

        next_hop = np.full((node_count, node_count), -1, dtype=np.int32)

        for start in range(node_count):
            next_hop[start, start] = start
            for goal in range(node_count):
                if start == goal:
                    continue
                # traceback predecessors to find the next hop from start towards goal
                curr = goal
                prev = predecessors[start, curr]
                
                # if unreachable (-9999 from scipy)
                if prev < 0:
                    continue
                    
                while prev != start:
                    curr = prev
                    prev = predecessors[start, curr]
                    
                next_hop[start, goal] = curr

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
