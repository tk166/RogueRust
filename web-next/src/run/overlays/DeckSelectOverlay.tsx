// 牌组选择器（`DeckSelectOverlay`）：**一处实现，六处复用**。
//
// 六处会用到它：祝福选牌（`pending 7`）、事件选牌（`pending 8`）、锻造、抽烟斗、付费删牌、
// 遗物欠账改牌（`pickup_change`）。它们的共同点只有一句：**给一个牌组下标**。
// 所以这里只做"列牌 + 选一张 + 把下标交出去"，动作由调用方决定。
//
// ## 交互设计
//
// 1. **牌组下标就是身份**（plan 明确要求"保留 deckIndex"）：列表顺序 == `rd_run_deck_*` 的下标，
//    绝不排序。想帮玩家找牌就加**过滤框**，而不是重排 —— 重排之后"第 3 张"是哪个就说不清了。
// 2. **不可选的牌显示原因**（升级过的牌不能再升级）：画成可点再让内核拒绝，就是死按钮。
// 3. **一次点击即提交**：选中就是答案（StS 的牌组选择器也是这么做的）。浏览模式（`browse`）
//    例外 —— 那时没有动作，点了只是展开详情。
// 4. **Esc 关闭**：只有在"可以放弃"的地方才给关闭按钮（锻造/删牌可以放弃，`pending 8` 不行）。

import { useMemo, useState } from "react";
import { displayName } from "../../i18n/index.js";
import { deckPickAllowed, deckPickCopy, type DeckPickPurpose } from "../models.js";

export interface DeckSelectOverlayProps {
  readonly purpose: DeckPickPurpose;
  /** 牌组定义 id（`strike` / `bash+` …），**顺序就是内核下标**。 */
  readonly deck: readonly string[];
  /** 可选：内核给的显示名（与 id 同序）。没有就退回 i18n。 */
  readonly titles?: readonly string[];
  readonly price?: number;
  /** 选中的牌组下标。 */
  readonly onPick: (index: number) => void;
  /** 给了才显示关闭按钮（可放弃的场合）。 */
  readonly onClose?: () => void;
  readonly busy?: boolean;
}

export function DeckSelectOverlay({
  purpose,
  deck,
  titles,
  price = 0,
  onPick,
  onClose,
  busy = false,
}: DeckSelectOverlayProps) {
  const [filter, setFilter] = useState("");
  const copy = deckPickCopy(purpose, price);

  // ⚠️ 过滤**不改变下标**：这里留下的是 `{ index, id }`，`index` 始终是内核下标。
  const rows = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return deck
      .map((id, index) => ({
        index,
        id,
        name: titles?.[index] || displayName("cards", id),
        allowed: deckPickAllowed(purpose, id),
      }))
      .filter((row) => {
        if (needle === "") return true;
        return row.name.toLowerCase().includes(needle) || row.id.toLowerCase().includes(needle);
      });
  }, [deck, titles, purpose, filter]);

  return (
    <div className="run-overlay" data-deck-select={purpose}>
      <div className="run-overlay-card run-deck-select">
        <header className="deck-select-head">
          <h3>{copy.title}</h3>
          <p className="muted">{copy.hint}</p>
        </header>

        <input
          type="search"
          className="deck-select-filter"
          data-deck-filter
          placeholder="按名字过滤（不改变下标）"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />

        <ul className="deck-select-list" data-deck-count={deck.length}>
          {rows.map((row) => (
            <li key={row.index}>
              <button
                type="button"
                className={row.allowed ? "deck-select-row" : "deck-select-row is-disabled"}
                data-deck-pick={row.index}
                data-deck-pick-id={row.id}
                data-deck-allowed={row.allowed ? "1" : "0"}
                disabled={!row.allowed || busy || !copy.actionable}
                title={row.allowed ? undefined : "这张牌已经升级过了"}
                onClick={() => onPick(row.index)}
              >
                <span className="deck-select-index muted">{row.index + 1}</span>
                <span className="deck-select-name">{row.name}</span>
                <span className="deck-select-id muted">{row.id}</span>
                {!row.allowed && <span className="deck-select-why">已升级</span>}
              </button>
            </li>
          ))}
          {rows.length === 0 && <li className="muted">没有匹配的牌</li>}
        </ul>

        {onClose && (
          <button type="button" data-deck-close onClick={onClose} disabled={busy}>
            取消
          </button>
        )}
      </div>
    </div>
  );
}
