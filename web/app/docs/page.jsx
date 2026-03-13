import SiteHeader from "../../components/site-header";

const SWARM_USE_CASES = [
  {
    title: "GNSS-denied coordination",
    body:
      "A swarm matters most when the navigation layer degrades. If GNSS is jammed, spoofed, or simply unavailable, the drones need peer coordination, local sensing, and agreement on assignments instead of a single external reference.",
  },
  {
    title: "Disaggregated sensing body",
    body:
      "Instead of one expensive UAV carrying the full mission payload, the swarm acts as a distributed body. Each drone covers a smaller portion of the airspace, and the fleet forms a wider sensing and routing envelope than a single platform can provide.",
  },
  {
    title: "Redundancy and graceful failure",
    body:
      "If one drone drops, the mission should degrade gracefully rather than collapse. The simulator is built around that assumption: failures trigger reassignment, leader failover, and continued waypoint progress instead of a hard stop.",
  },
  {
    title: "Resilient distributed decision-making",
    body:
      "The core value of the setup is not just flight animation. It is the distributed-systems problem underneath: who leads, how the swarm agrees on work, and how it keeps moving when communication or state quality becomes unreliable.",
  },
];

const PAPERS = [
  {
    title: "In Search of an Understandable Consensus Algorithm (Raft Extended Version)",
    href: "https://raft.github.io/raft.pdf",
    status: "Baseline live",
    reason:
      "This is the coordination backbone already reflected in the simulator: leader election, replicated commands, and committed assignment state.",
    plannedUse:
      "Use it later to extend the current in-memory model with more realistic timing, restart, and partition behavior.",
  },
  {
    title: "SwarnRaft: Leveraging Consensus for Robust Drone Swarm Coordination in GNSS-Degraded Environments",
    href: "https://arxiv.org/html/2508.00622v1#S3",
    status: "Planned",
    reason:
      "This is the paper for the next resilience layer. Section 3 is the path from basic coordination to compromise detection and state recovery when navigation data becomes untrustworthy.",
    plannedUse:
      "Implement it later as a 2D fused-estimate and voting pipeline: noisy GNSS, peer range estimates, residual tests, peer votes, and robust recovery.",
  },
  {
    title: "Designing UAV Swarm Experiments: A Simulator Selection and Experiment Design Process",
    href: "https://pmc.ncbi.nlm.nih.gov/articles/PMC10490248/",
    status: "Planned",
    reason:
      "This is the research-structure paper. It is less about control logic and more about how to shape scenarios, baselines, metrics, and comparisons so the simulator can support a defendable evaluation.",
    plannedUse:
      "Use it later to tighten the experiment matrix, scenario families, run counts, and the reporting format for paper-style outputs.",
  },
];

export default function DocsPage() {
  return (
    <>
      <SiteHeader status="Documentation" />
      <main className="docs-shell">
        <section className="docs-hero docs-hero-single">
          <div>
            <div className="docs-kicker">Documentation</div>
            <h1 className="docs-title">Why UAV swarms matter in this simulator</h1>
            <p className="docs-copy">
              This simulator is meant to model the coordination problem that appears when
              a UAV mission must continue under degraded navigation, partial fleet loss,
              and distributed sensing constraints. The point is not just flocking. The
              point is resilient agreement and mission continuity.
            </p>
          </div>
        </section>

        <section className="docs-grid">
          <div className="docs-card">
            <div className="sidebar-section-title">Primary Use Cases</div>
            <div className="queue-list">
              {SWARM_USE_CASES.map((item) => (
                <article className="queue-item" key={item.title}>
                  <h2 className="docs-section-title">{item.title}</h2>
                  <p className="docs-copy">{item.body}</p>
                </article>
              ))}
            </div>
          </div>

          <div className="docs-card">
            <div className="sidebar-section-title">Research Papers</div>
            <div className="paper-list">
              {PAPERS.map((paper) => (
                <article className="paper-card" key={paper.href}>
                  <div className="paper-head">
                    <a className="paper-link" href={paper.href} target="_blank" rel="noreferrer">
                      {paper.title}
                    </a>
                    <span className="paper-badge">{paper.status}</span>
                  </div>
                  <p className="docs-copy">{paper.reason}</p>
                  <div className="paper-planned">
                    <span className="paper-label">Planned use</span>
                    <p>{paper.plannedUse}</p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>
      </main>
    </>
  );
}
