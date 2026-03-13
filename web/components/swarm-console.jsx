"use client";

import { startTransition, useEffect, useState } from "react";
import SwarmScene from "./swarm-scene";


function fmt(v) {
  if (v == null) return "—";
  return Number.isInteger(v) ? String(v) : Number(v).toFixed(2);
}

function findScenario(manifest, name) {
  return manifest?.scenarios.find((s) => s.name === name) ?? null;
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

  /* ── load manifest ── */
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch("/data/latest/manifest.json");
        if (!res.ok) throw new Error(`manifest ${res.status}`);
        const data = await res.json();
        if (cancelled) return;
        setManifest({
          ...data,
          // Only expose the single live scenario — strip static playback scenarios
          scenarios: [
            { name: "Raft Consensus", description: "Real-time stream from the Python simulator running a Raft-inspired quorum consensus protocol for decentralised waypoint assignment." },
          ],
        });
        setStatus("Raft Consensus");
        startTransition(() => setSelectedScenarioName("Raft Consensus"));
      } catch (e) {
        if (!cancelled) setLoadError(e.message);
      }
    }
    load();
    return () => { cancelled = true; };
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

    if (selectedScenario.name === "Raft Consensus") {
      setIsLive(true);
      setPlayback({ frames: [], config: { width: 1280, height: 720 } });
      setLiveFrame(null);
      setFrameIndex(0);

      socket = new WebSocket("ws://127.0.0.1:8000/ws");

      socket.onopen  = () => { if (!cancelled) setStatus("Live · Connected"); };
      socket.onclose = () => { if (!cancelled) setStatus("Live · Disconnected"); };
      socket.onerror = () => { if (!cancelled) setStatus("Live · Error"); };

      socket.onmessage = (ev) => {
        if (cancelled) return;
        const data = JSON.parse(ev.data);
        setLiveFrame(data);
        // keep playback.config in sync for SwarmScene
        setPlayback((prev) => ({ ...prev, config: data.config ?? prev.config }));
      };

      return () => { cancelled = true; socket.close(); };
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

  return (
    <>
      {/* ── Top Navigation Bar ── */}
      <nav className="topbar">
        <div className="topbar-brand">
          <span className="brand-dot" />
          <span className="brand-title">Consensus-Driven Drone Simulation</span>
          <span className="brand-sub">Distributed Swarm Coordination</span>
        </div>
        <span className="status-pill">{status}</span>
      </nav>

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
                  onClick={() => fetch("http://127.0.0.1:8000/api/reset", { method: "POST" }).catch(console.error)}
                >
                  Reset Sim
                </button>
                <button
                  className="button danger-btn"
                  onClick={() => fetch("http://127.0.0.1:8000/api/fail-random", { method: "POST" }).catch(console.error)}
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
                    ? "Waiting for live stream — make sure swarm-sim is running on :8000"
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
                <span className="stat-label">Tick</span>
                <span className="stat-value accent">{currentFrame?.tick ?? "—"}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Elapsed</span>
                <span className="stat-value">{currentFrame ? fmt(currentFrame.elapsed_seconds) + " s" : "—"}</span>
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
            </div>

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
