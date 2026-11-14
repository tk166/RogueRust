// **表现层的第二层：`effectKey` → 视觉配方**（纯数据 + 一个查表函数）。
//
// ## 这一层与素材注册表的区别（审阅 §6 的标题就是这个）
//
// * `assets/registry.ts`（**VisualAssetRegistry**）回答"这个 id 长什么样"（原型/调色板/字母）；
// * 本文件（**PresentationRegistry**）回答"这件事发生时播什么"（颜色/形状/时长/方向/是否震屏）。
//
// 两者都是**数据驱动**：加一张卡、一个状态、一种敌人不需要改 `Stage.tsx` / `EnemyFigure.tsx`。
//
// ## 为什么现在只做到"配方"而不做 3D 动画
//
// 审阅 §6/§7 的建议是对的：先建**语义契约**（Cue + Registry），再让 GLB/clip/粒子作为
// **可替换的执行器**接进来。所以这一轮：
// * Cue 与配方都是纯函数/纯数据（闸门 57 穷尽断言）；
// * `BeatLayer` 只消费"配方里的颜色/时长/形状"，仍然是 DOM 飘字；
// * `kind: 'gltf'` 那一路（`VisualAssetSpec`）留到 R3，接口先在这里定形（见 `VisualAssetSpec`）。
//
// ## 兜底纪律
//
// 查不到 `effectKey` ⇒ **不静默**：用 `fallback` 配方（中性灰）并让调用方计数。
// 这与 `assets/registry.ts` 的 `unknown` 集合是同一条规矩。

/** 飘字/特效的**形状**（现在只影响 CSS class；将来是粒子/轨迹的预设名）。 */
export type CueShape =
  | "spark" // 伤害：短促、向右偏
  | "shield" // 格挡：稳住、蓝色
  | "cross" // 治疗：向上、绿色
  | "up" // 增益
  | "down" // 减益
  | "burst" // 倒下/摧毁
  | "banner" // 回合
  | "note" // 中性（来源未知）
  | "card"; // 出牌

export interface CueRecipe {
  /** 颜色（CSS 值）。**同一份**给 DOM 与将来的 3D 材质用，避免两处调色。 */
  readonly color: string;
  readonly shape: CueShape;
  /** 时长（毫秒）。导演会再夹一次上限。 */
  readonly duration: number;
  /** 是否震屏（只有重击/倒下这类才给）。 */
  readonly shake: boolean;
  /** 给将来的 3D 执行器留的预设名（现在不用）。 */
  readonly motion: string;
}

/** 兜底配方：来源/种类未知时用它，调用方负责计数（不静默）。 */
export const FALLBACK_RECIPE: CueRecipe = {
  color: "#9fb3c6",
  shape: "note",
  duration: 360,
  shake: false,
  motion: "none",
};

