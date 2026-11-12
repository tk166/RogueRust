// 牌堆浏览（抽牌堆 / 弃牌堆 / 消耗堆）：战斗中的只读面板。
//
// ## 为什么抽牌堆**不显示顺序**
//
// 内核给了 `rd_env_pile_card_id_*` 的下标顺序，但抽牌堆的顺序是**内部信息**（StS 里玩家
// 只能看到"里面有哪些牌"，看不到下一张）。所以这里：
//   * 弃牌堆 / 消耗堆：按内核顺序列（那是玩家的历史，本来就可见）；
//   * 抽牌堆：**按名字排序后**列出，只显示"有什么、几张"。
//
// 这条是**规则**而不是实现细节 —— 把抽牌堆按内核顺序画出来等于给玩家一个外挂。
//
// ## 交互
//
// 三个标签页切换；点一张牌看详情（标题 + id）；Esc / 关闭按钮收起。

import { useMemo, useState } from "react";
import { displayName } from "../../i18n/index.js";

export interface PileCard {
  readonly id: string;
  readonly title: string;
}

export interface PileOverlayProps {
  /** 0 抽牌堆 / 1 弃牌堆 / 2 消耗堆。 */
  readonly piles: readonly { zone: number; label: string; cards: readonly PileCard[] }[];
  readonly onClose: () => void;
}

export function PileOverlay({ piles, onClose }: PileOverlayProps) {
  const [zone, setZone] = useState(0);
  const active = piles.find((pile) => pile.zone === zone) ?? piles[0];

  const cards = useMemo(() => {
    if (!active) return [];
    const rows = active.cards.map((card) => ({
      id: card.id,
      name: displayName("cards", card.id) || card.title,
    }));
    // ⚠️ 抽牌堆（zone 0）**排序**：不泄露内部顺序（见文件头）。
    if (active.zone === 0) rows.sort((a, b) => a.name.localeCompare(b.name));
    return rows;
  }, [active]);

  return (
    <div className="run-overlay" data-pile-overlay={zone}>
      <div className="run-overlay-card run-pile">
        <header className="deck-select-head">
          <h3>牌堆</h3>
          <p className="muted">
            {active?.zone === 0 ? "抽牌堆只显示内容，不显示顺序" : "按内核顺序"}
          </p>
        </header>

        <div className="pile-tabs">
          {piles.map((pile) => (
            <button
              key={pile.zone}
              type="button"
              className={pile.zone === zone ? "pile-tab is-active" : "pile-tab"}
              data-pile-tab={pile.zone}
              data-pile-len={pile.cards.length}
              onClick={() => setZone(pile.zone)}
            >
              {pile.label} {pile.cards.length}
            </button>
          ))}
        </div>

        <ul className="deck-select-list" data-pile-cards={cards.length}>
          {cards.map((card, index) => (
            <li key={`${card.id}-${index}`} data-pile-card={card.id}>
              <span className="deck-select-name">{card.name}</span>
              <span className="deck-select-id muted">{card.id}</span>
            </li>
          ))}
          {cards.length === 0 && <li className="muted">空的。</li>}
        </ul>

        <button type="button" data-pile-close onClick={onClose}>
          关闭
        </button>
      </div>
    </div>
  );
}
