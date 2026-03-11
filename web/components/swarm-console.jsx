"use client";

import { startTransition, useEffect, useState } from "react";
import SwarmScene from "./swarm-scene";


const aggregateMetricLabels = {
  final_waypoint_completions: "Completions",
  final_collision_events_total: "Collision Events",
  final_completion_rate_per_min: "Completions / Min",
  mean_cohesion_score: "Mean Cohesion",
  mean_consensus_success_ratio: "Consensus Success",
  mean_active_collision_pairs: "Active Collision Pairs",
  time_to_first_completion_seconds: "First Completion (s)",
  dropout_recovery_ticks: "Recovery Ticks",
};


function formatMetricValue(value) {
  if (value === null) {
    return "n/a";
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}


function findScenario(manifest, name) {
  return manifest?.scenarios.find((scenario) => scenario.name === name) ?? null;
}


export default function SwarmConsole() {
  const [manifest, setManifest] = useState(null);
  const [selectedScenarioName, setSelectedScenarioName] = useState("");
  const [selectedScenario, setSelectedScenario] = useState(null);
  const [playback, setPlayback] = useState(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [status, setStatus] = useState("Loading manifest");
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function loadManifest() {
      try {
        const response = await fetch("/data/latest/manifest.json");
        if (!response.ok) {
          throw new Error(`manifest request failed with ${response.status}`);
        }
        const nextManifest = await response.json();
        if (cancelled) {
          return;
        }
        setManifest(nextManifest);
        setStatus(`Manifest generated ${new Date(nextManifest.generated_at_utc).toLocaleString()}`);
        startTransition(() => {
          setSelectedScenarioName(
            nextManifest.default_scenario ?? nextManifest.scenarios[0]?.name ?? "",
          );
        });
      } catch (error) {
        if (cancelled) {
          return;
        }
        setLoadError(error instanceof Error ? error.message : "unknown manifest error");
      }
    }

    loadManifest();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const nextScenario = findScenario(manifest, selectedScenarioName);
    setSelectedScenario(nextScenario);
  }, [manifest, selectedScenarioName]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedScenario) {
      return;
    }

    async function loadPlayback() {
      try {
        setStatus(`Loading ${selectedScenario.name}`);
        const response = await fetch(`/data/latest/${selectedScenario.playback_path}`);
        if (!response.ok) {
          throw new Error(`playback request failed with ${response.status}`);
        }
        const nextPlayback = await response.json();
        if (cancelled) {
          return;
        }
        setPlayback(nextPlayback);
        setFrameIndex(0);
        setIsPlaying(true);
        setStatus(
          `${selectedScenario.name} | representative seed ${selectedScenario.representative_seed}`,
        );
      } catch (error) {
        if (cancelled) {
          return;
        }
        setLoadError(error instanceof Error ? error.message : "unknown playback error");
      }
    }

    loadPlayback();
    return () => {
      cancelled = true;
    };
  }, [selectedScenario]);

  useEffect(() => {
    if (!playback || !isPlaying) {
      return;
    }
    const timer = window.setInterval(() => {
      setFrameIndex((current) => {
        if (current >= playback.frames.length - 1) {
          return current;
        }
        return current + 1;
      });
    }, 110);

    return () => {
      window.clearInterval(timer);
    };
  }, [playback, isPlaying]);

  useEffect(() => {
    if (!playback) {
      return;
    }
    if (frameIndex >= playback.frames.length - 1) {
      setIsPlaying(false);
    }
  }, [frameIndex, playback]);

  const currentFrame = playback?.frames[frameIndex] ?? null;
  const currentEvents = currentFrame?.events ?? [];

  return (
    <main className="page-shell">
      <section className="hero-panel">
        <p className="eyebrow">Swarm Experiment Console</p>
        <h1>Research playback for a distributed drone swarm</h1>
        <p className="lede">
          This viewer is built for Vercel deployment. The Python experiment runner exports static
          traces, and this Next.js console turns them into a 3D review surface for scenarios,
          failures, and coordination quality.
        </p>
      </section>

      <div className="layout-grid">
        <section className="scene-panel">
          <div className="scene-shell">
            <div className="scene-toolbar">
              <div className="button-stack">
                <div className="selector-row">
                  <label htmlFor="scenario-select" className="muted">
                    Scenario
                  </label>
                  <select
                    id="scenario-select"
                    className="select"
                    value={selectedScenarioName}
                    onChange={(event) => {
                      const nextName = event.target.value;
                      startTransition(() => {
                        setSelectedScenarioName(nextName);
                      });
                    }}
                    disabled={!manifest}
                  >
                    {manifest?.scenarios.map((scenario) => (
                      <option key={scenario.name} value={scenario.name}>
                        {scenario.name}
                      </option>
                    ))}
                  </select>
                </div>
                <span className="status-pill">{status}</span>
              </div>

              <div className="button-row">
                <button
                  className="button ghost"
                  onClick={() => {
                    setFrameIndex(0);
                    setIsPlaying(false);
                  }}
                  type="button"
                >
                  Reset
                </button>
                <button
                  className="button secondary"
                  onClick={() => {
                    setFrameIndex((current) => Math.max(current - 1, 0));
                    setIsPlaying(false);
                  }}
                  type="button"
                >
                  Step Back
                </button>
                <button
                  className="button"
                  onClick={() => {
                    if (playback && frameIndex >= playback.frames.length - 1) {
                      setFrameIndex(0);
                    }
                    setIsPlaying((current) => !current);
                  }}
                  type="button"
                >
                  {isPlaying ? "Pause" : "Play"}
                </button>
              </div>
            </div>

            <div className="canvas-frame">
              {currentFrame && playback ? (
                <SwarmScene playback={playback} frame={currentFrame} />
              ) : (
                <div className="empty-state">
                  <div>
                    <h2>Waiting for playback data</h2>
                    <p className="muted">
                      Run the Python experiment generator and publish artifacts into
                      `web/public/data/latest`.
                    </p>
                  </div>
                </div>
              )}
            </div>

            <div className="timeline-panel">
              <div className="timeline-row">
                <div className="timeline-values">
                  <strong>Timeline</strong>
                  <span className="timeline-caption">
                    Frame {frameIndex + 1} / {playback?.frames.length ?? 0}
                  </span>
                </div>
                <input
                  className="timeline-range"
                  type="range"
                  min={0}
                  max={Math.max((playback?.frames.length ?? 1) - 1, 0)}
                  value={frameIndex}
                  onChange={(event) => {
                    setFrameIndex(Number(event.target.value));
                    setIsPlaying(false);
                  }}
                  disabled={!playback}
                />
                <div className="timeline-values">
                  <span>Tick {currentFrame?.tick ?? 0}</span>
                  <span>{currentFrame ? currentFrame.elapsed_seconds.toFixed(2) : "0.00"} s</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <aside className="sidebar">
          <section className="stack-card">
            <h3>Scenario Brief</h3>
            <h2 style={{ marginTop: 10 }}>{selectedScenario?.name ?? "No scenario selected"}</h2>
            <p className="scenario-description" style={{ marginTop: 10 }}>
              {selectedScenario?.description ??
                "The manifest has not loaded yet, so no scenario description is available."}
            </p>
            {loadError ? (
              <p className="danger" style={{ marginTop: 12 }}>
                {loadError}
              </p>
            ) : null}
          </section>

          <section className="stack-card">
            <h3>Aggregate Metrics</h3>
            <div className="metric-grid">
              {selectedScenario
                ? Object.entries(selectedScenario.aggregate_metrics).map(([key, metric]) => (
                    <article className="metric-card" key={key}>
                      <div className="metric-label">
                        {aggregateMetricLabels[key] ?? key}
                      </div>
                      <div className="metric-value">{formatMetricValue(metric.mean)}</div>
                      <div className="metric-subtitle">
                        stdev {formatMetricValue(metric.stdev)}
                      </div>
                    </article>
                  ))
                : null}
            </div>
          </section>

          <section className="stack-card">
            <h3>Representative Frame</h3>
            {currentFrame ? (
              <div className="metric-grid">
                <article className="metric-card">
                  <div className="metric-label">Active Agents</div>
                  <div className="metric-value">{currentFrame.summary.active_agents}</div>
                </article>
                <article className="metric-card">
                  <div className="metric-label">Waypoint Completions</div>
                  <div className="metric-value">{currentFrame.summary.waypoint_completions}</div>
                </article>
                <article className="metric-card">
                  <div className="metric-label">Collision Events</div>
                  <div className="metric-value">
                    {currentFrame.summary.collision_events_total}
                  </div>
                </article>
                <article className="metric-card">
                  <div className="metric-label">Consensus Success</div>
                  <div className="metric-value">
                    {currentFrame.summary.consensus_success_ratio.toFixed(2)}
                  </div>
                </article>
              </div>
            ) : null}
          </section>

          <section className="stack-card">
            <h3>Run Summaries</h3>
            <div className="run-grid">
              {selectedScenario?.runs.map((run) => (
                <article className="run-card" key={`${run.scenario_name}-${run.seed}`}>
                  <strong>Seed {run.seed}</strong>
                  completions {run.final_waypoint_completions} | collisions{" "}
                  {run.final_collision_events_total} | cohesion {run.mean_cohesion_score.toFixed(2)}
                </article>
              ))}
            </div>
          </section>

          <section className="stack-card">
            <h3>Recent Events</h3>
            <div className="log-list">
              {currentEvents.length ? (
                currentEvents.map((event, index) => (
                  <article className="log-entry" key={`${event}-${index}`}>
                    <div>{event}</div>
                    <div className="log-meta" style={{ marginTop: 6 }}>
                      tick {currentFrame?.tick}
                    </div>
                  </article>
                ))
              ) : (
                <article className="log-entry">
                  <div>No recent events recorded for this frame.</div>
                </article>
              )}
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}
