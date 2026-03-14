"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { Line, OrbitControls } from "@react-three/drei";
import { useEffect, useRef } from "react";
import * as THREE from "three";

function worldPosition(width, height, x, y, elevation) {
  return [x - width / 2, elevation, y - height / 2];
}

function recoveryColor(mode, suspected) {
  if (mode === "ins_fallback") return "#ffb454";
  if (mode === "median") return "#8ef0a8";
  return suspected ? "#ffe08a" : "#f8fafc";
}

function DroneMesh({ drone, width, height, tick, index, leaderId, residualThreshold, voteThreshold }) {
  const groupRef = useRef();
  const swarmraft = drone.swarmraft;
  const suspected = Boolean(swarmraft?.suspected_faulty);
  const compromised = Boolean(swarmraft?.compromised);
  const isLeader = drone.drone_id === leaderId;
  const residualRatio = swarmraft && residualThreshold > 0
    ? Math.min(swarmraft.residual / residualThreshold, 2.4)
    : 0;
  const voteRatio = swarmraft
    ? Math.min(swarmraft.negative_votes / Math.max(voteThreshold, 1), 2.4)
    : 0;
  const haloRadius = 9.5 + voteRatio * 3.4;
  const haloColor = residualRatio > 1.0 ? "#ff7a59" : residualRatio > 0.6 ? "#ffb454" : "#6c6fff";

  const targetPos = new THREE.Vector3(
    ...worldPosition(
      width,
      height,
      drone.position.x,
      drone.position.y,
      drone.failed ? 4 : 16 + Math.sin((tick + index) * 0.14) * 0.9,
    ),
  );
  const heading = Math.atan2(drone.velocity.y, drone.velocity.x);
  const targetQuat = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, -heading, Math.PI / 2));

  useEffect(() => {
    if (groupRef.current) {
      groupRef.current.position.copy(targetPos);
      groupRef.current.quaternion.copy(targetQuat);
    }
  }, []);

  useFrame((_, delta) => {
    if (groupRef.current) {
      groupRef.current.position.lerp(targetPos, 8 * delta);
      groupRef.current.quaternion.slerp(targetQuat, 8 * delta);
    }
  });

  return (
    <group ref={groupRef}>
      {swarmraft && !drone.failed ? (
        <mesh position={[0, -13.8, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[haloRadius, 0.75, 10, 36]} />
          <meshStandardMaterial
            color={haloColor}
            emissive={haloColor}
            emissiveIntensity={0.22 + residualRatio * 0.18}
            transparent
            opacity={0.18 + Math.min(residualRatio, 1.0) * 0.22}
          />
        </mesh>
      ) : null}

      {isLeader && !drone.failed ? (
        <group>
          <Line
            color="#f8fafc"
            lineWidth={1.4}
            opacity={0.42}
            points={[[0, -10, 0], [0, 26, 0]]}
            transparent
          />
          <mesh position={[0, 28, 0]} rotation={[Math.PI / 2, 0, 0]}>
            <ringGeometry args={[5.4, 7.6, 28]} />
            <meshStandardMaterial
              color="#f8fafc"
              emissive="#6c6fff"
              emissiveIntensity={0.42}
              transparent
              opacity={0.88}
            />
          </mesh>
        </group>
      ) : null}

      <mesh>
        <coneGeometry args={[5.4, 16, 4]} />
        <meshStandardMaterial
          color={
            drone.failed
              ? "#333344"
              : isLeader
                ? "#f8fafc"
                : suspected
                  ? "#ff7a59"
                  : compromised
                    ? "#f87171"
                    : "#6c6fff"
          }
          emissive={
            drone.failed
              ? "#111122"
              : isLeader
                ? "#4c4fd6"
                : suspected
                  ? "#9f2d1a"
                  : compromised
                    ? "#7f1d1d"
                    : "#3c3fcc"
          }
          emissiveIntensity={isLeader ? 0.72 : 0.5}
        />
      </mesh>
      <mesh position={[-4, 0, 0]}>
        <boxGeometry args={[3.4, 1.4, 11]} />
        <meshStandardMaterial
          color={
            drone.failed
              ? "#22223a"
              : isLeader
                ? "#d5d7ff"
                : suspected
                  ? "#ffd0c2"
                  : compromised
                    ? "#fecaca"
                    : "#c4c5ff"
          }
        />
      </mesh>
    </group>
  );
}

