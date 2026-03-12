# Swarm Coordination Simulator
--> Phadke A, Medrano FA, Sekharan CN, Chu T. Designing UAV Swarm Experiments: A Simulator Selection and Experiment Design Process. Sensors (Basel). 2023 Aug 23;23(17):7359. doi: 10.3390/s23177359. PMID: 37687817; PMCID: PMC10490248.


A lightweight autonomous swarm coordination simulator built in Python with:

- decentralized waypoint negotiation
- boids-style local motion control
- failure injection and rebalancing
- WebSocket-driven browser visualization
- Prometheus metrics for swarm health observability

This repo is intentionally a 2D first slice. The point is to get a credible distributed-systems prototype working before spending time on a heavier 3D stack.

## What Exists Today

- `SwarmSimulator` models drones, waypoints, consensus rounds, collision detection, and mission-point recycling.
- `swarm-experiments` runs seeded scenario sweeps and exports playback traces plus aggregate metrics.
- `FastAPI` serves a browser UI and streams live snapshots over WebSockets.
- `web/` contains a static-first Next.js 3D console for Vercel deployment.
- `/metrics` exposes Prometheus-friendly swarm health metrics.
- `tests/` covers core simulator behavior.

## Architecture

```text
simulation tick
  -> consensus round assigns waypoint claims
  -> boids steering updates drone motion
  -> collision + completion detectors emit events
  -> snapshot is pushed over WebSocket
  -> Prometheus gauges/counters are updated
```

The current consensus model is deliberately lightweight:

1. Each active drone proposes its best waypoint using distance and contention-aware scoring.
2. Nearby peers vote on visible proposals inside a communication radius.
3. Winners claim waypoints, and unassigned drones fall back to the nearest free objective.

That gives you a clean bridge between classic boids behavior and a more distributed coordination story without implementing full replicated-log consensus where it is not needed.

## Quick Start

### Python simulator

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
swarm-sim
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Useful endpoints:

- `/api/state` for the latest snapshot
- `/ws` for live state streaming
- `/metrics` for Prometheus scraping

Run the simulator tests with:

```bash
python3 -m unittest discover -s tests
```

### Experiment runner

Generate repeatable experiment artifacts:

```bash
PYTHONPATH=src python3 -m swarm_sim.experiments --output-dir artifacts/experiments/latest
```

Publish those artifacts into the Next.js app:

```bash
PYTHONPATH=src python3 -c "from pathlib import Path; from swarm_sim.experiments import run_experiments; run_experiments(output_dir=Path('artifacts/experiments/latest'), publish_dir=Path('web/public/data/latest'))"
```

### Next.js 3D console

From `web/`:

```bash
npm install
npm run dev
```

The frontend reads static files from `web/public/data/latest`, so it can be deployed without a live Python service.

## Metrics

The simulator currently exports:

- `swarm_active_agents`
- `swarm_failed_agents`
- `swarm_cohesion_score`
- `swarm_average_speed`
- `swarm_consensus_success_ratio`
- `swarm_dropout_detected`
- `swarm_assignment_changes`
- `swarm_collision_events_total`
- `swarm_waypoint_completions_total`



### Swarm and Multi-Agent Foundations

- Craig Reynolds, *Flocks, Herds, and Schools: A Distributed Behavioral Model*:
  [red3d.com/cwr/papers/1987/boids.html](https://red3d.com/cwr/papers/1987/boids.html)
- Eric Bonabeau, Marco Dorigo, Guy Theraulaz, *Swarm Intelligence: From Natural to Artificial Systems*:
  [academic.oup.com/book/40811](https://academic.oup.com/book/40811)

### Consensus and Coordination
- TO DO: SwarnRaft: Leveraging Consensus for Robust Drone Swarm Coordination in GNSS-Degraded Environments
- Raft consensus overview and visualization:
  [raft.github.io](https://raft.github.io/)
- Olfati-Saber, Fax, Murray, *Consensus and Cooperation in Networked Multi-Agent Systems*:
  [murray.cds.caltech.edu/index.php/Consensus_and_Cooperation_in_Networked_Multi-Agent_Systems](https://murray.cds.caltech.edu/index.php/Consensus_and_Cooperation_in_Networked_Multi-Agent_Systems)
- Wang, Li, Zou, *Connectivity-maintaining Consensus of Multi-agent Systems With Communication Management Based on Predictive Control Strategy*:
  [ieee-jas.net/en/article/doi/10.1109/JAS.2023.123081](https://www.ieee-jas.net/en/article/doi/10.1109/JAS.2023.123081)

### Path Planning and Current Research

- NASA NTRS, *Multi-Agent Motion Planning using Deep Learning for Space Applications*:
  [ntrs.nasa.gov/citations/20220005816](https://ntrs.nasa.gov/citations/20220005816)
- NASA NTRS, *UAV Path Planning for Wildfires*:
  [ntrs.nasa.gov/citations/20220015156](https://ntrs.nasa.gov/citations/20220015156)
- Kondo et al., *PRIMER: Perception-Aware Robust Learning-based Multiagent Trajectory Planner*:
  [arxiv.org/abs/2406.10060](https://arxiv.org/abs/2406.10060)

### Python and Visualization

- Mesa documentation:
  [mesa.readthedocs.io](https://mesa.readthedocs.io/)
  Good benchmark framework if you want to compare this custom engine against a standard ABM toolkit.
- Mesa visualization tutorial:
  [mesa.readthedocs.io/en/stable/tutorials/visualization_tutorial.html](https://mesa.readthedocs.io/en/stable/tutorials/visualization_tutorial.html)
  Worth reading before deciding whether to replace or augment the custom frontend.
- FastAPI WebSockets:
  [fastapi.tiangolo.com/advanced/websockets/](https://fastapi.tiangolo.com/advanced/websockets/)
  Directly relevant to the live visualizer loop.
- Three.js:
  [threejs.org](https://threejs.org/)
  The right next move if you want to push this from a research prototype toward a polished demo.
- Next.js static export:
  [nextjs.org/docs/app/building-your-application/deploying/static-exports](https://nextjs.org/docs/app/building-your-application/deploying/static-exports)
  Useful if you later want to turn the frontend into a pure static export.
- Vercel framework deployment docs:
  [vercel.com/docs/frameworks/full-stack/nextjs](https://vercel.com/docs/frameworks/full-stack/nextjs)
  Useful once you are ready to point Vercel at the `web/` directory.

### Observability

- Prometheus Python client:
  [prometheus.github.io/client_python/](https://prometheus.github.io/client_python/)
- Prometheus ASGI integration:
  [prometheus.github.io/client_python/exporting/http/asgi/](https://prometheus.github.io/client_python/exporting/http/asgi/)