const RECIPES: Record<string, CueRecipe> = {
  // ── 伤害 ────────────────────────────────────────────────────────────────
  "damage.direct": { color: "#ff8a7a", shape: "spark", duration: 420, shake: true, motion: "hit" },
  // 持续伤害**不震屏**：它没有"被打"的动作，震屏会让玩家以为是敌人出手。
  "damage.dot": { color: "#a7d16a", shape: "spark", duration: 380, shake: false, motion: "tick" },
  "block.gain": { color: "#8ac6ff", shape: "shield", duration: 380, shake: false, motion: "raise" },
  "heal.gain": { color: "#7ee0a8", shape: "cross", duration: 420, shake: false, motion: "rise" },
  "status.change": { color: "#c9b6ff", shape: "up", duration: 380, shake: false, motion: "pop" },
  "status.change.unknown": { color: "#9fb3c6", shape: "note", duration: 360, shake: false, motion: "none" },
  "status.remove": { color: "#9fb3c6", shape: "note", duration: 420, shake: false, motion: "fade" },
  "status.prevented": { color: "#8ac6ff", shape: "shield", duration: 420, shake: false, motion: "deflect" },
  "enemy.downed": { color: "#ffb3ab", shape: "burst", duration: 640, shake: true, motion: "collapse" },
  "enemy.escaped": { color: "#9fb3c6", shape: "note", duration: 520, shake: false, motion: "leave" },
  "enemy.summon": { color: "#d6b3ff", shape: "burst", duration: 640, shake: false, motion: "appear" },
  "enemy.destroyed": { color: "#ffb3ab", shape: "burst", duration: 520, shake: false, motion: "collapse" },
  "turn.start": { color: "#9fd0ff", shape: "banner", duration: 380, shake: false, motion: "slide" },
  "turn.end": { color: "#9fb3c6", shape: "banner", duration: 380, shake: false, motion: "slide" },
  "card.play": { color: "#ffd166", shape: "card", duration: 420, shake: false, motion: "cast" },

  // ── 逐卡的出牌表现（§398：这就是"斩击 vs 重击"能分开的地方）─────────────
  //
  // ⚠️ 只列**有区别意义**的几张，其余卡落到 `card.*` 的通用兜底（见 `recipeFor`）。
  // 加一张卡的表现 = 在这里加一行，不需要改任何组件（审阅 §9 的 R4 目标）。
  "card.strike": { color: "#ffd166", shape: "card", duration: 420, shake: true, motion: "slash" },
  "card.bash": { color: "#ff9d5c", shape: "card", duration: 520, shake: true, motion: "slam" },
  "card.twin_strike": { color: "#ffd166", shape: "card", duration: 460, shake: true, motion: "slash2" },
  "card.cleave": { color: "#ffb37a", shape: "card", duration: 480, shake: true, motion: "sweep" },
  "card.iron_wave": { color: "#9fd0ff", shape: "card", duration: 460, shake: false, motion: "slash_block" },
  "card.defend": { color: "#8ac6ff", shape: "card", duration: 380, shake: false, motion: "guard" },
  "card.bash+": { color: "#ff9d5c", shape: "card", duration: 560, shake: true, motion: "slam" },
};

/** 所有**显式**配方（闸门穷尽断言用：不许有空值、颜色必须是合法 CSS 色）。 */
export function recipeKeys(): string[] {
  return Object.keys(RECIPES).sort();
}

/**
 * 查配方。
 *
 * 回退顺序（**显式**，每层都有理由）：
 * 1. 精确命中（`card.bash`）；
 * 2. 剥掉 `+` 再查（`card.bash+` 有显式条目就用它，没有就用基础行）；
 * 3. `kind` 的通用条目（`card.<defId>` 没写 ⇒ `card.play`）；
 * 4. `FALLBACK_RECIPE`，并让调用方计数（不静默）。
 */
export function recipeFor(effectKey: string): { recipe: CueRecipe; fallback: boolean } {
  const exact = RECIPES[effectKey];
  if (exact) return { recipe: exact, fallback: false };
  const base = RECIPES[effectKey.replace(/\+\d*$/, "")];
  if (base) return { recipe: base, fallback: false };
  // `card.<defId>` 没有专门配方 ⇒ 用出牌的通用配方。
  if (effectKey.startsWith("card.")) {
    return { recipe: RECIPES["card.play"], fallback: false };
  }
  const head = effectKey.split(".")[0];
  const family = RECIPES[`${head}.direct`] ?? RECIPES[`${head}.gain`];
  if (family) return { recipe: family, fallback: false };
  return { recipe: FALLBACK_RECIPE, fallback: true };
}

/**
 * 将来的**素材规格**判别联合（审阅 §7 的建议，先定形不实现）。
 *
 * 为什么先写在这里：`EnemyFigure` 现在直接吃 `Archetype`（程序化几何）。等真的接 GLB 时，
 * 把契约换成这个判别联合就够了 —— 不用重写组件，也不会有"半程序化半 GLB"的中间态。
 */
export type VisualAssetSpec =
  | {
      readonly kind: "procedural";
      readonly archetype: string;
      readonly paletteId: number;
      readonly scale: number;
    }
  | {
      readonly kind: "gltf";
      readonly url: string;
      readonly clips: Record<string, string>;
      readonly scale: number;
      readonly sockets?: Record<"head" | "hand" | "impact" | "status", string>;
      readonly sha256?: string;
    };
