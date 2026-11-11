"""Stage 接入 `combatLayout`（区域模型 + 相机 + 扇形），并做四角投影与共享几何体。

## 三件事

1. **版面的常数搬进纯函数**：`CARD_W/CARD_H/LIFT_Z/FIT_HALF_WIDTH/cameraDistance/fanSpread`
   原本散在 `Stage` 里，现在由 `stage/combatLayout.ts` 一处给出；手牌的**世界 y** 由
   "手牌底边贴着操作栏"反推，不再是一个 `-halfH * 0.66` 的魔法数（§353 那个数是量出来的，
   现在它有了推导）。

2. **四角投影（Review P2-D）**：原来只投中心 + 一个**未旋转**的角来估宽高，牌旋转 ±15° 时
   估算会偏。现在投四个角取屏幕外接矩形；文字框另用一个 `faceW`（上下两条边投影长度的均值，
   即"牌面看起来有多宽"），因为文字要落在牌面上，而外接矩形在旋转时比牌面宽。

3. **共享几何体（Review P2-E）**：`CardEdge` 原来每张牌各建一份 `EdgesGeometry`（注释还写着
   "只创建一次"，说法过宽）。改成模块级懒单例，十张牌共用一份。
"""

import io

PATH = 'web-next/src/stage/Stage.tsx'
t = io.open(PATH, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


# ── ① 常数与纯函数从 combatLayout 来 ────────────────────────────────────────
sub(
    '''import { computeCombatFormation } from "./formation";
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
}''',
    '''import { computeCombatFormation } from "./formation";
import {
  CARD_H,
  CARD_W,
  FAN_Z,
  LIFT_Z,
  computeCombatLayout,
  type CombatLayout,
} from "./combatLayout";
import type { Phase } from "../input/pointerMachine";

/**
 * 扇形排布：返回第 `index` 张牌（共 `count` 张）的局部变换。
 *
 * 宽度与中心高度都来自 `computeCombatLayout`（区域模型的唯一来源），这里只负责"怎么摆"：
 * 中间略低、两端略高的弧线，以及**按序号单调递增的 z**。
 */
export function fanTransform(index: number, count: number, layout: CombatLayout) {
  const t = count <= 1 ? 0 : (index - (count - 1) / 2) / ((count - 1) / 2);
  return {
    x: t * layout.fanSpread,
    y: layout.fanCenterY + Math.abs(t) * layout.fanArc,
    // ⚠️ z **只随序号单调递增**（越靠右越靠前），**不要**写成 `FAN_Z + |t| * 0.12`：
    // 那样是对称的，两端在最前、中间 z 最小，窄屏互相压住时中间那张会被完全盖住，
    // 于是"看不见的牌也点不到"（闸门 25 抓到的就是这一条）。
    z: FAN_Z + index * 0.008,
    angle: -t * 0.26,
    t,
  };
}''',
    'imports + fanTransform',
)

# ── ② useFrame：一次算出 layout，替掉 cameraDistance/halfH/halfW/fanSpread ──
sub(
    '''    // ── 视图：相机距离按宽高比算，然后所有位置由 halfH/halfW 派生 ─────────────
    const aspect = size.height > 0 ? size.width / size.height : 1;
    const distance = cameraDistance(aspect);
    if (Math.abs(camera.position.z - distance) > 0.005) {
      camera.position.set(0, 0.6, distance);
      camera.lookAt(0, 0, 0);
      camera.updateProjectionMatrix();
    }
    const tan = Math.tan((45 * Math.PI) / 360);
    const halfH = tan * distance;
    const halfW = halfH * aspect;''',
    '''    // ── 版面：**一个**纯函数决定相机距离、可见范围、手牌位置与各区域边界 ────────
    const view = computeCombatLayout(
      { width: size.width, height: size.height, safeTop: 0, safeBottom: 0 },
      scene.hand.length
    );
    const distance = view.cameraDistance;
    if (Math.abs(camera.position.z - distance) > 0.005) {
      camera.position.set(0, 0.6, distance);
      camera.lookAt(0, 0, 0);
      camera.updateProjectionMatrix();
    }
    const halfH = view.halfH;
    const halfW = view.halfW;''',
    'useFrame layout',
)

# ── ③ 扇形宽度与卡牌循环 ────────────────────────────────────────────────────
sub(
    '''    // ── 卡牌：写网格变换，然后用**网格自己的世界坐标**投影 ───────────────────
    const spread = Math.min(2.6, halfW * 0.76);
    const cards: CardScreen[] = [];
    scene.hand.forEach((_, index) => {
      const group = cardRefs.current[index];
      if (!group) return;
      const local = fanTransform(index, scene.hand.length, spread, halfH);''',
    '''    // ── 卡牌：写网格变换，然后用**网格自己的世界坐标**投影 ───────────────────
    const cards: CardScreen[] = [];
    scene.hand.forEach((_, index) => {
      const group = cardRefs.current[index];
      if (!group) return;
      const local = fanTransform(index, scene.hand.length, view);''',
    'card loop head',
)

# ── ④ 四角投影 + faceW ─────────────────────────────────────────────────────
sub(
    '''      // 投影：中心 + 右上角 ⇒ 屏幕矩形（透视下用两次投影求尺寸，别用线性近似）。
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
      });''',
    '''      // 投影：**四个角**取屏幕外接矩形（Review P2-D）。
      // 原来只投"中心 + 一个未旋转的角"，牌旋转 ±15° 时宽高会偏 —— 手牌是斜着摆的，
      // 那点偏差在窄屏上正好决定"文字压不压到邻牌"。
      group.updateMatrixWorld();
      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      let maxY = -Infinity;
      const halfW = (CARD_W * scale) / 2;
      const halfH = (CARD_H * scale) / 2;
      for (const [sx, sy] of CORNERS) {
        scratch.offset.set(sx * halfW, sy * halfH, 0);
        scratch.corner.copy(scratch.offset).applyMatrix4(group.matrixWorld).project(camera);
        const px = (scratch.corner.x * 0.5 + 0.5) * size.width;
        const py = (-scratch.corner.y * 0.5 + 0.5) * size.height;
        if (px < minX) minX = px;
        if (px > maxX) maxX = px;
        if (py < minY) minY = py;
        if (py > maxY) maxY = py;
        scratch.screen.push(px, py);
      }
      // 牌面**看起来**有多宽：上、下两条边投影长度的均值。旋转时它比外接矩形窄，
      // 文字应该落在这个宽度里（外接矩形是"占位"，牌面才是"能写字的地方"）。
      const faceW =
        (Math.hypot(scratch.screen[2] - scratch.screen[0], scratch.screen[3] - scratch.screen[1]) +
          Math.hypot(scratch.screen[6] - scratch.screen[4], scratch.screen[7] - scratch.screen[5])) /
        2;
      scratch.screen.length = 0;
      cards.push({
        slot: index,
        x: (minX + maxX) / 2,
        y: (minY + maxY) / 2,
        w: maxX - minX,
        h: maxY - minY,
        faceW,
        visibleW: maxX - minX,
        hitX: (minX + maxX) / 2,
        hitY: (minY + maxY) / 2,
        lifted,
      });''',
    'four corners',
)

# ── ⑤ scratch 加 screen 缓冲；CORNERS 常量 ─────────────────────────────────
sub(
    '''      cameraDir: new THREE.Vector3(),
      offset: new THREE.Vector3(),
    }),
    []
  );''',
    '''      cameraDir: new THREE.Vector3(),
      offset: new THREE.Vector3(),
      /** 四个角的屏幕坐标（x0,y0,x1,y1,...），复用避免每帧分配。 */
      screen: [] as number[],
    }),
    []
  );''',
    'scratch screen',
)

sub(
    '''export function fanTransform(index: number, count: number, layout: CombatLayout) {''',
    '''/** 牌面四个角的单位偏移（顺序：左下、右下、右上、左上 —— 上/下两条边相邻即可）。 */
const CORNERS: readonly (readonly [number, number])[] = [
  [-1, -1],
  [1, -1],
  [1, 1],
  [-1, 1],
];

export function fanTransform(index: number, count: number, layout: CombatLayout) {''',
    'CORNERS',
)


io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('Stage: combatLayout + four corners')
