// 选牌问句的**文案**：纯函数，与 React 无关（闸门 27 直接单测它）。
//
// 为什么值得单独一个文件：句子由 `(source, kind)` 两个数决定，而 `kind` 有 **10 种**。
// 这是最容易"少写一种就静默说错话"的地方 —— 放进 .tsx 就没法在纯函数闸门里穷举。

// ⚠️ 写成 `.js`：这个文件会被闸门 27 **直接编译成 ESM 跑**（不经打包器），
// Node 的 ESM 解析要求显式扩展名。TS 的 bundler 解析会把 `.js` 映回 `.ts`，Vite 也认。
import { CHOICE_THEN, type PendingChoice } from "../wasm/snapshot.js";

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

