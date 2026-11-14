// P4 的**纯展示逻辑**：位掩码 → 选项、效果判别值 → 人话、价格 → 买得起吗。
//
// 为什么单独一层：这些都是"内核给一个数字，界面要变成一句话/一个按钮"的映射，最容易与内核漂
// （同一个词表两处认识）。放在纯函数里，闸门 35 不需要浏览器就能把它们**逐值**钉住。

// ── 篝火（§259 的位掩码）────────────────────────────────────────────────────
//
// ⚠️ 位序是**硬约定**（内核注释里写明"页面按它读"）：`Rest 1 | Smith 2 | Recall 4 | Lift 8 |
// Toke 16 | Dig 32`。改顺序 = 改语义。
export const CAMPFIRE = {
  rest: 1,
  smith: 2,
  recall: 4,
  lift: 8,
  toke: 16,
  dig: 32,
} as const;

export type CampfireId = keyof typeof CAMPFIRE;

/** 一个篝火选项。`needsDeck` 表示"点下去要先从牌组挑一张"（走牌组选择器）。 */
export interface CampfireOption {
  readonly id: CampfireId;
  readonly label: string;
  readonly hint: string;
  readonly needsDeck: boolean;
}

/**
 * 位掩码 → 选项表（**按位序**，与内核的位序一致）。
 *
 * 未定义的位会被忽略 —— 但那是"内核加了新选项而 UI 没跟上"，所以 `unknownCampfireBits()`
 * 把它单独报出来（闸门 35 断言它为空；真出现了就是一条可见的诊断，不是静默少一个按钮）。
 */
export function campfireOptionsFromMask(mask: number): CampfireOption[] {
  const all: (CampfireOption & { bit: number })[] = [
    { id: "rest", bit: CAMPFIRE.rest, label: "休息", hint: "回复生命", needsDeck: false },
    { id: "smith", bit: CAMPFIRE.smith, label: "锻造", hint: "升级一张牌", needsDeck: true },
    { id: "recall", bit: CAMPFIRE.recall, label: "回忆", hint: "拿红钥匙", needsDeck: false },
    { id: "lift", bit: CAMPFIRE.lift, label: "举重", hint: "永久 +1 力量", needsDeck: false },
    { id: "toke", bit: CAMPFIRE.toke, label: "抽烟斗", hint: "删掉一张牌", needsDeck: true },
    { id: "dig", bit: CAMPFIRE.dig, label: "挖宝", hint: "抽一件遗物", needsDeck: false },
  ];
  return all
    .filter((option) => (mask & option.bit) !== 0)
    .map(({ bit: _bit, ...option }) => option);
}

/** 掩码里 UI **不认识**的位（0 = 认识全部）。 */
export function unknownCampfireBits(mask: number): number {
  const known = Object.values(CAMPFIRE).reduce((sum, bit) => sum | bit, 0);
  return mask & ~known;
}

// ── 事件效果（与祝福同一套判别值）──────────────────────────────────────────
/**
 * 效果码 —— **内核的闭集**（`kernel/rd-wasm/src/run.rs::effect_code` / `effect_code_of`）。
 *
 * ⚠️ 这张表必须与内核**逐条对齐**：§9 只有 1..5，之后 §143（6..8）、§278（11/12）、
 * §280（13/14/15）、§285（16）陆续加码，界面停在 1..5 就把 `remove_card`（6）显示成
 * "未知效果 6（0）"（玩家实测：事件「翅膀雕像」的 [祈祷] 选项）。
 *
 * `none = -1` 不是"未知"：内核用它表示**"这一条没有效果码"** —— 真正的作用在内容字符串里
 * （`card:<id>` / `relic_lose:<id>` / `transform_choose:<n>` …），而选项自己的文字已经说清了。
 */
export const EFFECT = {
  none: -1,
  heal: 1,
  gold: 2,
  loseHealth: 3,
  maxHealth: 4,
  nothing: 5,
  removeCard: 6,
  upgradeCard: 7,
  transformCard: 8,
  gainCurse: 9,
  gainRelic: 10,
  loseHealthPercent: 11,
  loseMaxHealthPercent: 12,
  goldCost: 13,
  healPercent: 14,
  healFull: 15,
  goldRandom: 16,
} as const;

