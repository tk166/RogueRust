// 显示名/介绍：**内容 id → 中文**（`zh.json` 由 `native/build_zh_i18n.py` 生成）。
//
// ## 为什么是一张表而不是改内核
//
// 内核只给**定义 id**（`rd_env_card_name_*` 返回 `strike` / `strike+`），本地化是展示层的事。
// 一张 `id → {name, text}` 的表把它隔开：内核不用知道中文，UI 不用知道 ABI。
//
// ## 回退链（每一层都是**显式**的，不猜）
//
// 1. 精确命中；
// 2. `strike+` / `searing_blow+++` → 剥掉所有 `+` 查基础条目，名字补回 `+`；
// 3. 都没有 ⇒ 返回**定义 id 本身**（`insight` / `standard.ritual`），并且**计数**。
//
// 第 3 层为什么重要：静默回退到英文会让"没翻译"看起来像"翻译成了英文"。`coverage()` 把回退
// 次数暴露出来，闸门拿它做断言（回退数超过预算就红）。

// ⚠️ 写 `.js`：闸门 27 把这个文件**直接编译成 ESM** 跑（不经打包器），Node 要求显式扩展名。
// TS 的 bundler 解析把 `.js` 映回 `.ts`，Vite 也认。
import zh from "./zh.js";

export type I18nTable = "cards" | "relics" | "potions" | "monsters" | "statuses";

interface Entry {
  readonly name: string;
  readonly text?: string;
}

const TABLES: Record<I18nTable, Record<string, Entry>> = {
  cards: zh.cards as Record<string, Entry>,
  relics: zh.relics as Record<string, Entry>,
  potions: zh.potions as Record<string, Entry>,
  monsters: zh.monsters as Record<string, Entry>,
  statuses: zh.statuses as Record<string, Entry>,
};

/** 生成这些表时 `+` 变体沿用了基础文本的条数（来源只提供英文升级描述）。 */
export const UPGRADED_WITH_BASE_TEXT = zh.upgradedWithBaseText ?? 0;

const fallbacks: Record<I18nTable, Set<string>> = {
  cards: new Set(),
  relics: new Set(),
  potions: new Set(),
  monsters: new Set(),
  statuses: new Set(),
};

function entry(table: I18nTable, id: string): Entry | null {
  const table_ = TABLES[table];
  const exact = table_[id];
  if (exact) return exact;
  // `strike+` / `searing_blow+++`：剥掉**所有** `+` 再查基础条目。
  const stripped = id.replace(/\++$/, "");
  if (stripped !== id) {
    const base = table_[stripped];
    if (base) {
      const plus = id.slice(stripped.length);
      return { name: base.name + plus, text: base.text };
    }
  }
  fallbacks[table].add(id);
  return null;
}

/**
 * 显示名。**没有条目时返回 id 本身**（并记一次回退）。
 *
 * `standard.vulnerable` 这类 id 会去掉 `standard.` 前缀再显示（`vulnerable`）——
 * 比整串更像人话，但仍然明显是"没翻译"。
 */
export function displayName(table: I18nTable, id: string): string {
  const found = entry(table, id);
  if (found) return found.name;
  const dot = id.lastIndexOf(".");
  return dot >= 0 ? id.slice(dot + 1) : id;
}

/** 介绍文本；没有条目返回空串（UI 自己决定要不要显示占位）。 */
export function displayText(table: I18nTable, id: string): string {
  return entry(table, id)?.text ?? "";
}

/** 覆盖统计：每个表有多少条、有多少 id 走了回退（闸门用它设预算）。 */
export function coverage(): Record<I18nTable, { entries: number; fallbacks: number; ids: string[] }> {
  const out = {} as Record<I18nTable, { entries: number; fallbacks: number; ids: string[] }>;
  for (const table of Object.keys(TABLES) as I18nTable[]) {
    out[table] = {
      entries: Object.keys(TABLES[table]).length,
      fallbacks: fallbacks[table].size,
      ids: Array.from(fallbacks[table]).slice(0, 20),
    };
  }
  return out;
}

/** 清空回退记录（闸门每次断言前重置，避免上一次的计数污染）。 */
export function resetCoverage(): void {
  for (const table of Object.keys(fallbacks) as I18nTable[]) fallbacks[table].clear();
}
