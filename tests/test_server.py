from __future__ import annotations

import sys
import unittest
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from swarm_sim.server import create_app


HTTPX_AVAILABLE = importlib.util.find_spec("httpx") is not None
if HTTPX_AVAILABLE:
    from fastapi.testclient import TestClient


class ServerApiTest(unittest.TestCase):
    def test_root_is_api_metadata_not_html_ui(self) -> None:
        if not HTTPX_AVAILABLE:
            self.skipTest("httpx is not installed")
        with TestClient(create_app()) as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")
            self.assertEqual(response.json()["ui"], "Use the Next.js frontend for visualization.")

    def test_config_endpoint_updates_runtime(self) -> None:
        if not HTTPX_AVAILABLE:
            self.skipTest("httpx is not installed")
        with TestClient(create_app()) as client:
            response = client.get("/api/config")
            self.assertEqual(response.status_code, 200)
            self.assertIn("config", response.json())

            update = client.post("/api/config", json={"tick_seconds": 0.04, "render_stride": 2})
            self.assertEqual(update.status_code, 200)
            self.assertEqual(update.json()["config"]["tick_seconds"], 0.04)
            self.assertEqual(update.json()["config"]["render_stride"], 2)


if __name__ == "__main__":
    unittest.main()
