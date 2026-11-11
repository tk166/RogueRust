// 战斗界面版面：**纯函数**，不碰 R3F / React / DOM。
//
// 为什么需要它：之前版面常数散在三处 —— `Stage` 的 `-halfH * 0.66`、`fanSpread()` 的
// `0.76`、CSS 里 `top: 100px` 的提示条。三者互相不知道对方存在，于是"手牌压操作栏"
// "气泡压 HUD" 这类问题只能靠截图发现（§353 就是量出来才修对的）。
//
// 现在只有一个地方决定**每一块屏幕高度归谁**：
//
//   ┌──────────────┐ safeTop
//   │ HUD          │ hudBottom
//   ├──────────────┤ combatTop
//   │ 战场         │
//   ├──────────────┤ combatBottom / handTop
//   │ 手牌         │
//   ├──────────────┤ handBottom
//   │ 操作栏       │ actionsTop
//   └──────────────┘ safeBottom
//
// 手牌的**世界坐标**由"手牌底边贴着操作栏"反推（透视：手牌在 z≈0.9，比 z=0 平面更近，
// 所以不能拿 z=0 的比例去推 —— §353 踩过）。

/** 卡牌尺寸（世界单位）。**唯一一份**：`Stage` 与文字覆盖层都从这里取。 */
export const CARD_W = 0.62;
export const CARD_H = 0.86;
/** 手牌所在的 z 平面（离相机更近 ⇒ 投影更大）。 */
export const FAN_Z = 0.9;
/** 抬起的牌所在的 z 平面。 */
export const LIFT_Z = 1.45;

const FOV_DEG = 45;
/** 横向必须装得下的世界半宽（两个敌人 + 半径 + 余量）。 */
const FIT_HALF_WIDTH = 2.3;
const MIN_CAMERA = 6;
const MAX_CAMERA = 9.5;
/**
 * HUD 一行的高度（uikit 的 padding + 文字）。
 *
 * 36 是**量出来的**：390×844 的截图里 HP/BLK/EN/TURN 四个盒子占到约 86 CSS 像素
 * （14 padding + 2×36）。uikit 的 HUD 是 3D 画的，DOM 量不到 —— 所以这个数只能靠截图校准，
 * 改动 HUD 内边距时要跟着改。
 */
const HUD_ROW_H = 36;
const HUD_PAD = 14;
/** 底部操作栏高度（SETTINGS / END TURN）。 */
const ACTIONS_H = 56;
/** 手牌之间至少要露出这么多像素，否则只能显示费用（紧凑态）。 */
const MIN_STRIP_PX = 20;
const MAX_SPREAD = 2.6;
const NARROW_WIDTH = 600;

export interface CombatViewport {
  readonly width: number;
  readonly height: number;
  /** `env(safe-area-inset-top)`，CSS 像素。 */
  readonly safeTop?: number;
  readonly safeBottom?: number;
}

export interface CombatRegions {
  readonly hudTop: number;
  readonly hudBottom: number;
  readonly combatTop: number;
  readonly combatBottom: number;
  readonly handTop: number;
  readonly handBottom: number;
  readonly actionsTop: number;
}

export interface CombatLayout {
  readonly aspect: number;
  readonly cameraDistance: number;
  readonly halfW: number;
  readonly halfH: number;
  /** 手牌扇形的半宽（世界单位）。 */
  readonly fanSpread: number;
  /** 手牌**中心**的世界 y（由"底边贴操作栏"反推）。 */
  readonly fanCenterY: number;
  /** 扇形弧高（两端比中间高多少，世界单位）。 */
  readonly fanArc: number;
  readonly regions: CombatRegions;
}

/**
 * 相机距离：**保证横向装得下 `FIT_HALF_WIDTH`**，并夹在 `[MIN_CAMERA, MAX_CAMERA]`。
 * 竖屏（aspect 0.46）会被拉到 9.5：敌人不会被切在两侧，牌也还在视口里。
 */
export function cameraDistance(aspect: number, fovDeg = FOV_DEG): number {
  const tan = Math.tan((fovDeg * Math.PI) / 360);
  const needed = FIT_HALF_WIDTH / (tan * Math.max(aspect, 0.2));
  return Math.min(MAX_CAMERA, Math.max(MIN_CAMERA, needed));
}

/**
 * 在深度 `worldZ` 处，**一个世界单位等于多少 CSS 像素**。
 *
 * ⚠️ 这是"透视不是线性的"的落地形式：手牌在 z=0.9，比 z=0 平面离相机近 0.9 个世界单位，
 * 所以同一个世界长度在屏幕上更大。拿 z=0 的比例去算手牌位置会让牌压到操作栏下面（§353）。
 */
export function pxPerWorldAt(
  cameraDist: number,
  worldZ: number,
  height: number,
  fovDeg = FOV_DEG
): number {
  const tan = Math.tan((fovDeg * Math.PI) / 360);
  return height / 2 / (tan * Math.max(0.1, cameraDist - worldZ));
}

export function computeCombatLayout(view: CombatViewport, handCount: number): CombatLayout {
  if (!(view.width > 0 && view.height > 0)) {
    throw new RangeError(`viewport must be positive; got ${view.width}x${view.height}`);
  }
  const safeTop = Math.max(0, view.safeTop ?? 0);
  const safeBottom = Math.max(0, view.safeBottom ?? 0);
  const aspect = view.width / view.height;
  const distance = cameraDistance(aspect);
  const tan = Math.tan((FOV_DEG * Math.PI) / 360);
  const halfH = tan * distance;
  const halfW = halfH * aspect;

  // ── 区域（CSS 像素，从屏幕顶往下量）────────────────────────────────────
  const hudRows = view.width < NARROW_WIDTH ? 2 : 1;
  const hudBottom = safeTop + HUD_PAD + hudRows * HUD_ROW_H;
  const actionsTop = view.height - safeBottom - ACTIONS_H;
  const pxPerWorld = pxPerWorldAt(distance, FAN_Z, view.height);
  const cardHalfPx = (CARD_H / 2) * pxPerWorld;
  // 手牌底边贴着操作栏往上 4px（卡片高度按手牌平面算）。
  const handBottom = actionsTop - 4;
  const handCenterPx = handBottom - cardHalfPx;
  const fanCenterY = -(handCenterPx - view.height / 2) / pxPerWorld;
  const combatTop = hudBottom + 8;
  const combatBottom = Math.max(combatTop + 1, handCenterPx - cardHalfPx - 8);

  // ── 扇形宽度 ───────────────────────────────────────────────────────────
  // ① 基准：最多占可见宽度的 76%，且不超过 MAX_SPREAD；
  // ② 下限：牌与牌之间至少露出 MIN_STRIP_PX（否则只剩费用数字，见 TextOverlay 的紧凑态）；
  // ③ 上限：最外侧那张牌的**外缘**必须留在视口内。
  const base = Math.min(MAX_SPREAD, halfW * 0.76);
  const minStrideWorld = MIN_STRIP_PX / pxPerWorld;
  const minByStrip = handCount > 1 ? (minStrideWorld * (handCount - 1)) / 2 : 0;
  const maxByFit = Math.max(0, halfW * 0.98 - CARD_W / 2);
  const fanSpread = Math.min(maxByFit, Math.max(base, minByStrip));

  return {
    aspect,
    cameraDistance: distance,
    halfW,
    halfH,
    fanSpread,
    fanCenterY,
    fanArc: halfH * 0.05,
    regions: {
      hudTop: safeTop,
      hudBottom,
      combatTop,
      combatBottom,
      handTop: combatBottom,
      handBottom,
      actionsTop,
    },
  };
}
