// 待决选牌的弹窗（`rd_env_choice_*`）。
//
// ## 句子由 `(source, kind)` **两个数**决定
//
// `kind` 只有三个值（1 消耗 / 2 弃掉再抽 / 0 什么都不做），而"从弃牌堆拿一张"与"从三个候选里
// 选一张"是同一个 `then`。只看 `kind` 写句子就得猜，而且会猜错（§161.5 的老坑）。所以：
//
// | source | kind | 句子 |
// |---|---|---|
// | 1 牌堆 | 1 消耗 | 选择要**消耗**的牌 |
// | 1 牌堆 | 2 弃掉再抽 | 选择要**丢弃**的牌，然后抽牌 |
// | 2 候选 | 0/其它 | 选择**一张**牌加入手牌 |
//
// 数量写 `min == max ? "n 张" : "m–n 张"`。
//
// ## 为什么这个弹窗**关不掉**
//
// 问句是**模态**的：内核在等回答，动作表此时是空的（`compute_actions` 直接返回空表）。
// 允许关掉它等于把玩家扔进"什么都点不动"的界面。所以只有"确认"能离开这一屏。

import type { PendingChoice } from "../wasm/snapshot";
import { choiceSentence } from "../view/choiceText";

export interface ChoiceModalProps {
  readonly choice: PendingChoice;
  readonly onPick: (index: number, on: boolean) => void;
  readonly onConfirm: () => void;
  readonly onClear: () => void;
  /** 上一次确认被拒的原因（`-2` 数量不对），由 App 传进来。 */
  readonly refusal: string | null;
}

export function ChoiceModal({ choice, onPick, onConfirm, onClear, refusal }: ChoiceModalProps) {
  const selectedCount = choice.options.filter((option) => option.selected).length;
  const canConfirm = selectedCount >= choice.min;
  const multiple = choice.max > 1;

  return (
    <div className="choice-backdrop" data-choice>
      <div className="choice-panel">
        <h2 className="choice-panel__title">{choiceSentence(choice)}</h2>
        <p className="choice-panel__hint">
          已选 {selectedCount} / {choice.min === choice.max ? choice.min : `${choice.min}–${choice.max}`}
        </p>

        <ul className="choice-panel__options">
          {choice.options.map((option) => (
            <li key={option.index}>
              <button
                type="button"
                className={`choice-option${option.selected ? " is-selected" : ""}`}
                data-choice-option={option.index}
                data-selected={option.selected ? "1" : "0"}
                onClick={() => onPick(option.index, !option.selected)}
              >
                <span className="choice-option__mark">{option.selected ? "✓" : ""}</span>
                {/* 标题来自内核（当前是定义 id）；本地化与卡名一起处理。 */}
                <span className="choice-option__title">{option.title || option.id}</span>
              </button>
            </li>
          ))}
        </ul>

        {refusal && <p className="choice-panel__refusal" data-choice-refusal>{refusal}</p>}

        <div className="choice-panel__actions">
          {multiple && (
            <button type="button" className="choice-button" data-choice-clear onClick={onClear}>
              清空
            </button>
          )}
          <button
            type="button"
            className="choice-button is-primary"
            data-choice-confirm
            disabled={!canConfirm}
            onClick={onConfirm}
          >
            确认
          </button>
        </div>
      </div>
    </div>
  );
}
