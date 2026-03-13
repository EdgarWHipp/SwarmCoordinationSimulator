"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { Line, OrbitControls } from "@react-three/drei";
import { useRef, useEffect } from "react";
import * as THREE from "three";

function worldPosition(width, height, x, y, elevation) {
  return [x - width / 2, elevation, y - height / 2];
}

function DroneMesh({ drone, width, height, tick, index }) {
  const groupRef = useRef();
  const swarmraft = drone.swarmraft;
  const suspected = Boolean(swarmraft?.suspected_faulty);
  
  const targetPos = new THREE.Vector3(...worldPosition(
    width, height, drone.position.x, drone.position.y,
    drone.failed ? 4 : 16 + Math.sin((tick + index) * 0.14) * 0.9
  ));
  const heading = Math.atan2(drone.velocity.y, drone.velocity.x);
  const targetQuat = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, -heading, Math.PI / 2));

  useEffect(() => {
    if (groupRef.current) {
      groupRef.current.position.copy(targetPos);
      groupRef.current.quaternion.copy(targetQuat);
    }
  }, []); // Only snap on initial mount

  useFrame((state, delta) => {
    if (groupRef.current) {
      groupRef.current.position.lerp(targetPos, 8 * delta);
      groupRef.current.quaternion.slerp(targetQuat, 8 * delta);
    }
  });

  return (
    <group ref={groupRef}>
      <mesh>
        <coneGeometry args={[5.4, 16, 4]} />
        <meshStandardMaterial
          color={drone.failed ? "#333344" : suspected ? "#ff7a59" : "#6c6fff"}
          emissive={drone.failed ? "#111122" : suspected ? "#9f2d1a" : "#3c3fcc"}
          emissiveIntensity={0.5}
        />
      </mesh>
      <mesh position={[-4, 0, 0]}>
        <boxGeometry args={[3.4, 1.4, 11]} />
        <meshStandardMaterial color={drone.failed ? "#22223a" : suspected ? "#ffd0c2" : "#c4c5ff"} />
      </mesh>
    </group>
  );
}

function SwarmRaftOverlay({ drone, width, height }) {
  if (!drone.swarmraft || drone.failed) return null;

  const gnss = worldPosition(
    width,
    height,
    drone.swarmraft.gnss_position.x,
    drone.swarmraft.gnss_position.y,
    1.8
  );
  const recovered = worldPosition(
    width,
    height,
    drone.swarmraft.recovered_position.x,
    drone.swarmraft.recovered_position.y,
    drone.swarmraft.suspected_faulty ? 7.5 : 5.4
  );
  const fused = worldPosition(
    width,
    height,
    drone.swarmraft.fused_position.x,
    drone.swarmraft.fused_position.y,
    3.6
  );

  return (
    <group>
      <mesh position={gnss} rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[2.2, 3.6, 20]} />
        <meshStandardMaterial
          color="#7dd3fc"
          emissive="#164e63"
          emissiveIntensity={0.6}
          transparent
          opacity={0.75}
        />
      </mesh>
      <mesh position={fused} rotation={[0, Math.PI / 4, 0]}>
        <boxGeometry args={[3, 3, 3]} />
        <meshStandardMaterial color="#f8fafc" emissive="#334155" emissiveIntensity={0.35} />
      </mesh>
      <mesh position={recovered} rotation={[0, Math.PI / 4, 0]}>
        <octahedronGeometry args={[drone.swarmraft.recovered ? 4.8 : 3.8, 0]} />
        <meshStandardMaterial
          color={drone.swarmraft.suspected_faulty ? "#ffb454" : "#8ef0a8"}
          emissive={drone.swarmraft.suspected_faulty ? "#7c2d12" : "#166534"}
          emissiveIntensity={0.45}
        />
      </mesh>
      <Line
        color={drone.swarmraft.suspected_faulty ? "#ff7a59" : "#7dd3fc"}
        lineWidth={1.2}
        opacity={0.42}
        points={[gnss, recovered]}
        transparent
      />
    </group>
  );
}

function WaypointMesh({ waypoint, width, height, tick, index }) {
  const groupRef = useRef();
  const targetPos = new THREE.Vector3(...worldPosition(
    width, height, waypoint.position.x, waypoint.position.y,
    4 + Math.sin((tick + index) * 0.08) * 0.6
  ));

  useEffect(() => {
    if (groupRef.current) {
      groupRef.current.position.copy(targetPos);
    }
  }, []);

  useFrame((state, delta) => {
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

      {frame.drones.map((drone, index) => (
        <DroneMesh
          key={drone.drone_id} 
          drone={drone} 
          width={width} 
          height={height} 
          tick={frame.tick} 
          index={index} 
        />
      ))}

      {isSwarmRaft
        ? frame.drones.map((drone) => (
            <SwarmRaftOverlay
              key={`${drone.drone_id}-swarmraft`}
              drone={drone}
              width={width}
              height={height}
            />
          ))
        : null}

      {frame.drones.map((drone) => {
        if (!drone.target_waypoint_id || drone.failed) return null;
        const waypoint = frame.waypoints.find((c) => c.waypoint_id === drone.target_waypoint_id);
        if (!waypoint) return null;
        const startSource =
          isSwarmRaft && drone.swarmraft
            ? drone.swarmraft.recovered_position
            : drone.position;
        const start = worldPosition(width, height, startSource.x, startSource.y, 16);
        const end   = worldPosition(width, height, waypoint.position.x, waypoint.position.y, 4);
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
