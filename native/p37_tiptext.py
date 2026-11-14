"""§384 补丁：把 `describeTip`（纯文案）从 `CardTip.tsx` 搬到 `view/cardTipText.ts`。

## 为什么

`choiceText.ts`（纯函数层，闸门 27 直接编译它）需要"种类 · 费用 · 稀有度"那一行。
如果它 import `run/overlays/CardTip.js`，tsc 就要把 **`.tsx`** 编成 ESM —— 而闸门那一趟
tsc 没有 jsx 支持，整条编译链直接崩（实测：`ERR_MODULE_NOT_FOUND ... CardTip.js`）。

正确的分层本来也该是这样：

* `view/cardTipText.ts` —— **纯文案**（`describeTip`），可被纯函数闸门穷尽断言；
* `run/overlays/CardTip.tsx` —— **渲染壳**（只负责 DOM 与事件），import 上面那一层。

于是"种类/费用/稀有度只在一处算"这条纪律仍然成立，而闸门能直接跑到它。
"""

import io

# ── 1. 新建纯文案层 ────────────────────────────────────────────────────────
TIP_TEXT = '''// 悬浮详情 / 选牌弹窗**共用的文案层**（§379 / §384）：纯函数，与 React 无关。
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
  return table[id] ?? table[id.replace(/\\++$/, "")] ?? null;
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
'''
io.open('web-next/src/view/cardTipText.ts', 'w', encoding='utf-8', newline='\n').write(TIP_TEXT)
print('view/cardTipText.ts 已建')

# ── 2. CardTip.tsx 改成薄壳 ────────────────────────────────────────────────
PATH = 'web-next/src/run/overlays/CardTip.tsx'
t = io.open(PATH, encoding='utf-8').read()

start = t.index('import { displayName, displayText } from "../../i18n/index.js";')
end = t.index('export interface CardTipProps {')
shell = '''// 悬浮详情（§379）：**一个组件，多处复用**（奖励屏 / 商店 / 选牌弹窗 / 牌组）。
//
// ## 玩家报的是什么
//
// "商店和奖励界面每个卡片没有跟随鼠标或者触摸的悬浮窗提示卡牌的具体内容，怎么选全靠盲猜。"
//
// ## 两条交互（鼠标 / 触摸各一条，不互相顶）
//
// * **鼠标**：`pointerenter` 就显示（固定面板，不做"跟着光标飘"的浮窗 ——
//   贴边时飘窗会被裁掉，而且它会盖住相邻的牌，反而更难选）。
// * **触摸**：`pointerdown` 显示。⚠️ 触摸上**不**阻止点击 —— 商店的"点一下买"必须保留，
//   所以触摸是"按住不放看详情、松手仍然买"。
//
// ## 分层（§384 修）
//
// 文案在 `view/cardTipText.ts`（**纯函数**，闸门直接编译它穷尽断言）；
// 本文件只是**渲染壳**（DOM + 事件）。所以"种类 · 费用 · 稀有度"只有一处算法。
//
// ## 为什么是固定面板而不是跟随光标的 tooltip
//
// 固定面板的位置可预测、可断言（`data-card-tip`），也不会被容器裁掉。
// ⚠️ 必须是 `position: fixed`（脱离文档流）：`sticky` 会撑动容器 ⇒ 卡牌重排 ⇒
// 鼠标下的牌换位置 ⇒ hover 换目标 ⇒ 面板换文字 ⇒ 死循环抖动（§381 实测）。

import { describeTip, type TipRequest } from "../../view/cardTipText.js";

export type { TipKind, TipRequest } from "../../view/cardTipText.js";

'''
t = t[:start] + shell + t[end:]
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('CardTip.tsx 变薄壳')

# ── 3. choiceText 改 import 纯层 ───────────────────────────────────────────
PATH2 = 'web-next/src/view/choiceText.ts'
t2 = io.open(PATH2, encoding='utf-8').read()
old = '''import { describeTip } from "../run/overlays/CardTip.js";'''
new = '''import { describeTip } from "./cardTipText.js";'''
assert t2.count(old) == 1
t2 = t2.replace(old, new)
t2 = t2.replace(
    '''// ⚠️ `.js` 同上：闸门 27 直接编这个文件。`describeTip` 与商店/奖励的悬浮面板**同一个来源**
// （种类 · 费用 · 稀有度只在一处算）。''',
    '''// ⚠️ `.js` 同上：闸门 27 直接编这个文件。`describeTip` 与商店/奖励的悬浮面板**同一个来源**
// （种类 · 费用 · 稀有度只在一处算）—— 注意它来自 `view/cardTipText.ts`（**纯文案**），
// 不是 `.tsx` 那个渲染壳：闸门那一趟 tsc 没有 jsx 支持。''',
)
io.open(PATH2, 'w', encoding='utf-8', newline='\n').write(t2)
print('choiceText 改指向纯层')
