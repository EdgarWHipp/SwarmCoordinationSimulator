"use client";

import { startTransition, useEffect, useState } from "react";
import SiteHeader from "./site-header";
import SwarmScene from "./swarm-scene";

const SWARM_API_BASE_URL = (process.env.NEXT_PUBLIC_SWARM_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const LIVE_BASE_DRONE_COUNT = 8;
const LIVE_BASE_WAYPOINT_COUNT = 8;
const SWARMRAFT_ATTACK_SCALE = 2;
const LIVE_MODE_LABELS = {
  raft: "Consensus Coordination",
  swarmraft: "Resilient Localization",
  consensus: "Heuristic Consensus",
  greedy: "Greedy Assignment",
};
const SWARMRAFT_PROTOCOL_STEPS = ["Sense", "Inform", "Estimate", "Evaluate", "Recover", "Finalize"];
const SWARMRAFT_LIVE_CONFIG = {
  assignment_strategy: "swarmraft",
  speed_multiplier: 1,
  drone_count: LIVE_BASE_DRONE_COUNT,
  waypoint_count: LIVE_BASE_WAYPOINT_COUNT,
  swarmraft_attacked_drones: 1 * SWARMRAFT_ATTACK_SCALE,
  swarmraft_fault_budget: 1 * SWARMRAFT_ATTACK_SCALE,
  swarmraft_enable_gnss_attack: true,
  swarmraft_enable_range_attack: true,
  swarmraft_enable_collusion: true,
  swarmraft_gnss_attack_bias_std: 42 * SWARMRAFT_ATTACK_SCALE,
  swarmraft_range_attack_bias_std: 18 * SWARMRAFT_ATTACK_SCALE,
};
const LIVE_SCENARIOS = [
  {
    name: "Raft Consensus",
    description:
      "Real-time stream from the Python simulator running persistent Raft leader election and replicated waypoint assignment.",
    liveConfig: {
      assignment_strategy: "raft",
      speed_multiplier: 1,
      drone_count: LIVE_BASE_DRONE_COUNT,
      waypoint_count: LIVE_BASE_WAYPOINT_COUNT,
    },
  },
  {
    name: "SwarmRaft",
    description:
      "Raft coordination with doubled GNSS spoofing, range tampering, collusion, and robust recovery visible in 3D.",
    liveConfig: SWARMRAFT_LIVE_CONFIG,
  },
];


function fmt(v) {
  if (v == null) return "—";
  return Number.isInteger(v) ? String(v) : Number(v).toFixed(2);
}

function findScenario(manifest, name) {
  return manifest?.scenarios.find((s) => s.name === name) ?? null;
}

function apiUrl(path) {
  return new URL(path, `${SWARM_API_BASE_URL}/`).toString();
}

function websocketUrl() {
  const url = new URL(SWARM_API_BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws";
  url.search = "";
  return url.toString();
}

function mergePlaybackConfig(previous, nextConfig) {
  const fallback = { frames: [], config: { width: 1280, height: 720 } };
  const base = previous ?? fallback;
  return { ...base, config: nextConfig ?? base.config };
}

function formatModeLabel(strategy) {
  return LIVE_MODE_LABELS[strategy] ?? strategy ?? "—";
}

function protocolStepState(step, phase, leaderRoundApplied) {
  if (leaderRoundApplied) {
    return step === phase ? "current" : "complete";
  }
  if (phase === "Fallback") {
    if (step === "Sense" || step === "Inform") return "complete";
    return "muted";
  }
  if (phase === "Sense") {
    return step === "Sense" ? "current" : "muted";
  }
  return "muted";
}


export default function SwarmConsole() {
  const [manifest, setManifest] = useState(null);
  const [selectedScenarioName, setSelectedScenarioName] = useState("");
  const [selectedScenario, setSelectedScenario] = useState(null);
  const [playback, setPlayback] = useState(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [status, setStatus] = useState("Connecting…");
  const [loadError, setLoadError] = useState(null);
  const [isLive, setIsLive] = useState(false);
  const [liveFrame, setLiveFrame] = useState(null);
  const [liveRunning, setLiveRunning] = useState(true);
  const [liveControlBusy, setLiveControlBusy] = useState(false);

  /* ── load live scenarios ── */
  useEffect(() => {
    setManifest({ scenarios: LIVE_SCENARIOS });
    setStatus(LIVE_SCENARIOS[0].name);
    startTransition(() => setSelectedScenarioName(LIVE_SCENARIOS[0].name));
  }, []);

  /* ── scenario selection ── */
  useEffect(() => {
    setSelectedScenario(findScenario(manifest, selectedScenarioName));
  }, [manifest, selectedScenarioName]);

  /* ── live WS or static playback ── */
  useEffect(() => {
    let cancelled = false;
    let socket = null;
    if (!selectedScenario) return;

    if (selectedScenario.liveConfig) {
      setIsLive(true);
      setPlayback({ frames: [], config: { width: 1280, height: 720 } });
      setLiveFrame(null);
      setFrameIndex(0);
      setLiveRunning(true);
      setLoadError(null);
      setStatus(`Live · Configuring ${selectedScenario.name}`);

      async function configureAndConnect() {
        try {
          const configResponse = await fetch(apiUrl("/api/config"), {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(selectedScenario.liveConfig),
          });
          if (!configResponse.ok) {
            throw new Error(`config ${configResponse.status}`);
          }

          const resetResponse = await fetch(apiUrl("/api/reset"), { method: "POST" });
          if (!resetResponse.ok) {
            throw new Error(`reset ${resetResponse.status}`);
          }
          const resetPayload = await resetResponse.json();
          if (cancelled) return;

          setLiveFrame(resetPayload);
          setPlayback((prev) => mergePlaybackConfig(prev, resetPayload.config));
          setStatus(`Live · ${selectedScenario.name}`);

          socket = new WebSocket(websocketUrl());

          socket.onopen = () => {
            if (cancelled) return;
            setStatus((current) => (current === "Live · Paused" ? current : `Live · ${selectedScenario.name}`));
          };
          socket.onclose = () => {
            if (!cancelled) setStatus("Live · Disconnected");
          };
          socket.onerror = () => {
            if (!cancelled) setStatus("Live · Error");
          };

          socket.onmessage = (ev) => {
            if (cancelled) return;
            const data = JSON.parse(ev.data);
            setLiveFrame(data);
            setLiveRunning((current) => (current === false ? false : true));
            setStatus((current) => (current === "Live · Paused" ? current : `Live · ${selectedScenario.name}`));
            setPlayback((prev) => mergePlaybackConfig(prev, data.config));
          };
        } catch (e) {
          if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e));
        }
      }

      configureAndConnect();
      return () => {
        cancelled = true;
        if (socket) socket.close();
      };
    }

    setIsLive(false);

    async function loadPlayback() {
      try {
        setStatus(`Loading ${selectedScenario.name}…`);
        const res = await fetch(`/data/latest/${selectedScenario.playback_path}`);
        if (!res.ok) throw new Error(`playback ${res.status}`);
        const data = await res.json();
        if (cancelled) return;
        setPlayback(data);
        setFrameIndex(0);
        setIsPlaying(true);
        setStatus(selectedScenario.name);
      } catch (e) {
        if (!cancelled) setLoadError(e.message);
      }
    }
    loadPlayback();
    return () => { cancelled = true; };
  }, [selectedScenario]);

  /* ── playback timer ── */
  useEffect(() => {
    if (!playback || !isPlaying || isLive) return;
    const id = setInterval(() => {
      setFrameIndex((i) => (i >= playback.frames.length - 1 ? i : i + 1));
    }, 110);
    return () => clearInterval(id);
  }, [playback, isPlaying, isLive]);

  useEffect(() => {
    if (playback && frameIndex >= playback.frames.length - 1) setIsPlaying(false);
  }, [frameIndex, playback]);

  const currentFrame  = isLive ? liveFrame : (playback?.frames[frameIndex] ?? null);
  const summary       = currentFrame?.summary ?? null;
  const currentEvents = currentFrame?.events ?? [];
  const liveSpeedMultiplier = currentFrame?.config?.speed_multiplier ?? 1;
  const liveDroneCount = currentFrame?.config?.drone_count ?? selectedScenario?.liveConfig?.drone_count ?? LIVE_BASE_DRONE_COUNT;
  const liveWaypointCount = currentFrame?.config?.waypoint_count ?? selectedScenario?.liveConfig?.waypoint_count ?? LIVE_BASE_WAYPOINT_COUNT;
  const swarmraftFrame = currentFrame?.swarmraft ?? null;
  const swarmraftPhase = swarmraftFrame?.protocol_phase ?? summary?.swarmraft_protocol_phase ?? "—";
  const swarmraftSteps = swarmraftFrame?.protocol_steps ?? SWARMRAFT_PROTOCOL_STEPS;
  const swarmraftLeaderId = swarmraftFrame?.leader_id ?? summary?.raft_leader_id ?? "—";
  const swarmraftFaultBudget = currentFrame?.config?.swarmraft_fault_budget ?? "—";
  const swarmraftThresholdK = currentFrame?.config?.swarmraft_threshold_k ?? "—";
  const displayedModeLabel = isLive
    ? (selectedScenario?.name ?? formatModeLabel(currentFrame?.config?.assignment_strategy))
    : formatModeLabel(currentFrame?.config?.assignment_strategy);

  async function sendLiveControl(command, requestBody = null) {
    setLiveControlBusy(true);
    try {
      const response = await fetch(apiUrl(`/api/${command}`), {
        method: "POST",
        headers: requestBody ? { "content-type": "application/json" } : undefined,
        body: requestBody ? JSON.stringify(requestBody) : undefined,
      });
      if (!response.ok) {
        throw new Error(`${command} ${response.status}`);
      }
      const responsePayload = await response.json();
      if (typeof responsePayload.running === "boolean") {
        setLiveRunning(responsePayload.running);
        setStatus(responsePayload.running ? `Live · ${selectedScenario?.name ?? "Connected"}` : "Live · Paused");
      } else if (command === "reset") {
        if (responsePayload.tick != null) {
          setLiveFrame(responsePayload);
          setPlayback((prev) => mergePlaybackConfig(prev, responsePayload.config));
        }
        setStatus(`Live · ${selectedScenario?.name ?? "Reset"}`);
      } else if (command === "fail-random") {
        setStatus("Live · Failure Injected");
      }
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error));
    } finally {
      setLiveControlBusy(false);
    }
  }

  async function setLiveSpeedMultiplier(multiplier) {
    setLiveControlBusy(true);
    try {
      const response = await fetch(apiUrl("/api/config"), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ speed_multiplier: multiplier }),
      });
      if (!response.ok) {
        throw new Error(`config ${response.status}`);
      }
      setStatus(`Live · ${multiplier.toFixed(0)}x speed`);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error));
    } finally {
      setLiveControlBusy(false);
    }
  }

  async function adjustLivePopulation(delta) {
    const nextDroneCount = Math.max(1, Number(liveDroneCount) + delta);
    setLiveControlBusy(true);
    try {
      const response = await fetch(apiUrl("/api/config"), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          drone_count: nextDroneCount,
        }),
      });
      if (!response.ok) {
        throw new Error(`config ${response.status}`);
      }
      setStatus(`Live · ${nextDroneCount} drones`);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error));
    } finally {
      setLiveControlBusy(false);
    }
  }

  return (
    <>
      {/* ── Top Navigation Bar ── */}
      <SiteHeader status={status} />

      <div className="page-shell">
        {/* ── Toolbar ── */}
        <div className="toolbar-strip">
          <div className="toolbar-left">
            <label htmlFor="scenario-select" style={{ fontSize: 11, color: "var(--muted)" }}>
              Scenario
            </label>
            <select
              id="scenario-select"
              className="select"
              value={selectedScenarioName}
              onChange={(e) => startTransition(() => setSelectedScenarioName(e.target.value))}
              disabled={!manifest}
            >
              {manifest?.scenarios.map((s) => (
                <option key={s.name} value={s.name}>{s.name}</option>
              ))}
            </select>

            {selectedScenario?.description && (
              <span style={{ fontSize: 11, color: "var(--muted)", maxWidth: 360 }}>
                {selectedScenario.description}
              </span>
            )}
            {loadError && (
              <span style={{ fontSize: 11, color: "var(--danger)" }}>{loadError}</span>
            )}
          </div>

          <div className="toolbar-right">
            {isLive ? (
              <>
                <button
                  className="button"
                  onClick={() => sendLiveControl(liveRunning ? "pause" : "resume")}
                  disabled={liveControlBusy}
                >
                  {liveRunning ? "Pause Sim" : "Resume Sim"}
                </button>
                <button
                  className="button"
                  onClick={() => sendLiveControl("reset")}
                  disabled={liveControlBusy}
                >
                  Reset Sim
                </button>
                <button
                  className="button"
                  onClick={() => adjustLivePopulation(4)}
                  disabled={liveControlBusy}
                >
                  Spawn +4
                </button>
                <button
                  className="button"
                  onClick={() => setLiveSpeedMultiplier(liveSpeedMultiplier >= 4 ? 1 : 4)}
                  disabled={liveControlBusy}
                >
                  {liveSpeedMultiplier >= 4 ? "Back To 1x" : "Enable 4x"}
                </button>
                <button
                  className="button danger-btn"
                  onClick={() => sendLiveControl("fail-random")}
                  disabled={liveControlBusy}
                >
                  Fail Drone
                </button>
              </>
            ) : (
              <>
                <button className="button" onClick={() => { setFrameIndex(0); setIsPlaying(false); }}>Reset</button>
                <button className="button" onClick={() => setFrameIndex((i) => Math.max(i - 1, 0))}>← Step</button>
                <button
                  className="button primary"
                  onClick={() => {
                    if (playback && frameIndex >= playback.frames.length - 1) setFrameIndex(0);
                    setIsPlaying((v) => !v);
                  }}
                >
                  {isPlaying ? "Pause" : "Play"}
                </button>
              </>
            )}
          </div>
        </div>

        {/* ── Main Content ── */}
        <div className="content-grid">

          {/* Left: scene + timeline */}
          <div className="scene-area">
            <div className="canvas-frame">
              {currentFrame && playback ? (
                <SwarmScene playback={playback} frame={currentFrame} />
              ) : (
                <div className="empty-state">
                  {isLive
                    ? `Waiting for live stream — make sure the swarm API is running at ${SWARM_API_BASE_URL}`
                    : "Select a scenario to start playback"}
                </div>
              )}
            </div>

            {/* Timeline (hidden in live mode) */}
            {!isLive && (
              <div className="timeline-panel">
                <span className="timeline-label">Timeline</span>
                <input
                  className="timeline-range"
                  type="range"
                  min={0}
                  max={Math.max((playback?.frames.length ?? 1) - 1, 0)}
                  value={frameIndex}
                  onChange={(e) => { setFrameIndex(Number(e.target.value)); setIsPlaying(false); }}
                  disabled={!playback}
                />
                <span className="timeline-tick">
                  {frameIndex + 1} / {playback?.frames.length ?? 0} · {fmt(currentFrame?.elapsed_seconds)}s
                </span>
              </div>
            )}
          </div>

          {/* Right: metrics sidebar */}
          <aside className="metrics-sidebar">

            {/* Live frame stats */}
            <div className="sidebar-section">
              <div className="sidebar-section-title">Live Metrics</div>
              <div className="stat-row">
                <span className="stat-label">Profile</span>
                <span className="stat-value accent">{displayedModeLabel}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Tick</span>
                <span className="stat-value accent">{currentFrame?.tick ?? "—"}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Configured Drones</span>
                <span className="stat-value">{liveDroneCount}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Configured Waypoints</span>
                <span className="stat-value">{liveWaypointCount}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Elapsed</span>
                <span className="stat-value">{currentFrame ? fmt(currentFrame.elapsed_seconds) + " s" : "—"}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Speed</span>
                <span className="stat-value">{fmt(liveSpeedMultiplier)}x</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Active Agents</span>
                <span className="stat-value positive">{summary ? summary.active_agents : "—"}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Failed Agents</span>
                <span className={`stat-value ${summary?.failed_agents > 0 ? "danger" : ""}`}>
                  {summary ? summary.failed_agents : "—"}
                </span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Completions</span>
                <span className="stat-value positive">{summary ? summary.waypoint_completions : "—"}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Collisions</span>
                <span className={`stat-value ${summary?.collision_events_total > 0 ? "warning" : ""}`}>
                  {summary ? summary.collision_events_total : "—"}
                </span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Cohesion</span>
                <span className="stat-value">{summary ? fmt(summary.cohesion_score) : "—"}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Avg Speed</span>
                <span className="stat-value">{summary ? fmt(summary.average_speed) : "—"}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Consensus</span>
                <span className="stat-value accent">
                  {summary ? (summary.consensus_success_ratio * 100).toFixed(0) + "%" : "—"}
                </span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Assignment Δ</span>
                <span className="stat-value">{summary ? summary.assignment_changes : "—"}</span>
              </div>
              {summary?.swarmraft_enabled ? (
                <>
                  <div className="stat-row">
                    <span className="stat-label">Attacked</span>
                    <span className={`stat-value ${summary.swarmraft_attacked_agents > 0 ? "danger" : ""}`}>
                      {summary.swarmraft_attacked_agents}
                    </span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">Suspected</span>
                    <span className={`stat-value ${summary.swarmraft_suspected_agents > 0 ? "warning" : ""}`}>
                      {summary.swarmraft_suspected_agents}
                    </span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">Recovered</span>
                    <span className="stat-value positive">{summary.swarmraft_recovered_agents}</span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">True Positives</span>
                    <span className="stat-value positive">{summary.swarmraft_true_positive_detections}</span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">False Positives</span>
                    <span className={`stat-value ${summary.swarmraft_false_positive_detections > 0 ? "warning" : ""}`}>
                      {summary.swarmraft_false_positive_detections}
                    </span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">False Negatives</span>
                    <span className={`stat-value ${summary.swarmraft_false_negative_detections > 0 ? "danger" : ""}`}>
                      {summary.swarmraft_false_negative_detections}
                    </span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">GNSS Error</span>
                    <span className="stat-value">{fmt(summary.swarmraft_mean_gnss_error)}</span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">Recovered Error</span>
                    <span className="stat-value">{fmt(summary.swarmraft_mean_consensus_error)}</span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">Median GNSS Error</span>
                    <span className="stat-value">{fmt(summary.swarmraft_median_gnss_error)}</span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">Median Recovered Error</span>
                    <span className="stat-value">{fmt(summary.swarmraft_median_consensus_error)}</span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">Residual</span>
                    <span className="stat-value">{fmt(summary.swarmraft_mean_residual)}</span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">Threshold</span>
                    <span className="stat-value">{fmt(summary.swarmraft_residual_threshold)}</span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label">Vote Budget</span>
                    <span className="stat-value">{summary.swarmraft_vote_threshold}</span>
                  </div>
                </>
              ) : null}
            </div>

            {summary?.swarmraft_enabled ? (
              <div className="sidebar-section">
                <div className="sidebar-section-title">SwarmRaft Protocol</div>
                <div className="stat-row">
                  <span className="stat-label">Leader</span>
                  <span className="stat-value accent">{swarmraftLeaderId}</span>
                </div>
                <div className="stat-row">
                  <span className="stat-label">Phase</span>
                  <span className="stat-value">{swarmraftPhase}</span>
                </div>
                <div className="stat-row">
                  <span className="stat-label">Leader Round</span>
                  <span className={`stat-value ${summary.swarmraft_leader_round_applied ? "positive" : "warning"}`}>
                    {summary.swarmraft_leader_round_applied ? "Applied" : "Fallback"}
                  </span>
                </div>
                <div className="stat-row">
                  <span className="stat-label">Fault Budget f</span>
                  <span className="stat-value">{swarmraftFaultBudget}</span>
                </div>
                <div className="stat-row">
                  <span className="stat-label">Threshold k</span>
                  <span className="stat-value">{fmt(swarmraftThresholdK)}</span>
                </div>

                <div className="protocol-strip">
                  {swarmraftSteps.map((step) => (
                    <span
                      key={step}
                      className={`protocol-pill protocol-pill-${protocolStepState(
                        step,
                        swarmraftPhase,
                        summary.swarmraft_leader_round_applied,
                      )}`}
                    >
                      {step}
                    </span>
                  ))}
                </div>

                {!summary.swarmraft_leader_round_applied ? (
                  <div className="protocol-note">
                    No leader quorum for this round. The scene is showing local GNSS + INS reports without median recovery.
                  </div>
                ) : null}

                <div className="legend-list">
                  <div className="legend-item">
                    <span className="legend-chip legend-chip-true" />
                    <span className="legend-copy">Drone body / green ring: true position</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-chip legend-chip-gnss" />
                    <span className="legend-copy">Blue ring: GNSS reading</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-chip legend-chip-ins" />
                    <span className="legend-copy">Rose tetra: INS dead reckoning</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-chip legend-chip-local" />
                    <span className="legend-copy">Gray cube: local GNSS + INS report</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-chip legend-chip-fused" />
                    <span className="legend-copy">White cube: leader fused estimate</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-chip legend-chip-recovered" />
                    <span className="legend-copy">Green or amber octa: recovered position</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-chip legend-chip-leader" />
                    <span className="legend-copy">White beacon: elected Raft leader collecting reports</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-chip legend-chip-halo" />
                    <span className="legend-copy">Ground halo: residual and vote pressure</span>
                  </div>
                </div>
              </div>
            ) : null}

            {/* Events log */}
            <div className="sidebar-section" style={{ flex: 1 }}>
              <div className="sidebar-section-title">Events</div>
              <div className="event-list">
                {currentEvents.length ? (
                  currentEvents.map((ev, i) => (
                    <div className="event-item" key={`${ev}-${i}`}>
                      <div>{ev}</div>
                      <div className="event-tick">tick {currentFrame?.tick}</div>
                    </div>
                  ))
                ) : (
                  <div className="event-item" style={{ color: "var(--muted)" }}>
                    No events this frame.
                  </div>
                )}
              </div>
            </div>

          </aside>
        </div>
      </div>
    </>
  );
}
