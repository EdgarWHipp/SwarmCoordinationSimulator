"use client";

import { Canvas } from "@react-three/fiber";
import { Line, OrbitControls, Stars } from "@react-three/drei";


function worldPosition(width, height, x, y, elevation) {
  return [x - width / 2, elevation, y - height / 2];
}


function SwarmObjects({ playback, frame }) {
  const width = playback.config.width;
  const height = playback.config.height;

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.6, 0]}>
        <planeGeometry args={[width, height, 1, 1]} />
        <meshStandardMaterial color="#0b1825" metalness={0.2} roughness={0.9} />
      </mesh>

      <gridHelper
        args={[Math.max(width, height), 24, "#2e6f73", "#183747"]}
        position={[0, -1.55, 0]}
      />

      {frame.waypoints.map((waypoint, index) => {
        const position = worldPosition(
          width,
          height,
          waypoint.position.x,
          waypoint.position.y,
          4 + Math.sin((frame.tick + index) * 0.08) * 0.6,
        );

        return (
          <group key={waypoint.waypoint_id} position={position}>
            <mesh rotation={[Math.PI / 2, 0, 0]}>
              <torusGeometry args={[9, 1.4, 12, 32]} />
              <meshStandardMaterial
                color={waypoint.claimed_by ? "#f0b05a" : "#72e0d1"}
                emissive={waypoint.claimed_by ? "#8f5d14" : "#1c5b5f"}
                emissiveIntensity={0.7}
              />
            </mesh>
            <mesh position={[0, -3.2, 0]}>
              <cylinderGeometry args={[2, 2, 6, 12]} />
              <meshStandardMaterial color="#17384a" />
            </mesh>
          </group>
        );
      })}

      {frame.drones.map((drone, index) => {
        const heading = Math.atan2(drone.velocity.y, drone.velocity.x);
        const position = worldPosition(
          width,
          height,
          drone.position.x,
          drone.position.y,
          drone.failed ? 4 : 16 + Math.sin((frame.tick + index) * 0.14) * 0.9,
        );

        return (
          <group key={drone.drone_id} position={position} rotation={[0, -heading, Math.PI / 2]}>
            <mesh>
              <coneGeometry args={[5.4, 16, 4]} />
              <meshStandardMaterial
                color={drone.failed ? "#ee6d82" : "#72e0d1"}
                emissive={drone.failed ? "#802738" : "#24585d"}
                emissiveIntensity={0.9}
              />
            </mesh>
            <mesh position={[-4, 0, 0]}>
              <boxGeometry args={[3.4, 1.4, 11]} />
              <meshStandardMaterial color={drone.failed ? "#f7b8c2" : "#defcf8"} />
            </mesh>
          </group>
        );
      })}

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
            color="#72e0d1"
            lineWidth={1}
            opacity={0.28}
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
      <color attach="background" args={["#040813"]} />
      <fog attach="fog" args={["#040813", cameraDistance * 0.7, cameraDistance * 1.6]} />
      <ambientLight intensity={0.78} />
      <directionalLight position={[160, 240, 120]} intensity={1.2} color="#f5f4ff" />
      <directionalLight position={[-120, 90, -80]} intensity={0.4} color="#72e0d1" />
      <Stars radius={900} depth={80} count={2000} factor={5} saturation={0} fade speed={0.35} />
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