/**
 * 效果判别值 → 人话。
 *
 * ⚠️ `nothing` 是 **5**，不是 0：0 在别处是"没有"，这里"没有效果"有专门的取值，
 * 所以不能拿 `kind === 0` 判"无"（那会把**所有**未知效果都显示成"无"）。
 *
 * ⚠️ `-1` 返回**空串**（"没有效果码"≠"未知"）：调用方不画那一行。把它写成"未知效果 -1"
 * 是在报告一个不存在的错误 —— 玩家会以为事件坏了。
 */
export function effectLabel(kind: number, amount: number): string {
  switch (kind) {
    case EFFECT.none:
      return "";
    case EFFECT.heal:
      return `回复 ${amount} 点生命`;
    case EFFECT.gold:
      return `获得 ${amount} 金币`;
    case EFFECT.loseHealth:
      return `失去 ${amount} 点生命`;
    case EFFECT.maxHealth:
      return `生命上限 +${amount}`;
    case EFFECT.nothing:
      return "无";
    case EFFECT.removeCard:
      return "从牌组移除一张牌";
    case EFFECT.upgradeCard:
      return "升级一张牌";
    case EFFECT.transformCard:
      return "变化一张牌";
    case EFFECT.gainCurse:
      return "获得一张诅咒牌";
    case EFFECT.gainRelic:
      return "获得一件遗物";
    // §278：`amount` 是**千分比**（`250` = 25%）—— 内核已经把它换算成同一个单位。
    case EFFECT.loseHealthPercent:
      return `失去 ${Math.round(amount / 10)}% 最大生命`;
    case EFFECT.loseMaxHealthPercent:
      return `生命上限 −${Math.round(amount / 10)}%`;
    case EFFECT.goldCost:
      return `支付 ${amount} 金币`;
    case EFFECT.healPercent:
      return `回复 ${Math.round(amount / 10)}% 最大生命`;
    case EFFECT.healFull:
      return "回复全部生命";
    case EFFECT.goldRandom:
      return "获得随机数量的金币";
    default:
      // 真正的"未知"：内核加了一个码而界面没跟上。响亮，但只有这一条路。
      return `未知效果 ${kind}（${amount}）`;
  }
}

/**
 * 一条选项的效果列表 → 一句话（多条用 ` · ` 连）。
 *
 * 全空（每条都是 `-1`，或列表本身为空）⇒ 返回**空串**：调用方据此**不画**这一行，
 * 而不是画一个"无"。空列表仍然返回"无"（那确实是"没有效果"）。
 */
export function effectSummary(effects: readonly { kind: number; amount: number }[]): string {
  if (effects.length === 0) return "无";
  return effects
    .map((effect) => effectLabel(effect.kind, effect.amount))
    .filter((line) => line.length > 0)
    .join(" · ");
}

// ── 商店 ────────────────────────────────────────────────────────────────────
export type ShelfKind = "card" | "relic" | "potion" | "colorless";

export interface ShelfRow {
  readonly slot: number;
  readonly id: string;
  readonly price: number;
  /** `price >= 0` 才是"还在卖"（`-1` = 已售）。 */
  readonly forSale: boolean;
  readonly affordable: boolean;
  /**
   * 放得下吗（§380）。只有药水那一排会是 `false`（腰带满）。
   *
   * ⚠️ 与 `affordable` **并列**而不是合并：页面要能分别说"金币不够"和"腰带满了"——
   * 合成一个布尔值就只剩一句笼统的"不能买"，玩家不知道该去赚金币还是先喝一瓶。
   */
  readonly room: boolean;
}

/**
 * 把内核给的货架变成可渲染的行。
 *
 * **价格只由内核给**（`_price` 已经算上会员卡/涨价），这里只做"买得起吗"的比较 ——
 * 页面自己算价必然与内核漂，而"显示 100 却收 120"是最难查的那种 bug。
 */
