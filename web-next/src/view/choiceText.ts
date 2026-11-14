// 选牌问句的**文案**：纯函数，与 React 无关（闸门 27 直接单测它）。
//
// 为什么值得单独一个文件：句子由 `(source, kind)` 两个数决定，而 `kind` 有 **10 种**。
// 这是最容易"少写一种就静默说错话"的地方 —— 放进 .tsx 就没法在纯函数闸门里穷举。

// ⚠️ 写成 `.js`：这个文件会被闸门 27 **直接编译成 ESM 跑**（不经打包器），
// Node 的 ESM 解析要求显式扩展名。TS 的 bundler 解析会把 `.js` 映回 `.ts`，Vite 也认。
import { CHOICE_THEN, type PendingChoice } from "../wasm/snapshot.js";
// ⚠️ `.js` 同上：闸门 27 直接编这个文件。`describeTip` 与商店/奖励的悬浮面板**同一个来源**
// （种类 · 费用 · 稀有度只在一处算）—— 注意它来自 `view/cardTipText.ts`（**纯文案**），
// 不是 `.tsx` 那个渲染壳：闸门那一趟 tsc 没有 jsx 支持。
import { displayName } from "../i18n/index.js";
import { describeTip } from "./cardTipText.js";

function countText(min: number, max: number): string {
  return min === max ? `${min} 张` : `${min}–${max} 张`;
}

/**
 * `kind` → 动词。**十种**，一种一句（内核为每种都给了新编号，就是为了让页面能写对句子）。
 * 未列出的编号（将来 ABI 加了新的）会落到"未定义的处理"而不是猜一句像话的 —— 猜出来的句子
 * 会静默承诺内核没答应的事。
 */
const THEN_VERB: Record<number, string> = {
  [CHOICE_THEN.exhaust]: "消耗",
  [CHOICE_THEN.discardThenDraw]: "丢弃，然后抽牌",
  [CHOICE_THEN.toHand]: "拿回手牌",
  [CHOICE_THEN.copy]: "复制",
  [CHOICE_THEN.upgrade]: "升级",
  [CHOICE_THEN.toDrawPileTop]: "放到抽牌堆顶",
  [CHOICE_THEN.toHandFree]: "拿进手牌（本回合免费）",
  [CHOICE_THEN.toDrawPileBottomFree]: "放到抽牌堆底（免费）",
  [CHOICE_THEN.playChosen]: "立刻打出",
  [CHOICE_THEN.toHandPrinted]: "按印刷价格拿进手牌",
};

/**
 * 句子：`source` 决定"从哪来"，`kind` 决定"之后怎么处理"。
 *
 * ⚠️ 只看 `kind` 不够：`kind` 说"拿进手牌"，而"从弃牌堆拿一张"与"从三个候选里选一张"是同一个
 * `then`。所以 `source === 2`（三选一）时"从候选里选"，`source === 1` 时"从牌堆里选"。
 */
/**
 * 选牌弹窗里**一行**的文案（§384）。
 *
 * ⚠️ 中文名来自 i18n 表（`cards`），**不是**内核的 `title` —— 后者是内容的 `NameKey`（英文
 * `Strike+`）。商店/奖励屏早就是这条规矩，只有选牌这一屏漏了，于是"武装"要选一张手牌时
 * 弹出来的是英文名。
 *
 * 回退顺序（每一层都显式）：i18n 中文 → 内核 title（英文）→ 定义 id。
 */
export function choiceOptionLabel(option: {
  readonly id: string;
  /**
   * 内核的显示名（内容的 `NameKey`，**英文**：`Strike+`）。
   *
   * ⚠️ **故意不用它**（§384）：玩家报的就是"弹窗里是英文名"。它的信息量与"美化 id"
   * 完全一样（`patient_guard` → `patient guard`），而英文名在一屏中文里最扎眼。
   * 参数留着是因为调用方手里本来就有它，删掉会让调用点再拼一次 —— 但不读。
   */
  readonly title: string;
}): { name: string; subtitle: string } {
  const translated = displayName("cards", option.id);
  // 回退顺序只有两层：i18n 中文 → **美化 id**（`patient_guard` → `patient guard`）。
  // 哪些牌会走到第二层由闸门 56 的**显式白名单**钉住（新增一张没翻译的就红）。
  const name =
    translated !== option.id
      ? translated
      : option.id.replace(/^standard\./, "").replace(/_/g, " ");
  const meta = describeTip({ kind: "card", id: option.id });
  return { name, subtitle: meta.subtitle };
}

export function choiceSentence(choice: PendingChoice): string {
  const want = countText(choice.min, choice.max);
  const verb = THEN_VERB[choice.kind];
  if (verb === undefined) {
    // 未知编号：说实话，不要编一句像话的（那会静默承诺内核没答应的事）。
    return `选择 ${want}（未知处理方式 ${choice.kind}）`;
  }
  if (choice.kind === CHOICE_THEN.copy && choice.copies > 0) {
    return `选择 ${want}，各复制 ${choice.copies} 份`;
  }
  if (choice.source === 2) {
    return `从候选里选择 ${want}：${verb}`;
  }
  return `从牌堆里选择 ${want}：${verb}`;
}

