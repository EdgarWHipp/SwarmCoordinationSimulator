from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from swarm_sim.navigation import NavigationGraph


class NavigationGraphTest(unittest.TestCase):
    def test_diagonal_goal_uses_diagonal_first_hop(self) -> None:
        graph = NavigationGraph.build(width=300, height=300, cols=3, rows=3)

        start = 0
        goal = 8
        center = 4

        self.assertEqual(graph.next_hop[start, goal], center)
        self.assertLess(
            float(graph.path_costs[start, goal]),
            float(graph.path_costs[start, 1] + graph.path_costs[1, goal]),
        )

    def test_neighbors_include_diagonal_nodes(self) -> None:
        graph = NavigationGraph.build(width=300, height=300, cols=3, rows=3)

        center_neighbors = graph.neighbor_indices[4]
        valid_neighbors = center_neighbors[center_neighbors >= 0]

        self.assertEqual(len(valid_neighbors), 8)
        self.assertIn(0, valid_neighbors.tolist())
        self.assertIn(8, valid_neighbors.tolist())


if __name__ == "__main__":
    unittest.main()