function SwarmRaftOverlay({ drone, width, height, residualThreshold }) {
  if (!drone.swarmraft || drone.failed || !drone.swarmraft.local_report_position) return null;

  const swarmraft = drone.swarmraft;
  const truePosition = worldPosition(width, height, drone.position.x, drone.position.y, 0.8);
  const gnss = worldPosition(width, height, swarmraft.gnss_position.x, swarmraft.gnss_position.y, 1.8);
  const ins = worldPosition(width, height, swarmraft.ins_position.x, swarmraft.ins_position.y, 2.4);
  const localReport = worldPosition(
    width,
    height,
    swarmraft.local_report_position.x,
    swarmraft.local_report_position.y,
    3.0,
  );
  const fused = worldPosition(width, height, swarmraft.fused_position.x, swarmraft.fused_position.y, 4.2);
  const recovered = worldPosition(
    width,
    height,
    swarmraft.recovered_position.x,
    swarmraft.recovered_position.y,
    swarmraft.suspected_faulty ? 7.6 : 5.7,
  );
  const spoofed = residualThreshold > 0 && swarmraft.residual > residualThreshold;
  const recoveredColor = recoveryColor(swarmraft.recovery_mode, swarmraft.suspected_faulty);

  return (
    <group>
      <mesh position={truePosition} rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[1.0, 1.8, 16]} />
        <meshStandardMaterial color="#34d399" emissive="#166534" emissiveIntensity={0.35} />
      </mesh>

      <mesh position={gnss} rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[2.2, 3.6, 20]} />
        <meshStandardMaterial
          color={swarmraft.compromised ? "#f87171" : "#7dd3fc"}
          emissive={swarmraft.compromised ? "#7f1d1d" : "#164e63"}
          emissiveIntensity={0.6}
          transparent
          opacity={0.75}
        />
      </mesh>

      <mesh position={ins} rotation={[0, Math.PI / 4, 0]}>
        <tetrahedronGeometry args={[2.6, 0]} />
        <meshStandardMaterial color="#fb7185" emissive="#7f1d1d" emissiveIntensity={0.32} />
      </mesh>

      <mesh position={localReport} rotation={[0, Math.PI / 4, 0]}>
        <boxGeometry args={[2.4, 2.4, 2.4]} />
        <meshStandardMaterial color="#94a3b8" emissive="#334155" emissiveIntensity={0.25} />
      </mesh>

      <mesh position={fused} rotation={[0, Math.PI / 4, 0]}>
        <boxGeometry args={[3.0, 3.0, 3.0]} />
        <meshStandardMaterial color="#f8fafc" emissive="#334155" emissiveIntensity={0.35} />
      </mesh>

      <mesh position={recovered} rotation={[0, Math.PI / 4, 0]}>
        <octahedronGeometry args={[swarmraft.recovered ? 4.8 : 3.8, 0]} />
        <meshStandardMaterial
          color={recoveredColor}
          emissive={swarmraft.recovery_mode === "ins_fallback" ? "#7c2d12" : "#166534"}
          emissiveIntensity={0.45}
        />
      </mesh>

      <Line
        color={spoofed || swarmraft.compromised ? "#f87171" : "#7dd3fc"}
        lineWidth={1.2}
        opacity={0.46}
        points={[truePosition, gnss]}
        transparent
      />
      <Line
        color="#fb7185"
        lineWidth={1.0}
        opacity={0.34}
        points={[truePosition, ins]}
        transparent
      />
      <Line
        color="#94a3b8"
        lineWidth={1.0}
        opacity={0.28}
        points={[localReport, fused]}
        transparent
      />
      <Line
        color={swarmraft.recovery_mode === "ins_fallback" ? "#ffb454" : "#8ef0a8"}
        lineWidth={1.25}
        opacity={0.38}
        points={[fused, recovered]}
        transparent
      />
    </group>
  );
}

function LeaderSpokes({ frame, width, height }) {
  if (frame?.config?.assignment_strategy !== "swarmraft" || !frame?.swarmraft?.enabled) return null;

  const leaderId = frame.swarmraft.leader_id;
  if (!leaderId) return null;
  const leader = frame.drones.find((drone) => drone.drone_id === leaderId && !drone.failed);
  if (!leader) return null;

  const leaderPosition = worldPosition(width, height, leader.position.x, leader.position.y, 20);

  return (
    <group>
      {frame.drones.map((drone) => {
        if (drone.failed || drone.drone_id === leaderId) return null;
        const color = drone.swarmraft?.compromised
          ? "#f87171"
          : drone.swarmraft?.suspected_faulty
            ? "#ffb454"
            : "#6c6fff";
        const peerPosition = worldPosition(width, height, drone.position.x, drone.position.y, 18);
        return (
          <Line
            key={`${leaderId}-${drone.drone_id}-leader-link`}
            color={color}
            lineWidth={1.0}
            opacity={0.14}
            points={[leaderPosition, peerPosition]}
            transparent
          />
        );
      })}
    </group>
  );
}

