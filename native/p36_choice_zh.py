"""§384：选牌弹窗（武装 / 头击 / 灵液…）必须显示**中文名 + 二维卡面 + 悬浮详情**。

## 玩家报的

"战斗界面的武装、头击等牌需要选择已有手牌的时候，弹出窗口显示的是牌的英文名非常不直观，
可以改成和商店与奖励一样的二维绘图 + 映射表中文名 + 悬浮提示。"

## 根因

`ChoiceModal` 渲染的是 `option.title`，而那是内核的 `rd_env_pile_card_title_*`
—— 内容是 `CARD.NameKey`（**英文**：`Strike+` / `Defend`）。中文在 i18n 表里（`cards` 表），
商店/奖励屏早就改成 `displayName("cards", id)` 了，只有这一屏漏了。

## 修法

1. 标签抽成**纯函数** `choiceOptionLabel(option)`（放 `view/choiceText.ts`：它已经是
   "选牌这一屏的文案"那一层，且**闸门 27 直接编译它**）—— 于是"显示中文"这件事可以被穷尽断言，
   而不是靠在浏览器里抽到 `武装`；
2. `ChoiceModal` 用 `Badge`（二维卡面）+ 中文名 + 副标题（种类 · 费用 · 稀有度，与
   `CardTip.describeTip` **同一个来源**）+ `CardTip` 悬浮详情。

⚠️ 回退顺序是**显式**的：i18n 中文 → 内核 title（英文）→ 定义 id。第二层留着是因为
"没翻译"不该显示成空白；第三层是最后兜底（`insane_id` 之类）。
"""

import io

# ── 1. 纯函数：标签 ────────────────────────────────────────────────────────
PATH = 'web-next/src/view/choiceText.ts'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = '''export function choiceSentence(choice: PendingChoice): string {'''
assert t.count(ANCHOR) == 1

BLOCK = '''/**
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
  readonly title: string;
}): { name: string; subtitle: string } {
  const translated = displayName("cards", option.id);
  // `displayName` 查不到时**原样返回 id** ⇒ 那一层不算"翻译成功"。
  const name = translated !== option.id ? translated : option.title || option.id;
  const meta = describeTip({ kind: "card", id: option.id });
  return { name, subtitle: meta.subtitle };
}

export function choiceSentence(choice: PendingChoice): string {'''

t = t.replace(ANCHOR, BLOCK)

OLD_IMPORT = '''import { CHOICE_THEN, type PendingChoice } from "../wasm/snapshot.js";'''
NEW_IMPORT = '''import { CHOICE_THEN, type PendingChoice } from "../wasm/snapshot.js";
// ⚠️ `.js` 同上：闸门 27 直接编这个文件。`describeTip` 与商店/奖励的悬浮面板**同一个来源**
// （种类 · 费用 · 稀有度只在一处算）。
import { displayName } from "../i18n/index.js";
import { describeTip } from "../run/overlays/CardTip.js";'''
assert t.count(OLD_IMPORT) == 1
t = t.replace(OLD_IMPORT, NEW_IMPORT)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('choiceText: choiceOptionLabel')

# ── 2. ChoiceModal：徽章 + 中文名 + 悬浮详情 ────────────────────────────────
PATH2 = 'web-next/src/overlay/ChoiceModal.tsx'
t2 = io.open(PATH2, encoding='utf-8').read()

OLD2 = '''import type { PendingChoice } from "../wasm/snapshot";
import { choiceSentence } from "../view/choiceText";'''
NEW2 = '''import { useState } from "react";
import { Badge } from "../assets/Badge.js";
import { badgeLook } from "../assets/registry.js";
import type { PendingChoice } from "../wasm/snapshot";
import { choiceOptionLabel, choiceSentence } from "../view/choiceText";
import { CardTip, type TipRequest } from "../run/overlays/CardTip.js";'''
assert t2.count(OLD2) == 1
t2 = t2.replace(OLD2, NEW2)

OLD3 = '''export function ChoiceModal({ choice, onPick, onConfirm, onClear, refusal }: ChoiceModalProps) {
  const selectedCount = choice.options.filter((option) => option.selected).length;'''
NEW3 = '''export function ChoiceModal({ choice, onPick, onConfirm, onClear, refusal }: ChoiceModalProps) {
  // §384：指着哪一张（详情面板只有一个，所以一个状态就够）。
  const [tip, setTip] = useState<TipRequest | null>(null);
  const selectedCount = choice.options.filter((option) => option.selected).length;'''
assert t2.count(OLD3) == 1
t2 = t2.replace(OLD3, NEW3)

OLD4 = '''          {choice.options.map((option) => (
            <li key={option.index}>
              <button
                type="button"
                className={`choice-option${option.selected ? " is-selected" : ""}`}
                data-choice-option={option.index}
                data-selected={option.selected ? "1" : "0"}
                disabled={!option.selected && atMax}
                onClick={() => onPick(option.index, !option.selected)}
              >
                <span className="choice-option__mark">{option.selected ? "✓" : ""}</span>
                {/* 标题来自内核（当前是定义 id）；本地化与卡名一起处理。 */}
                <span className="choice-option__title">{option.title || option.id}</span>
              </button>
            </li>
          ))}'''
NEW4 = '''          {choice.options.map((option) => {
            // §384：中文名 + 种类/费用/稀有度。`option.title` 是内核的**英文** NameKey，
            // 只在"这一条没翻译"时当第二层回退（见 `choiceOptionLabel`）。
            const label = choiceOptionLabel(option);
            const request: TipRequest = { kind: "card", id: option.id };
            return (
              <li key={option.index}>
                <button
                  type="button"
                  className={`choice-option${option.selected ? " is-selected" : ""}`}
                  data-choice-option={option.index}
                  data-selected={option.selected ? "1" : "0"}
                  data-choice-card={option.id}
                  disabled={!option.selected && atMax}
                  // 指着/聚焦/触摸按下都亮详情（与商店、奖励屏同一套手势）。
                  onPointerEnter={() => setTip(request)}
                  onFocus={() => setTip(request)}
                  onPointerDown={() => setTip(request)}
                  onClick={() => onPick(option.index, !option.selected)}
                >
                  <span className="choice-option__mark">{option.selected ? "✓" : ""}</span>
                  {/* 二维卡面：与商店/奖励屏**同一个**素材注册表（两位字母 + 调色板）。 */}
                  <Badge
                    look={badgeLook("cards", option.id)}
                    size="sm"
                    upgraded={option.id.endsWith("+")}
                    title={option.id}
                  />
                  <span className="choice-option__title" data-choice-name>
                    {label.name}
                  </span>
                  {label.subtitle && (
                    <span className="choice-option__sub muted" data-choice-sub>
                      {label.subtitle}
                    </span>
                  )}
                </button>
              </li>
            );
          })}'''
assert t2.count(OLD4) == 1
t2 = t2.replace(OLD4, NEW4)

OLD5 = '''        <div className="choice-panel__actions">'''
NEW5 = '''        <CardTip request={tip} />

        <div className="choice-panel__actions">'''
assert t2.count(OLD5) == 1
t2 = t2.replace(OLD5, NEW5)
io.open(PATH2, 'w', encoding='utf-8', newline='\n').write(t2)
print('ChoiceModal: 徽章 + 中文名 + CardTip')
