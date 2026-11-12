// 事件候选（`SC-10`，`pending == 9`）：事件摊开的几张牌，选一张。
//
// 与 `RewardScene` 的区别：奖励是"打完了给什么"，这里是"事件让你挑"。
// 两者都是"拿一张牌进牌组"，所以**拿牌一律用内核槽位**，不自己数列表下标。
//
// ⚠️ 候选数量由运行层说（`rd_run_event_offer_len`），不猜（`The Library` 是 20 选 1）。

import { displayName } from "../../i18n/index.js";

export interface EventOfferView {
  readonly slot: number;
  readonly id: string;
  readonly title: string;
}

export interface EventOfferSceneProps {
  readonly eventId: string;
  readonly offers: readonly EventOfferView[];
  readonly onTake: (slot: number) => void;
  readonly busy?: boolean;
}

export function EventOfferScene({ eventId, offers, onTake, busy = false }: EventOfferSceneProps) {
  return (
    <section className="scene scene-event-offer" data-scene="SC-10" data-event-id={eventId}>
      <header className="scene-head">
        <h2>挑一张</h2>
        <p className="scene-sub">共 {offers.length} 张候选</p>
      </header>

      <div className="reward-cards" data-event-offer-count={offers.length}>
        {offers.map((offer) => (
          <button
            key={offer.slot}
            type="button"
            className="reward-card"
            data-event-offer={offer.slot}
            data-event-offer-id={offer.id}
            disabled={busy}
            onClick={() => onTake(offer.slot)}
          >
            <span className="reward-card-title">{displayName("cards", offer.id) || offer.title}</span>
            <span className="reward-card-id muted">{offer.id}</span>
          </button>
        ))}
        {offers.length === 0 && <p className="muted">没有候选（内核没给）。</p>}
      </div>
    </section>
  );
}