export function shelfRows(
  entries: readonly { slot: number; id: string; price: number }[],
  gold: number,
  /**
   * 还有没有地方放（§380：只有药水那一排需要 —— 腰带满了就装不下）。
   * `undefined` = 这一排没有容量限制（卡/遗物）。
   */
  room = true
): ShelfRow[] {
  return entries.map((entry) => ({
    slot: entry.slot,
    id: entry.id,
    price: entry.price,
    forSale: entry.price >= 0,
    affordable: entry.price >= 0 && entry.price <= gold,
    // "买得起"与"放得下"是两件事：腰带 3/3 时金币再多也买不了。
    room,
  }));
}

/** 腰带还能不能再装一瓶（`§380`）。`slots <= 0` = 没有局 ⇒ 当作不能。 */
export function beltHasRoom(held: number, slots: number): boolean {
  return slots > 0 && held < slots;
}

/** 这家店的删卡服务能不能用（`§343`：每家店一次）。`-1` 没有局 ⇒ 当作不能用。 */
export function removalUsable(available: number, price: number, gold: number): boolean {
  return available === 1 && price >= 0 && price <= gold;
}

// ── 牌组选择器（`DeckSelectOverlay`）──────────────────────────────────────
//
// 六处会用到它：祝福选牌（`pending 7`）、事件选牌（`pending 8`）、锻造、抽烟斗、付费删牌、
// 遗物欠账改牌（`pickup_change` 1..4）。它们**都是"给一个牌组下标"**，所以选择器只需要知道
// "为什么在选"，好把标题写对、并在确认后调**对应**的那个动作。

export type DeckPickPurpose =
  | "blessing"
  | "event"
  | "smith"
  | "toke"
  | "remove"
  | "pickup"
  | "browse";

export interface DeckPickCopy {
  readonly title: string;
  readonly hint: string;
  /** 选中之后要不要再确认（浏览模式没有动作）。 */
  readonly actionable: boolean;
}

/** "为什么在选" → 标题/提示。**每一处都说清代价**（付费删牌要显示价格）。 */
export function deckPickCopy(purpose: DeckPickPurpose, price = 0): DeckPickCopy {
  switch (purpose) {
    case "blessing":
      return { title: "祝福：选一张牌", hint: "选中的牌会被处理（升级/删除/变形）", actionable: true };
    case "event":
      return { title: "事件：选一张牌", hint: "这个事件要从牌组里挑一张", actionable: true };
    case "smith":
      return { title: "锻造：升级一张牌", hint: "选一张还没升级的牌", actionable: true };
    case "toke":
      return { title: "抽烟斗：删一张牌", hint: "删掉的牌永久离开牌组", actionable: true };
    case "remove":
      return {
        title: "商店：删一张牌",
        hint: price > 0 ? `花费 ${price} 金币` : "花费金币",
        actionable: true,
      };
    case "pickup":
      return { title: "遗物：改一张牌", hint: "遗物要求你从牌组里挑一张", actionable: true };
    default:
      return { title: "牌组", hint: "只是看看", actionable: false };
  }
}

/** 牌组里"能不能被这次操作选中"：升级过的牌不能再升级（`indexOf('+')`）。 */
export function deckPickAllowed(purpose: DeckPickPurpose, id: string): boolean {
  // 锻造只能选**没升级**的牌（内核也会拒绝，但界面不该先画成可点）。
  if (purpose === "smith") return !id.includes("+");
  return true;
}

// ── 药水 ────────────────────────────────────────────────────────────────────
export const POTION_EFFECT = {
  unknown: 0,
  targetEnemy: 1,
  heroOrRun: 2,
  allEnemies: 3,
} as const;

export type PotionTargeting = "enemy" | "self" | "all" | "unknown";

export function potionTargeting(effect: number): PotionTargeting {
  switch (effect) {
    case POTION_EFFECT.targetEnemy:
      return "enemy";
    case POTION_EFFECT.heroOrRun:
      return "self";
    case POTION_EFFECT.allEnemies:
      return "all";
    default:
      return "unknown";
  }
}

/** 药水能不能现在用：战斗外只能喝 `needsFight === 0` 的。 */
export function potionUsable(needsFight: number, inFight: boolean): boolean {
  if (needsFight < 0) return false;
  return needsFight === 0 || inFight;
}
