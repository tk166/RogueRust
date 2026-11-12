// 遗物欠账（`SC-11a` 改牌 / `SC-11b` 加牌）：**弹在原来那一屏之上**。
//
// ## 为什么它们是覆盖层而不是一屏
//
// 它们可以和奖励屏、宝箱屏**同时**存在（`rd_run_pickup_picks` 不走 `pending`，§274 的原文
// 就是这个理由）。做成"另一屏"会把底下的奖励屏顶掉，玩家领完遗物就找不到刚才的奖励了。
//
// 所以：`base` 仍然是原来那一屏（`MapScene`/`RewardScene`/…），这一层盖在上面，
// **关掉之后回到原来那一屏**（plan P4 明确要求"正确返回原场景"）。
//
// ## 交互
//
// * `SC-11a`（改牌）：点"选一张牌" → 进牌组选择器 → 选完欠账 -1；
// * `SC-11b`（加牌）：候选几张 + "跳过"（`orrery` 每次都可以跳过）+ `singing_bowl` 的"+2 上限"；
// * **不可关掉**：欠账必须还（内核会一直欠着），所以没有关闭按钮。

export interface PickupOverlayProps {
  /** `1` 移除 / `2` 升级 / `3` 改造 / `4` 改造并升级。 */
  readonly change: number;
  readonly picks: number;
  readonly add: number;
  readonly offers: readonly { slot: number; title: string }[];
  readonly onPickCard: () => void;
  readonly onAddCard: (slot: number) => void;
  readonly onSkipAdd: () => void;
  readonly onMaxHpInstead: () => void;
  readonly busy?: boolean;
}

const CHANGE_LABEL: Record<number, string> = {
  1: "移除一张牌",
  2: "升级一张牌",
  3: "改造一张牌",
  4: "改造并升级一张牌",
};

export function PickupOverlay({
  change,
  picks,
  add,
  offers,
  onPickCard,
  onAddCard,
  onSkipAdd,
  onMaxHpInstead,
  busy = false,
}: PickupOverlayProps) {
  const adding = add > 0;
  return (
    <div className="run-overlay" data-pickup={adding ? "add" : "change"} data-pickup-picks={picks} data-pickup-add={add}>
      <div className="run-overlay-card run-pickup">
        <h3>{adding ? "遗物：加一张牌" : "遗物：改一张牌"}</h3>
        <p className="muted">
          {adding ? `还要加 ${add} 张` : `还要改 ${picks} 张 · ${CHANGE_LABEL[change] ?? `未知（${change}）`}`}
        </p>

        {adding ? (
          <>
            <ul className="run-deck-list" data-pickup-offers={offers.length}>
              {offers.map((offer) => (
                <li key={offer.slot}>
                  <button
                    type="button"
                    className="deck-select-row"
                    data-pickup-add={offer.slot}
                    disabled={busy}
                    onClick={() => onAddCard(offer.slot)}
                  >
                    <span className="deck-select-name">
                      {offer.title || "（没有名字）"}
                    </span>
                  </button>
                </li>
              ))}
              {offers.length === 0 && <li className="muted">没有候选（内核没给）。</li>}
            </ul>
            <div className="run-pickup-actions">
              <button type="button" data-pickup-skip onClick={onSkipAdd} disabled={busy}>
                跳过这一次
              </button>
              <button type="button" data-pickup-maxhp onClick={onMaxHpInstead} disabled={busy}>
                换成生命上限 +2
              </button>
            </div>
          </>
        ) : (
          <button type="button" className="primary" data-pickup-pick onClick={onPickCard} disabled={busy}>
            选一张牌
          </button>
        )}

        <p className="muted">这件遗物的要求还没还完，所以这一层关不掉。</p>
      </div>
    </div>
  );
}
