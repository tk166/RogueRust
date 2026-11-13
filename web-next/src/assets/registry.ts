// 素材**注册表**：内容 id → 可画的素材；缺失时降级并**计数**。
//
// ## 三层
//
// 1. `manifest.ts`（**生成物**）：内容镜像里的每个 id 都有一条描述 —— 所以"内容加了东西而美术
//    没跟上"在结构上不会静默；
// 2. 这一层：把清单 + 几何目录拼成渲染层要的东西，并且对**清单里没有**的 id 走降级
//    （`lettersOf` 现算 / `fallbackFigure`），同时记进 `unknownAssets()`；
// 3. 渲染层（`EnemyFigure` / `Badge`）：只认"原型名 + 调色板 + 角色"，不认具体 id。
//
// ## 为什么降级还要计数
//
// 静默降级会让"这个敌人跟别的一样"看起来像"设计如此"（§4 的工具形态）。计数之后，
// 闸门 45 断言它为空；真出现了就是一条可见的诊断。

import {
  ARCHETYPES,
  ASSET_COUNTS,
  BADGE_ASSETS,
  ENEMY_ASSETS,
  PALETTES,
  type BadgeAsset,
  type EnemyAsset,
} from "./manifest.js";
import { FIGURES, type Archetype } from "./geometry.js";

export type BadgeKind = "cards" | "relics" | "potions" | "statuses";

export interface Palette {
  readonly name: string;
  readonly body: string;
  readonly accent: string;
  readonly eye: string;
}

/** 敌人素材（渲染层需要的全部东西）。 */
export interface EnemyLook {
  readonly id: string;
  readonly archetype: string;
  readonly figure: Archetype;
  readonly palette: Palette;
  readonly scale: number;
  readonly boss: boolean;
  /** `true` = 清单里没有这个 id，走的是降级（闸门断言它为 0）。 */
  readonly fallback: boolean;
}

const unknown = new Set<string>();

/** 清单 → 素材；缺失时降级（确定性：同一个 id 每次降级到同一个原型）。 */
export function enemyLook(id: string): EnemyLook {
  const entry: EnemyAsset | undefined = ENEMY_ASSETS[id];
  const paletteIndex = entry?.palette ?? stableHash(id) % PALETTES.length;
  const archetype = entry?.archetype ?? ARCHETYPES[stableHash(id) % ARCHETYPES.length];
  const figure = FIGURES[archetype];
  if (!entry) unknown.add(`enemy:${id}`);
  if (!figure) {
    // 清单引用了一个**几何目录里不存在**的原型：这不是"缺素材"，是生成器/目录漂了。
    unknown.add(`archetype:${archetype}`);
    return {
      id,
      archetype: "slime",
      figure: FIGURES.slime,
      palette: PALETTES[paletteIndex],
      scale: entry?.scale ?? 1,
      boss: entry?.boss ?? false,
      fallback: true,
    };
  }
  return {
    id,
    archetype,
    figure,
    palette: PALETTES[paletteIndex],
    scale: entry?.scale ?? 1,
    boss: entry?.boss ?? false,
    fallback: entry === undefined,
  };
}

/** 二维元素（卡面/遗物/药水/状态）：两位大写字母 + 调色板。 */
export interface BadgeLook {
  readonly id: string;
  readonly kind: BadgeKind;
  readonly letters: string;
  readonly palette: Palette;
  readonly fallback: boolean;
}

/** 内容 id → 两位大写字母（与生成器的 `letters_for` **同一条规则**）。 */
export function lettersOf(assetId: string): string {
  const base = assetId.replace(/\++$/, "");
  const words = base.replace(/\./g, "_").replace(/-/g, "_").split("_").filter(Boolean);
  let letters =
    words.length >= 2 ? words[0].slice(0, 1) + words[1].slice(0, 1) : (words[0] ?? "").slice(0, 2);
  letters = letters.toUpperCase();
  while (letters.length < 2) letters += "X";
  return letters.slice(0, 2);
}

export function badgeLook(kind: BadgeKind, id: string): BadgeLook {
  const entry: BadgeAsset | undefined = BADGE_ASSETS[kind][id];
  if (!entry) unknown.add(`${kind}:${id}`);
  return {
    id,
    kind,
    letters: entry?.letters ?? lettersOf(id),
    palette: PALETTES[entry?.palette ?? stableHash(`${kind}|${id}`) % PALETTES.length],
    fallback: entry === undefined,
  };
}

/** 见过但清单里没有的 id（闸门 45 断言为空）。 */
export function unknownAssets(): string[] {
  return Array.from(unknown).sort();
}

export function resetUnknownAssets(): void {
  unknown.clear();
}

/** 清单规模（诊断/素材库页面显示）。 */
export function assetCounts(): typeof ASSET_COUNTS {
  return ASSET_COUNTS;
}

/** 原型目录（素材库页面按它列）。 */
export function archetypeNames(): string[] {
  return [...ARCHETYPES];
}

/** 与生成器同一条稳定哈希（FNV-1a 32 位）—— 降级时用它挑原型/调色板。 */
function stableHash(text: string): number {
  let value = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    value ^= text.charCodeAt(index);
    value = (value * 0x01000193) >>> 0;
  }
  return value >>> 0;
}
