// 三维敌人的**渲染**：把 `geometry.ts` 的原型数据画成 three.js 基本体。
//
// 三个设计点：
//
// 1. **渲染层不认具体敌人**：它只吃 `EnemyLook`（原型 + 调色板 + 缩放 + 是否 Boss）。
//    加一个敌人只改清单，加一个原型只改目录 —— 渲染代码不动。
// 2. **几何体共享**：同一种基本体（球/盒/锥/柱/环/八面体/胶囊）在整个场景里**只有一份**
//    geometry，靠 `scale` 变形。理由：61 个敌人 × 5 个基本体 = 300+ 个网格，每个各建一份
//    geometry 会白白吃显存（P6 记过"每张牌一份几何体"的老账）。
// 3. **没有资源加载**：这一版刻意不碰 GLB（`docs/ui-p5-beats.md` §6）。所以"素材缺失"只可能
//    来自"清单里没有这个 id"，而那条路径在注册表里被计数。

import { useMemo } from "react";
import * as THREE from "three";
import type { EnemyLook } from "../assets/registry";
import type { Shape } from "../assets/geometry";

/** 单位几何体（模块级共享；`size` 用 `scale` 表达）。 */
const UNIT: Record<Shape, () => THREE.BufferGeometry> = {
  sphere: () => new THREE.SphereGeometry(0.5, 18, 14),
  box: () => new THREE.BoxGeometry(1, 1, 1),
  cone: () => new THREE.ConeGeometry(0.5, 1, 14),
  cylinder: () => new THREE.CylinderGeometry(0.5, 0.5, 1, 14),
  torus: () => new THREE.TorusGeometry(0.5, 0.12, 8, 24),
  octahedron: () => new THREE.OctahedronGeometry(0.5),
  capsule: () => new THREE.CapsuleGeometry(0.5, 1, 6, 12),
};

const shared = new Map<Shape, THREE.BufferGeometry>();
function geometryFor(shape: Shape): THREE.BufferGeometry {
  let geometry = shared.get(shape);
  if (!geometry) {
    geometry = UNIT[shape]();
    shared.set(shape, geometry);
  }
  return geometry;
}

export interface EnemyFigureProps {
  readonly look: EnemyLook;
  /** 整体位置（世界坐标）。 */
  readonly position?: readonly [number, number, number];
  /** 整体朝向（弧度，绕 Y 轴）。 */
  readonly yaw?: number;
  /** 不参与射线（敌人命中仍由 `hitTest` 的圆形负责，网格不接事件）。 */
  readonly opacity?: number;
}

/**
 * 一个敌人 = 一个 group，里面是原型的基本体。
 *
 * ⚠️ 网格**不挂任何事件**（`raycast` 被清空）：命中判定统一走 `input/hitTest` 的屏幕圆形，
 * 两套几何（射线 vs 圆形）并存会让边缘出现"绿环亮着但点不中"（P1 的老账）。
 */
export function EnemyFigure({ look, position = [0, 0, 0], yaw = 0, opacity = 1 }: EnemyFigureProps) {
  const parts = look.figure.parts;
  const scale = look.scale * (look.boss ? 1.08 : 1);
  // 材质按角色建一次（同一敌人内三种颜色）。
  const materials = useMemo(() => {
    const make = (color: string) =>
      new THREE.MeshStandardMaterial({
        color,
        roughness: 0.72,
        metalness: 0.06,
        transparent: opacity < 1,
        opacity,
      });
    return {
      body: make(look.palette.body),
      accent: make(look.palette.accent),
      eye: new THREE.MeshBasicMaterial({ color: look.palette.eye }),
    };
  }, [look.palette.body, look.palette.accent, look.palette.eye, opacity]);

  return (
    <group position={position as unknown as THREE.Vector3Tuple} rotation={[0, yaw, 0]} scale={scale}>
      {parts.map((part, index) => (
        <mesh
          key={index}
          geometry={geometryFor(part.shape)}
          material={materials[part.role]}
          position={part.position as unknown as THREE.Vector3Tuple}
          rotation={(part.rotation ?? [0, 0, 0]) as unknown as THREE.Vector3Tuple}
          scale={part.size as unknown as THREE.Vector3Tuple}
          raycast={() => {}}
          castShadow={false}
          receiveShadow={false}
        />
      ))}
      {/* Boss 多一圈光环：一眼能看出"这是 Boss"，不靠体型猜。 */}
      {look.boss && (
        <mesh rotation={[1.57, 0, 0]} position={[0, -0.42, 0]} raycast={() => {}}>
          <torusGeometry args={[0.62, 0.03, 8, 32]} />
          <meshBasicMaterial color={look.palette.accent} transparent opacity={0.55} />
        </mesh>
      )}
    </group>
  );
}
