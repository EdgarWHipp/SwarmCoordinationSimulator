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
          color={drone.failed ? "#000000" : "#ff4d00"}
          emissive={drone.failed ? "#000000" : "#ff4d00"}
          emissiveIntensity={0.2}
        />
      </mesh>
      <mesh position={[-4, 0, 0]}>
        <boxGeometry args={[3.4, 1.4, 11]} />
        <meshStandardMaterial color={drone.failed ? "#666666" : "#ffffff"} />
      </mesh>
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
          color={waypoint.claimed_by ? "#000000" : "#ff4d00"}
          emissive={waypoint.claimed_by ? "#000000" : "#ff4d00"}
          emissiveIntensity={0.2}
        />
      </mesh>
      <mesh position={[0, -3.2, 0]}>
        <cylinderGeometry args={[2, 2, 6, 12]} />
        <meshStandardMaterial color="#000000" />
      </mesh>
    </group>
  );
}

function SwarmObjects({ playback, frame }) {
  const width = playback.config.width;
  const height = playback.config.height;

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.6, 0]}>
        <planeGeometry args={[width, height, 1, 1]} />
        <meshStandardMaterial color="#f4f0ea" metalness={0.0} roughness={1.0} />
      </mesh>

      <gridHelper
        args={[Math.max(width, height), 24, "#000000", "#d3cec4"]}
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

      {frame.drones.map((drone) => {
        if (!drone.target_waypoint_id || drone.failed) {
          return null;
        }

        const waypoint = frame.waypoints.find(
          (candidate) => candidate.waypoint_id === drone.target_waypoint_id,
        );
        if (!waypoint) {
          return null;
        }

        const start = worldPosition(width, height, drone.position.x, drone.position.y, 16);
        const end = worldPosition(width, height, waypoint.position.x, waypoint.position.y, 4);

        return (
          <Line
            key={`${drone.drone_id}-${waypoint.waypoint_id}`}
            color="#ff4d00"
            lineWidth={2}
            opacity={0.4}
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
      <color attach="background" args={["#f4f0ea"]} />
      <ambientLight intensity={1.5} />
      <directionalLight position={[160, 240, 120]} intensity={2.5} color="#ffffff" castShadow />
      <directionalLight position={[-120, 90, -80]} intensity={1.0} color="#ffedd8" />
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
