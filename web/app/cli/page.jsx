import SiteHeader from "../../components/site-header";

const INSTALL_COMMAND = "curl -fsSL https://swarmsim.app/install.sh | bash";

const COMMAND_ROWS = [
  {
    command: "PYTHONPATH=src python3 -m swarm_sim.cli --steps 240 --agents 24 --waypoints 24",
    description: "Run a standard headless simulation and print the final text metrics.",
  },
  {
    command:
      "PYTHONPATH=src python3 -m swarm_sim.cli --live --steps 240 --agents 24 --render-every 4 --factor 2",
    description: "Render the ASCII 2D simulation in the terminal at 2x playback speed.",
  },
  {
    command: "PYTHONPATH=src python3 -m swarm_sim.cli --steps 240 --agents 24 --json",
    description: "Emit machine-readable JSON for scripts, automation, or experiment capture.",
  },
  {
    command:
      "PYTHONPATH=src python3 -m swarm_sim.cli --steps 360 --agents 32 --assignment-strategy raft --failure-tick 180 --json",
    description: "Run a Raft scenario with a deterministic failure event in the middle of the mission.",
  },
  {
    command:
      "PYTHONPATH=src python3 -m swarm_sim.cli --steps 300 --agents 24 --assignment-strategy swarmraft --json",
    description: "Run the SwarmRaft localization-and-recovery mode with Raft-backed assignment commits.",
  },
];

const FLAG_ROWS = [
  {
    flag: "--steps",
    description: "Number of simulator ticks to execute.",
    example: "--steps 240",
  },
  {
    flag: "--agents",
    description: "Number of drones in the swarm.",
    example: "--agents 24",
  },
  {
    flag: "--waypoints",
    description: "Number of waypoints in the mission. Defaults to the agent count if omitted.",
    example: "--waypoints 24",
  },
  {
    flag: "--assignment-strategy",
    description: "Coordination mode: `raft`, `swarmraft`, `consensus`, or `greedy`.",
    example: "--assignment-strategy raft",
  },
  {
    flag: "--live",
    description: "Render the ASCII 2D simulation directly in the terminal.",
    example: "--live",
  },
  {
    flag: "--render-every",
    description: "Draw every N ticks in live mode.",
    example: "--render-every 4",
  },
  {
    flag: "--factor",
    description: "Playback speed for live terminal rendering.",
    example: "--factor 2",
  },
  {
    flag: "--failure-tick",
    description: "Tick at which to inject a random failure. Use `-1` to disable it.",
    example: "--failure-tick 180",
  },
  {
    flag: "--json",
    description: "Return the final metrics payload as JSON instead of formatted text.",
    example: "--json",
  },
  {
    flag: "--backend",
    description: "Physics backend. Use `numpy` for the CPU-first path; `taichi` is experimental.",
    example: "--backend numpy",
  },
];

const NOTES = [
  "One step is one simulation tick. Simulated time is `steps * tick_seconds`, and the default tick size is `0.08` seconds.",
  "If you install the package, the same tool is available as `swarm-cli`.",
  "The CLI returns mission metrics such as active agents, failures, collisions, waypoint completions, cohesion, assignment success, and Raft leader state.",
];

export default function CliPage() {
  return (
    <>
      <SiteHeader status="CLI Reference" />
      <main className="docs-shell">
        <section className="docs-hero docs-hero-single">
          <div>
            <div className="docs-kicker">CLI Reference</div>
            <h1 className="docs-title">Terminal commands for the 2D swarm runner</h1>
            <p className="docs-copy">
              This page is structured as a compact command reference. The CLI is the
              fastest way to run the simulator on a workstation, a Hetzner box, or over
              SSH without depending on the browser interface.
            </p>
          </div>
        </section>

        <section className="docs-card docs-card-wide">
          <div className="sidebar-section-title">Quick Start</div>
          <div className="command-list">
            <article className="command-card">
              <h2 className="docs-section-title">Install</h2>
              <pre className="docs-code">
                <code>{INSTALL_COMMAND}</code>
              </pre>
            </article>
            <article className="command-card">
              <h2 className="docs-section-title">Show the startup banner and usage</h2>
              <pre className="docs-code">
                <code>swarm-cli</code>
              </pre>
            </article>
            <article className="command-card">
              <h2 className="docs-section-title">Show full help</h2>
              <pre className="docs-code">
                <code>swarm-cli --help</code>
              </pre>
            </article>
          </div>
        </section>

        <section className="docs-card docs-card-wide">
          <div className="sidebar-section-title">Common Commands</div>
          <div className="docs-table">
            <div className="docs-table-head">
              <div>Command</div>
              <div>Description</div>
            </div>
            {COMMAND_ROWS.map((row) => (
              <div className="docs-table-row" key={row.command}>
                <div>
                  <pre className="docs-code docs-code-compact">
                    <code>{row.command}</code>
                  </pre>
                </div>
                <div className="docs-table-copy">{row.description}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="docs-card docs-card-wide">
          <div className="sidebar-section-title">Important Flags</div>
          <div className="docs-table">
            <div className="docs-table-head docs-table-head-flags">
              <div>Flag</div>
              <div>Description</div>
              <div>Example</div>
            </div>
            {FLAG_ROWS.map((row) => (
              <div className="docs-table-row docs-table-row-flags" key={row.flag}>
                <div className="docs-flag">{row.flag}</div>
                <div className="docs-table-copy">{row.description}</div>
                <div className="docs-example">{row.example}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="docs-card">
          <div className="sidebar-section-title">Notes</div>
          <div className="queue-list">
            {NOTES.map((note) => (
              <article className="queue-item" key={note}>
                <p className="docs-copy">{note}</p>
              </article>
            ))}
          </div>
        </section>
      </main>
    </>
  );
}
