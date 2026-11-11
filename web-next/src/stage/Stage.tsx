// 3D 场景：地台 + 低多边形英雄 + 两个敌人 + 手牌。
//
// 全部用**原始几何体**（plan P1 的明确要求："原始几何体即可"），不引入模型资产 —— 这一阶段的
// 问题是"三维里能不能拖牌"，不是"角色好不好看"。
//
// ## 两条纪律
//
// 1. **网格的位置由这里每帧写，投影也读同一份。** 卡牌位置若由 JSX props 驱动（React state），
//    60Hz 重渲染会把 FPS 数字毁掉，而且"投影用的位置"与"渲染用的位置"会变成两份实现。
//    `useFrame` → 算目标变换 → 写 group → **再用 group 的世界坐标投影**。
//
// 2. **版面是"视图相对"的，不是世界坐标写死的。** 第一版把敌人放在 x=±1.35、牌放在 y=-1.62，
//    横屏好看，390×844 竖屏下敌人被切在两侧、整手牌压在底边外（截图一眼就看出来，而当时的
//    闸门只查"卡牌中心在视口内"——它甚至报了通过，因为牌心确实在视口里，只是牌身被裁掉了）。
//    所以：相机距离按宽高比拉远，所有元素的位置由 `halfH`（可见半高）算出来。

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { MockScene } from "../mock/scene";
import { layout, type CardScreen, type EnemyScreen } from "./layout";
import { computeCombatFormation } from "./formation";
import type { Phase } from "../input/pointerMachine";

const CARD_W = 0.62;
const CARD_H = 0.86;
/** 拖起来的牌所在的 z 平面：跟随指针时按这个平面反投影。 */
const LIFT_Z = 1.45;
/** 必须装得下的横向半宽（世界单位）：两个敌人 + 半径 + 余量。 */
const FIT_HALF_WIDTH = 2.3;

/**
 * 相机距离：**保证横向装得下 `FIT_HALF_WIDTH`**，并夹在 [6, 9.5] 之间。
 * 竖屏（aspect 0.46）会被拉到 9.5：这样敌人不会被切在两侧，牌也还在视口里。
 */
export function cameraDistance(aspect: number, fovDeg = 45): number {
  const tan = Math.tan((fovDeg * Math.PI) / 360);
  const needed = FIT_HALF_WIDTH / (tan * Math.max(aspect, 0.2));
  return Math.min(9.5, Math.max(6, needed));
}

/** 扇形排布：返回第 `index` 张牌（共 `count` 张）的局部变换。`halfH` 是可见半高。 */
export function fanTransform(index: number, count: number, spread: number, halfH: number) {
  const t = count <= 1 ? 0 : (index - (count - 1) / 2) / ((count - 1) / 2);
  return {
    x: t * spread,
    // 弧线：两端略高，中间略低（像手里握着的一把牌）。
    // ⚠️ 0.72 会让中间那张牌的底边压到底部操作栏下面（390×844 实测卡底 804、操作栏 790 起）。
    // 手牌在 z≈0.9，比 z=0 平面更靠近相机 ⇒ 透视下更大更低，所以不能按 z=0 的比例推。
    y: -halfH * 0.66 + Math.abs(t) * halfH * 0.05,
    // ⚠️ z **只随序号单调递增**（越靠右越靠前），**不要**写成 `0.9 + |t| * 0.12`：
    // 那样是对称的，两端在最前、中间 z 最小，窄屏互相压住时中间那张会被完全盖住，
    // 于是"看不见的牌也点不到"（闸门 25 抓到的就是这一条）。
    z: 0.9 + index * 0.008,
    angle: -t * 0.26,
    t,
  };
}