function WaypointMesh({ waypoint, width, height, tick, index }) {
  const groupRef = useRef();
  const targetPos = new THREE.Vector3(
    ...worldPosition(
      width,
      height,
      waypoint.position.x,
      waypoint.position.y,
      4 + Math.sin((tick + index) * 0.08) * 0.6,
    ),
  );

  useEffect(() => {
    if (groupRef.current) {
      groupRef.current.position.copy(targetPos);
    }
  }, []);

  useFrame((_, delta) => {
    if (groupRef.current) {
      groupRef.current.position.lerp(targetPos, 5 * delta);
    }
  });

  return (
    <group ref={groupRef}>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[9, 1.4, 12, 32]} />
        <meshStandardMaterial
          color={waypoint.claimed_by ? "#34d399" : "#6c6fff"}
          emissive={waypoint.claimed_by ? "#0d4a32" : "#2a2d88"}
          emissiveIntensity={0.6}
        />
      </mesh>
      <mesh position={[0, -3.2, 0]}>
        <cylinderGeometry args={[2, 2, 6, 12]} />
        <meshStandardMaterial color="#0d0d1e" />
      </mesh>
    </group>
  );
}

function SwarmObjects({ playback, frame }) {
  const width = playback.config.width;
  const height = playback.config.height;
  const isSwarmRaft = frame?.config?.assignment_strategy === "swarmraft";
  const leaderId = frame?.swarmraft?.leader_id ?? null;
  const residualThreshold = frame?.swarmraft?.residual_threshold ?? 0;
  const voteThreshold = frame?.swarmraft?.vote_threshold ?? 0;

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.6, 0]}>
        <planeGeometry args={[width, height, 1, 1]} />
        <meshStandardMaterial color="#0d0d18" metalness={0.1} roughness={0.9} />
      </mesh>

      <gridHelper
        args={[Math.max(width, height), 24, "#1a1a2e", "#111122"]}
        position={[0, -1.55, 0]}
      />

      {frame.waypoints.map((waypoint, index) => (
        <WaypointMesh
          key={waypoint.waypoint_id}
          waypoint={waypoint}
          width={width}
          height={height}
          tick={frame.tick}
          index={index}
        />
      ))}

      {isSwarmRaft ? <LeaderSpokes frame={frame} width={width} height={height} /> : null}

      {frame.drones.map((drone, index) => (
        <DroneMesh
          key={drone.drone_id}
          drone={drone}
          width={width}
          height={height}
          tick={frame.tick}
          index={index}
          leaderId={leaderId}
          residualThreshold={residualThreshold}
          voteThreshold={voteThreshold}
        />
      ))}

      {isSwarmRaft
        ? frame.drones.map((drone) => (
            <SwarmRaftOverlay
              key={`${drone.drone_id}-swarmraft`}
              drone={drone}
              width={width}
              height={height}
              residualThreshold={residualThreshold}
            />
          ))
        : null}

      {frame.drones.map((drone) => {
        if (!drone.target_waypoint_id || drone.failed) return null;
        const waypoint = frame.waypoints.find((candidate) => candidate.waypoint_id === drone.target_waypoint_id);
        if (!waypoint) return null;
        const startSource = isSwarmRaft && drone.swarmraft
          ? drone.swarmraft.recovered_position
          : drone.position;
        const start = worldPosition(width, height, startSource.x, startSource.y, 16);
        const end = worldPosition(width, height, waypoint.position.x, waypoint.position.y, 4);
        return (
          <Line
            key={`${drone.drone_id}-${waypoint.waypoint_id}`}
            color="#6c6fff"
            lineWidth={1.5}
            opacity={0.3}
            points={[start, end]}
            transparent
          />
        );
      })}
    </group>
  );
}

export default function SwarmScene({ playback, frame }) {
  const cameraDistance = Math.max(playback.config.width, playback.config.height) * 0.64;

  return (
    <Canvas dpr={[1, 2]}>
      <color attach="background" args={["#080810"]} />
      <fog attach="fog" args={["#080810", cameraDistance * 0.7, cameraDistance * 1.6]} />
      <ambientLight intensity={0.5} />
      <directionalLight position={[160, 240, 120]} intensity={1.8} color="#ffffff" />
      <directionalLight position={[-120, 90, -80]} intensity={0.5} color="#8888ff" />
      <SwarmObjects playback={playback} frame={frame} />
      <OrbitControls
        enablePan={false}
        minDistance={cameraDistance * 0.38}
        maxDistance={cameraDistance * 1.15}
        maxPolarAngle={Math.PI / 2.1}
      />
      <perspectiveCamera
        makeDefault
        fov={42}
        position={[cameraDistance * 0.35, cameraDistance * 0.5, cameraDistance * 0.45]}
      />
    </Canvas>
  );
}
