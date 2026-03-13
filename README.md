# Swarm Coordination Simulator
--> Phadke A, Medrano FA, Sekharan CN, Chu T. Designing UAV Swarm Experiments: A Simulator Selection and Experiment Design Process. Sensors (Basel). 2023 Aug 23;23(17):7359. doi: 10.3390/s23177359. PMID: 37687817; PMCID: PMC10490248.


A lightweight autonomous swarm coordination simulator built in Python with:

- decentralized waypoint negotiation
- boids-style local motion control
- failure injection and rebalancing
- WebSocket-driven browser visualization
- Prometheus metrics for swarm health observability
- an optimized simulation core built around SoA `float32` arrays, `cKDTree`, NumPy, and Numba

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

## Performance Architecture

The simulator now follows the optimization order that matters for swarm workloads:

- agent state is stored as Structure of Arrays in `float32`
- neighbor and collision discovery use `scipy.spatial.cKDTree`
- waypoint routing uses a startup-time navigation graph with precomputed A* next hops and path costs
- planning and steering are vectorized with NumPy
- hot inner loops use Numba
- only routing state that changed is recomputed
- live rendering is decoupled from the fixed-timestep simulation loop through a separate worker process
- runtime transport between the worker and API process uses `msgpack`, while the browser still receives JSON

The default backend is the optimized CPU path. Taichi is available as an experimental opt-in backend for larger swarm counts and future GPU scaling.

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

### Terminal CLI

For a CPU-first server workflow over SSH, use the terminal runner:

```bash
PYTHONPATH=src python3 -m swarm_sim.cli --steps 240 --agents 24 --waypoints 24
```

Render the 2D simulation as ASCII in the terminal:

```bash
PYTHONPATH=src python3 -m swarm_sim.cli --live --steps 240 --agents 24 --render-every 4
```

Show the same live run at 2x simulated speed:

```bash
PYTHONPATH=src python3 -m swarm_sim.cli --live --steps 240 --agents 24 --render-every 4 --factor 2
```

Print machine-readable metrics for automation or shell scripts:

```bash
PYTHONPATH=src python3 -m swarm_sim.cli --steps 240 --agents 24 --json
```

If you install the package, the same tool is available as:

```bash
swarm-cli --steps 240 --agents 24 --json
```

Profile the hot path with:

```bash
PYTHONPATH=src python3 -m swarm_sim.profile --agents 256 --steps 240 --warmup 8 --top 20
```

Write a profiler artifact for Snakeviz with:

```bash
PYTHONPATH=src python3 -m swarm_sim.profile --output /tmp/swarm.prof
snakeviz /tmp/swarm.prof
```

Try the experimental Taichi backend with:

```bash
PYTHONPATH=src python3 -m swarm_sim.profile --backend taichi --agents 512 --steps 120
```

If you have a GPU-enabled Taichi environment, set `SWARM_TAICHI_ARCH=gpu` before running.

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

This is the part that makes the project stand out in an enterprise or defense-adjacent systems interview: you are not just simulating behavior, you are instrumenting fleet health like an observable distributed platform.

## Step-By-Step Build Path

### Step 1: Working vertical slice

Status: implemented

- custom Python simulation core
- FastAPI server
- canvas-based browser visualizer
- Prometheus instrumentation

### Step 2: Scenario realism

Recommended next:

- add static obstacles and no-fly zones
- vary radio range and packet loss
- add leader dropout and delayed state propagation

### Step 3: Experiment harness

Status: implemented

- seeded scenario sweeps
- `manifest.json`, `summary.csv`, and `run_summaries.json`
- representative playback traces for the frontend
- metrics ready for paper-style comparison tables

### Step 4: Paper-ready evaluation

- compare no-consensus vs consensus routing
- compare failure-free vs dropout scenarios
- report mean and variance across multiple seeds

### Step 5: Visual polish

Status: implemented as a first pass

- Next.js frontend in `web/`
- 3D playback with Three.js via React Three Fiber
- static artifact loading for Vercel-friendly hosting

## Experiment Artifacts

The batch runner writes:

- `artifacts/experiments/latest/manifest.json`
- `artifacts/experiments/latest/summary.csv`
- `artifacts/experiments/latest/run_summaries.json`
- `artifacts/experiments/latest/playbacks/*.json`

The same artifact set can be mirrored into `web/public/data/latest/` for frontend playback.

Each scenario contains:

- aggregate metrics across multiple seeds
- per-seed run summaries
- one representative trace for 3D playback

This structure keeps the research workflow and the deploy workflow aligned: the paper figures and the demo UI read from the same exported data.

## Vercel Deploy

The recommended deployment model is:

1. generate experiment artifacts with Python
2. publish them into `web/public/data/latest`
3. deploy `web/` as the Vercel project root

For Vercel:

- set the project root to `web`
- use `npm run build`
- the app serves static experiment JSON from `web/public/data/latest`

This is simpler and more reliable than trying to host a long-running Python simulation loop on Vercel.

## Why This Stack

I chose a custom simulator first instead of Mesa for the initial implementation because this repo needs explicit control over timing, communication range, consensus epochs, and Prometheus integration. Mesa is still a strong learning resource and a good future baseline, but it is not required for the first credible prototype.

## Learning Resources

These are the highest-signal references I’d use for the next pass of this project. Links were checked on March 11, 2026.

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


