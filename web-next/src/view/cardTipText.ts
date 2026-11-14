// 悬浮详情 / 选牌弹窗**共用的文案层**（§379 / §384）：纯函数，与 React 无关。
//
// 为什么单独一层：`ChoiceModal`（选牌）与商店/奖励的 `CardTip` 都要显示
// "种类 · 费用 · 稀有度"，而这一行只能**在一处**算 —— 两处各写一份必然漂
// （§382 的"未知效果"就是这么来的：同一个词表被两处认识）。
//
// ⚠️ 这一层必须能被**闸门直接编译成 ESM**（不经打包器）⇒ 只 import 纯模块，
// 不 import 任何 `.tsx`。渲染壳在 `run/overlays/CardTip.tsx`。

import { displayName, displayText } from "../i18n/index.js";
import cardMeta from "./cardMeta.js";

/** 内容包稀有度 → 中文（内容里就这几个值）。 */
const RARITY_LABEL: Record<string, string> = {
  Basic: "基础",
  Common: "普通",
  Uncommon: "罕见",
  Rare: "稀有",
  Special: "特殊",
  Event: "事件",
  Curse: "诅咒",
  Status: "状态",
};

const KIND_LABEL: Record<string, string> = {
  attack: "攻击",
  skill: "技能",
  power: "能力",
  status: "状态",
  curse: "诅咒",
};

export type TipKind = "card" | "relic" | "potion";

export interface TipRequest {
  readonly kind: TipKind;
  /** 内容 id（`bludgeon` / `anchor` / `fire_potion`）。 */
  readonly id: string;
  /** 可选：挂在右上角的一行附加信息（商店的"价格 138"、奖励的"第 2 张"）。 */
  readonly note?: string;
}

/** 卡牌的元数据（剥 `+` 查基础条目，与 `combatView.metaOf` 同一条回退规则）。 */
function cardMetaOf(id: string) {
  const table = cardMeta as Record<string, { kind?: string; cost?: number | string; rarity?: string }>;
  return table[id] ?? table[id.replace(/\++$/, "")] ?? null;
}

/** 提示条里的四行内容。**纯函数**，闸门可以脱离浏览器断言它。 */
export function describeTip(request: TipRequest): {
  title: string;
  subtitle: string;
  body: string;
  note: string;
} {
  const table = request.kind === "card" ? "cards" : request.kind === "relic" ? "relics" : "potions";
  const title = displayName(table, request.id) || request.id;
  const body = displayText(table, request.id) || "";
  if (request.kind !== "card") {
    return {
      title,
      subtitle: request.kind === "relic" ? "遗物" : "药水",
      body,
      note: request.note ?? "",
    };
  }
  const meta = cardMetaOf(request.id);
  const kind = meta?.kind ? (KIND_LABEL[meta.kind] ?? meta.kind) : "卡牌";
  const cost =
    meta?.cost === undefined
      ? ""
      : meta.cost === "X"
        ? "X 费"
        : meta.cost === "-"
          ? "不可打出"
          : `${meta.cost} 费`;
  const rarity = meta?.rarity ? (RARITY_LABEL[meta.rarity] ?? meta.rarity) : "";
  return {
    title,
    subtitle: [kind, cost, rarity].filter(Boolean).join(" · "),
    body,
    note: request.note ?? "",
  };
}
