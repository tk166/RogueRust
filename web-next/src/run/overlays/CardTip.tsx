// 悬浮详情（§379）：**一个组件，四处复用**（奖励屏 / 商店 / 牌组 / 事件候选）。
//
// ## 玩家报的是什么
//
// "商店和奖励界面每个卡片没有跟随鼠标或者触摸的悬浮窗提示卡牌的具体内容，怎么选全靠盲猜。"
//
// 之前奖励屏只有 `名字 + 内容 id`，商店只有 `名字 + 价格`。而"这张牌 3 费打 32"与
// "这张牌 1 费打 6"是完全不同的决策 —— 名字读不出来。
//
// ## 两条交互（鼠标 / 触摸各一条，不互相顶）
//
// * **鼠标**：`pointerenter` 就显示（跟随到固定面板，不做"跟着光标飘"的浮窗 ——
//   贴边时飘窗会被裁掉，而且它会盖住相邻的牌，反而更难选）。
// * **触摸**：`pointerdown` 显示。⚠️ 触摸上**不**阻止点击 —— 商店的"点一下买"必须保留，
//   所以触摸是"按住不放看详情、松手仍然买"。真正不想买的人可以按住再移开（浏览器会取消 click）。
//
// ## 为什么是固定面板而不是 tooltip
//
// 固定面板的位置可预测、可断言（`data-card-tip`），也不会被容器裁掉。StS 手机版也是
// "点一下弹一张大卡"。像素位置交给 CSS，闸门只断言**内容**（名字/费用/稀有度/规则都在）。

import { displayName, displayText } from "../../i18n/index.js";
import cardMeta from "../../view/cardMeta.js";

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
  const cost = meta?.cost === undefined ? "" : meta.cost === "X" ? "X 费" : meta.cost === "-" ? "不可打出" : `${meta.cost} 费`;
  const rarity = meta?.rarity ? (RARITY_LABEL[meta.rarity] ?? meta.rarity) : "";
  return {
    title,
    subtitle: [kind, cost, rarity].filter(Boolean).join(" · "),
    body,
    note: request.note ?? "",
  };
}

export interface CardTipProps {
  readonly request: TipRequest | null;
}

/**
 * 固定位置的详情面板。`request === null` 时**不渲染**（不留一个空盒子占位）。
 */
export function CardTip({ request }: CardTipProps) {
  if (!request) return null;
  const described = describeTip(request);
  return (
    <div
      className="card-tip"
      data-card-tip={request.id}
      data-tip-kind={request.kind}
      data-tip-title={described.title}
      data-tip-subtitle={described.subtitle}
      role="tooltip"
    >
      <div className="card-tip__head">
        <span className="card-tip__title" data-tip-title-text>
          {described.title}
        </span>
        {described.note && (
          <span className="card-tip__note" data-tip-note>
            {described.note}
          </span>
        )}
      </div>
      {described.subtitle && (
        <div className="card-tip__subtitle" data-tip-subtitle-text>
          {described.subtitle}
        </div>
      )}
      <div className="card-tip__body" data-tip-body>
        {described.body || "（这一条没有说明文本）"}
      </div>
    </div>
  );
}
