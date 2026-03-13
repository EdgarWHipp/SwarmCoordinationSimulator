import SiteHeader from "../../components/site-header";

const APPROACHES = [
  {
    title: "Raft Consensus",
    body:
      "Baseline coordination path with persistent leader election and replicated waypoint assignments. This is the current distributed-systems control baseline for the swarm.",
  },
  {
    title: "SwarmRaft Recovery",
    body:
      "Raft coordination plus GNSS/INS fusion, peer residual voting, and robust state recovery. This is the resilience-oriented path for degraded navigation conditions.",
  },
];

const PLACEHOLDER_METRICS = [
  "Mission completion rate",
  "Collision events",
  "Leader failover latency",
  "Waypoint reassignment latency",
  "Localization error under degraded GNSS",
  "Recovery success after compromised state detection",
];

export default function ComparePage() {
  return (
    <>
      <SiteHeader status="Compare" />
      <main className="docs-shell">
        <section className="docs-hero docs-hero-single">
          <div>
            <div className="docs-kicker">Compare</div>
            <h1 className="docs-title">Comparison space for long-run swarm metrics</h1>
            <p className="docs-copy">
              This page is intentionally a placeholder. It exists so you have a dedicated
              location for long-run batch results once the experiment matrix is ready and
              the differences between the approaches are statistically meaningful.
            </p>
          </div>
        </section>

        <section className="docs-grid">
          {APPROACHES.map((approach) => (
            <div className="docs-card" key={approach.title}>
              <div className="sidebar-section-title">{approach.title}</div>
              <p className="docs-copy">{approach.body}</p>
            </div>
          ))}
        </section>

        <section className="docs-card docs-card-wide">
          <div className="sidebar-section-title">Planned Comparison Metrics</div>
          <div className="queue-list">
            {PLACEHOLDER_METRICS.map((metric) => (
              <article className="queue-item" key={metric}>
                <h2 className="docs-section-title">{metric}</h2>
                <p className="docs-copy">
                  Placeholder slot for future batch-run plots, summary tables, and confidence-backed
                  comparisons once you have enough long-run data.
                </p>
              </article>
            ))}
          </div>
        </section>
      </main>
    </>
  );
}