export interface StageProps {
  scene: MockScene;
  /** 抬起的牌（拖拽/选中中）；其余牌回落到手牌位置。 */
  liftedSlot: number;
  hoverSlot: number;
  /** [P1-UX] 视觉上悬停与业务上的目标选择是两种正交状态。 */
  hoverCardSlot: number;
  hoveredEnemySlot: number;
  phase: Phase;
  followPointer: boolean;
  legalTargets: readonly number[];
  onCardDown: (slot: number, pointer: { id: number; type: string; x: number; y: number }) => void;
  onCardHover: (slot: number) => void;
  onHover: (slot: number) => void;
  onRelease: (slot: number) => void;
}
export function Stage({
  scene, liftedSlot, hoverSlot, hoverCardSlot, hoveredEnemySlot, phase, followPointer,
  legalTargets, onCardDown, onCardHover, onHover, onRelease,
}: StageProps) {
  const { camera, size, pointer } = useThree();
  // `?still`：冻结呼吸与插值，让证据截图逐字节可复现（见文件头）。
  const still = typeof window !== "undefined" && window.location.search.includes("still");
  const heroRef = useRef<THREE.Group>(null);
  const groundRef = useRef<THREE.Mesh>(null);
  const enemyRefs = useRef<(THREE.Group | null)[]>([]);
  const cardRefs = useRef<(THREE.Group | null)[]>([]);
  const hitRefs = useRef<(THREE.Mesh | null)[]>([]);

  const scratch = useMemo(
    () => ({
      world: new THREE.Vector3(),
      projected: new THREE.Vector3(),
      corner: new THREE.Vector3(),
      pointerWorld: new THREE.Vector3(),
      cameraDir: new THREE.Vector3(),
      offset: new THREE.Vector3(),
    }),
    []
  );

  // [P1-UX] 瞄准连线只有 2 个顶点；每帧改 BufferAttribute，不创建新 Mesh/React 节点。
  // 线只是演出，不参与射线，不改变 WASM 的目标选择与命中判定。
  const aimLine = useMemo(() => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
    const material = new THREE.LineBasicMaterial({
      color: "#8dffcb", transparent: true, opacity: 0.90,
      depthTest: false, depthWrite: false,
    });
    const beam = new THREE.Line(geometry, material);
    beam.renderOrder = 19;
    beam.frustumCulled = false;
    beam.visible = false;
    beam.raycast = () => {}; // 从不遮挡敌人或手牌射线。
    return beam;
  }, []);
  useEffect(() => () => {
    aimLine.geometry.dispose();
    (aimLine.material as THREE.Material).dispose();
  }, [aimLine]);

  useFrame(({ clock }, delta) => {
    const t = still ? 0 : clock.getElapsedTime();

    // ── 视图：相机距离按宽高比算，然后所有位置由 halfH/halfW 派生 ─────────────
    const aspect = size.height > 0 ? size.width / size.height : 1;
    const distance = cameraDistance(aspect);
    if (Math.abs(camera.position.z - distance) > 0.005) {
      camera.position.set(0, 0.6, distance);
      camera.lookAt(0, 0, 0);
      camera.updateProjectionMatrix();
    }
    const tan = Math.tan((45 * Math.PI) / 360);
    const halfH = tan * distance;
    const halfW = halfH * aspect;

    // [P1-LAYOUT] 队形由纯函数统一计算。以后接真实 WASM 时替换数据源即可；
    // 战场仍然是 "我方在左、敌人在右"，竖屏右侧单列，横屏右侧两行（每行至多三名）。
    const formation = computeCombatFormation(
      scene.enemies.map((enemy) => enemy.slot),
      { width: size.width, height: size.height, halfW, halfH }
    );
    const groundY = -halfH * 0.5;
    if (groundRef.current) groundRef.current.position.y = groundY;
    if (heroRef.current) {
      heroRef.current.position.set(
        formation.hero.x, formation.hero.y + 0.025 * Math.sin(t * 1.6), formation.hero.z
      );
    }
    for (const [index, group] of enemyRefs.current.entries()) {
      const place = formation.enemies[index];
      if (!group || !place) continue;
      group.position.set(place.x, place.y + 0.025 * Math.sin(t * 1.3 + index * 1.7), place.z);
      group.scale.setScalar(place.scale);
    }

    // ── 指针在 LIFT_Z 平面上的世界坐标（拖起的牌跟随它）──────────────────────
    scratch.projected.set(pointer.x, pointer.y, 0.5).unproject(camera);
    scratch.cameraDir.copy(scratch.projected).sub(camera.position).normalize();
    const liftDistance = (LIFT_Z - camera.position.z) / scratch.cameraDir.z;
    scratch.pointerWorld.copy(camera.position).addScaledVector(scratch.cameraDir, liftDistance);

    // ── 卡牌：写网格变换，然后用**网格自己的世界坐标**投影 ───────────────────
    const spread = Math.min(2.6, halfW * 0.76);
    const cards: CardScreen[] = [];
    scene.hand.forEach((_, index) => {
      const group = cardRefs.current[index];
      if (!group) return;
      const local = fanTransform(index, scene.hand.length, spread, halfH);
      const lifted = index === liftedSlot;
      const hovered = index === hoverCardSlot && phase === "idle";
      // [P1-UX] 鼠标悬停轻抬；按下/拖拽显著抬起；点按目标牌后，预览固定在战场偏左下，
      // 不会在松开手指后继续粘着上一指针位置，从而挡住右侧敌人。
      const previewX = formation.portrait ? -halfW * 0.16 : -halfW * 0.22;
      const previewY = -halfH * 0.28;
      const targetX = lifted ? (followPointer ? scratch.pointerWorld.x : previewX) : local.x;
      const targetY = lifted ? (followPointer ? scratch.pointerWorld.y - 0.1 : previewY)
        : local.y + (hovered ? 0.11 : 0);
      const targetZ = lifted ? LIFT_Z : hovered ? 1.32 : local.z;
      const targetAngle = lifted ? 0 : local.angle;
      const targetScale = lifted ? 1.32 : hovered ? 1.11 : 1;
      // [P1-UX] 用 deltaTime 而非每帧固定系数，避免 30 / 60 / 120 Hz 手感不同。
      const k = still ? 1 : 1 - Math.exp(-(lifted ? 22 : hovered ? 16 : 13) * Math.min(delta, 0.1));
      group.position.x += (targetX - group.position.x) * k;
      group.position.y += (targetY - group.position.y) * k;
      group.position.z += (targetZ - group.position.z) * k;
      group.rotation.z += (targetAngle - group.rotation.z) * k;
      const scale = group.scale.x + (targetScale - group.scale.x) * k;
      group.scale.setScalar(scale);

      // 命中面：**静止**（不跟着拖拽动画走），位置就是扇形位。视觉是装饰，命中要有静止目标。
      const hit = hitRefs.current[index];
      if (hit) {
        hit.position.set(local.x, local.y, 1.2 + index * 0.008);
        hit.rotation.z = local.angle;
      }

      // 投影：中心 + 右上角 ⇒ 屏幕矩形（透视下用两次投影求尺寸，别用线性近似）。
      group.getWorldPosition(scratch.world);
      scratch.projected.copy(scratch.world).project(camera);
      const cx = (scratch.projected.x * 0.5 + 0.5) * size.width;
      const cy = (-scratch.projected.y * 0.5 + 0.5) * size.height;
      scratch.offset.set((CARD_W * scale) / 2, (CARD_H * scale) / 2, 0);
      scratch.corner.copy(scratch.world).add(scratch.offset).project(camera);
      const rx = (scratch.corner.x * 0.5 + 0.5) * size.width;
      const ry = (-scratch.corner.y * 0.5 + 0.5) * size.height;
      cards.push({
        slot: index,
        x: cx,
        y: cy,
        w: Math.abs(rx - cx) * 2,
        h: Math.abs(ry - cy) * 2,
        visibleW: Math.abs(rx - cx) * 2,
        hitX: cx,
        hitY: cy,
        lifted,
      });
    });
    // 露出来的宽度 = min(牌宽, 与右邻中心的间距)；最右那张没有右邻 ⇒ 整张都露着。
    // 命中点往**左**挪半个被压住的量：露出的是左边那条。
    for (let index = 0; index < cards.length; index += 1) {
      const card = cards[index];
      const neighbour = cards[index + 1];
      const stride = neighbour ? Math.abs(neighbour.x - card.x) : card.w;
      // 抬起的牌在最前面，整张都露着 ⇒ 文字用整张牌宽（否则规则会被压成很窄的一列）。
      card.visibleW = (card.lifted || card.slot === hoverCardSlot) ? card.w : Math.min(card.w, Math.max(stride, 1));
      card.hitX = card.x - (card.w - card.visibleW) / 2;
      card.hitY = card.y;
    }
    layout.cards = cards;

    // ── 敌人：投影中心 + 半径 ────────────────────────────────────────────────
    const enemies: EnemyScreen[] = [];
    scene.enemies.forEach((enemy, index) => {
      const group = enemyRefs.current[index];
      if (!group) return;
      group.getWorldPosition(scratch.world);
      scratch.projected.copy(scratch.world).project(camera);
      const cx = (scratch.projected.x * 0.5 + 0.5) * size.width;
      const cy = (-scratch.projected.y * 0.5 + 0.5) * size.height;
      scratch.offset.set(0.44 * (formation.enemies[index]?.scale ?? 1), 0, 0);
      scratch.corner.copy(scratch.world).add(scratch.offset).project(camera);
      const rx = (scratch.corner.x * 0.5 + 0.5) * size.width;
      enemies.push({ slot: enemy.slot, x: cx, y: cy, r: Math.abs(rx - cx) });
    });
    layout.enemies = enemies;
    layout.width = size.width;
    layout.height = size.height;
    // [P1-UX] 只在 "目标合法且真的被指向" 时画瞄准线，避免误导玩家。
    const aimTarget = formation.enemies.find((p) => p.slot === hoverSlot);
    const aimCard = liftedSlot >= 0 ? cardRefs.current[liftedSlot] : null;
    const aimActive = phase === "targeting" && legalTargets.includes(hoverSlot) && !!aimTarget && !!aimCard;
    aimLine.visible = aimActive;
    if (aimActive && aimTarget && aimCard) {
      const pos = aimLine.geometry.getAttribute("position") as THREE.BufferAttribute;
      pos.setXYZ(0, aimCard.position.x, aimCard.position.y, 1.7);
      pos.setXYZ(1, aimTarget.x, aimTarget.y, 0.52);
      pos.needsUpdate = true;
    }
    layout.frames += 1;
  });

  return (
    <>
      <color attach="background" args={["#0b0f14"]} />
      {/* [P1-UX] 瞄准连线共享整个场景的坐标系，目标被遮挡也不会错误发动作。 */}
      <primitive object={aimLine} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[3, 6, 4]} intensity={1.15} />
      <directionalLight position={[-4, 3, -2]} intensity={0.35} color="#7fb0ff" />

      {/* 地台（位置每帧写） */}
      <mesh ref={groundRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.5, -0.6]}>
        <circleGeometry args={[6, 48]} />
        <meshStandardMaterial color="#16202b" roughness={0.95} metalness={0.05} />
      </mesh>

      {/* 英雄：低多边形（胶囊身体 + 二十面体头 + 方块肩） */}
      <group ref={heroRef}>
        <mesh position={[0, -0.35, 0]}>
          <capsuleGeometry args={[0.34, 0.72, 4, 10]} />
          <meshStandardMaterial color="#c8543c" roughness={0.6} flatShading />
        </mesh>
        <mesh position={[0, 0.46, 0]}>
          <icosahedronGeometry args={[0.27, 0]} />
          <meshStandardMaterial color="#e8c9a0" roughness={0.7} flatShading />
        </mesh>
        <mesh position={[-0.36, 0.06, 0]} rotation={[0, 0, 0.3]}>
          <boxGeometry args={[0.2, 0.44, 0.24]} />
          <meshStandardMaterial color="#8c3a2a" roughness={0.7} flatShading />
        </mesh>
        <mesh position={[0.36, 0.06, 0]} rotation={[0, 0, -0.3]}>
          <boxGeometry args={[0.2, 0.44, 0.24]} />
          <meshStandardMaterial color="#8c3a2a" roughness={0.7} flatShading />
        </mesh>
      </group>

      {/* 敌人：两个不同形状，证明"不同敌人"在 3D 里是可见的 */}
      {scene.enemies.map((enemy, index) => {
        const dead = enemy.hp <= 0;
        // [P1-UX] "可选目标"与"已命中目标"分别提示；死亡/非法目标不显示绿色。
        const eligible = phase === "targeting" && legalTargets.includes(enemy.slot) && !dead;
        const targeted = eligible && hoverSlot === enemy.slot;
        const hovered = hoveredEnemySlot === enemy.slot;
        const illegalHover = phase === "targeting" && hovered && !eligible && !dead;
        return (
          <group
            key={`${enemy.id}-${enemy.slot}`}
            ref={(node) => {
              enemyRefs.current[index] = node;
            }}
            onPointerMove={(event) => {
              event.stopPropagation();
              onHover(enemy.slot);
            }}
            onPointerOut={() => onHover(-1)}
            onPointerUp={(event) => {
              event.stopPropagation();
              onRelease(enemy.slot);
            }}
          >
            {index % 2 === 0 ? (
              <mesh>
                <sphereGeometry args={[0.44, 12, 9]} />
                <meshStandardMaterial
                  color={dead ? "#2b3239" : targeted ? "#7ddc8a" : hovered ? "#78c786" : "#4c9a5a"}
                  roughness={0.45}
                  flatShading
                  emissive={targeted ? "#1f5c2c" : "#000000"}
                />
              </mesh>
            ) : (
              <mesh rotation={[0, 0.4, 0]}>
                <dodecahedronGeometry args={[0.46, 0]} />
                <meshStandardMaterial
                  color={dead ? "#2b3239" : targeted ? "#e0b46a" : hovered ? "#c89b63" : "#9c6b3c"}
                  roughness={0.6}
                  flatShading
                  emissive={targeted ? "#5a3c10" : "#000000"}
                />
              </mesh>
            )}
            {/* [P1-UX] 用面向相机的轮廓环替代水平地面环：竖屏/固定镜头也明显可见。
                青色=可选，绿色=当前有效目标；这只是 UI 提示，动作合法性仍由 options 决定。 */}
            {(eligible || illegalHover) && (
              <mesh position={[0, 0, 0.40]} raycast={() => null}>
                <ringGeometry args={[0.49, 0.55, 36]} />
                <meshBasicMaterial
                  color={illegalHover ? "#ff917b" : targeted ? "#86ffba" : "#7cc9ff"}
                  transparent opacity={illegalHover || targeted ? 0.96 : 0.55}
                  side={THREE.DoubleSide} depthTest={false} depthWrite={false}
                />
              </mesh>
            )}
          </group>
        );
      })}

      {/* 空白处兜底：指针不在敌人身上时命中它 ⇒ hoverSlot = -1 */}
      <mesh
        position={[0, 0, -3]}
        onPointerMove={(event) => {
          event.stopPropagation();
          onHover(-1);
        }}
        onPointerUp={(event) => {
          event.stopPropagation();
          onRelease(-1);
        }}
      >
        <planeGeometry args={[60, 60]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* 手牌：牌身 + 边框。**文字不在这里**（见 `TextOverlay`）。 */}
      {scene.hand.map((card, index) => (
        <group
          key={`${card.id}-${index}`}
          ref={(node) => {
            cardRefs.current[index] = node;
          }}
          position={[0, -8, 0]}
        >
          {/* ⚠️ 视觉网格**完全不参与射线**。第一版让牌身自己接收 `onPointerDown`，结果是：
              被拖起的牌挡住敌人（目标永远命不中），而且**回弹动画途中**的牌会挡住下一次点击
              —— 闸门读到的是"按第 3 张却打出了第 2 张"。视觉是装饰，命中要有静止的目标。 */}
          {/* 手牌是 **UI**：depthTest=false + renderOrder 让牌永远画在世界之上。
              否则地台（水平面，一直延伸到相机前）会挡住牌的下半截 —— 截图里"牌只剩一条"。 */}
          <mesh raycast={() => null} renderOrder={10}>
            <boxGeometry args={[CARD_W, CARD_H, 0.03]} />
            {/* ⚠️ 卡面必须**亮过背景**：第一版用了 #3a2226 这类深色，在 #0b0f14 的背景上
                整手牌只剩几根边框线（截图里几乎看不见牌）。深色主题里"牌"要靠明度差立起来。 */}
            <meshStandardMaterial
              color={card.kind === "attack" ? "#8c4a52" : card.kind === "skill" ? "#4a6f93" : "#6b5b96"}
              emissive={card.kind === "attack" ? "#2a1216" : card.kind === "skill" ? "#12202e" : "#1d1830"}
              roughness={0.62}
              metalness={0.12}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
          <CardEdge />
        </group>
      ))}

      {/* 命中面：每个槽位一块**静止**的不可见平面（位置每帧由 `useFrame` 写）。
          槽位越靠右 z 越大 ⇒ 叠放顺序与视觉一致（右边的牌压在上面）。 */}
      {scene.hand.map((card, index) => (
        <mesh
          key={`hit-${card.id}-${index}`}
          ref={(node) => {
            hitRefs.current[index] = node;
          }}
          onPointerOver={(event) => {
            if (event.pointerType === "mouse" || event.pointerType === "pen") onCardHover(index);
          }}
          onPointerOut={() => onCardHover(-1)}
          onPointerDown={(event) => {
            if (event.button !== 0) return; // 右键用于查看详情，不应进入出牌状态。
            event.stopPropagation();
            // [P1-UX] 保留 pointerId + CSS 像素原点供全局监听器计算真实拖动距离。
            onCardDown(index, {
              id: event.pointerId, type: event.pointerType,
              x: event.clientX, y: event.clientY,
            });
          }}
        >
          <planeGeometry args={[CARD_W, CARD_H]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>
      ))}
    </>
  );
}

/** 牌框：单独一个组件，这样 `BoxGeometry` 只创建一次（内联在 map 里会每帧 new）。 */
function CardEdge() {
  const geometry = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(CARD_W, CARD_H, 0.03)), []);
  return (
    <lineSegments geometry={geometry} raycast={() => null} renderOrder={11}>
      <lineBasicMaterial color="#c8dcf0" depthTest={false} depthWrite={false} />
    </lineSegments>
  );
}
