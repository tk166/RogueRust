// 战斗奖励（`SC-04`，`pending == 4`）。
//
// ## 槽位不漂移（plan P3 的硬要求）
//
// 奖励候选的 `slot` 是**内核的位置**（`rd_run_reward_card_id_*` 的下标）。这里两条纪律：
//
// 1. 拿牌用 `slot`，**不用**"列表里的第几个"：拿掉一张之后内核会重排，列表下标会漂。
// 2. 拿完之后**立刻重读**（`RunStore.takeRewardCard` 内部 refresh）—— 界面永远画内核当前给的
//    那份候选，不自己 splice 数组。自己维护一份"拿走了哪些"的本地状态，就是漂移的源头。
//
// ⚠️ 实测：拿一张之后**候选表清空**（内核把整排牌都收走了，与 StS 一致）。所以界面不能
// 自己"标记拿过的那张"，只能重读；关屏仍然由 `skip_reward` 做（它的语义是"我领完了"，
// 药水/遗物还能继续拿）。这条是闸门 34 的断言之一。
//
// ## 交互
//
// * 金币/药水/遗物各一行，各自一个"拿"按钮（没有就是没给）；
// * 三张牌各自"拿"；
// * 底部一个"跳过 / 继续"，**永远可点** —— 玩家可能不想要任何一张牌（牌组越薄越好）。

import { displayName } from "../../i18n/index.js";

export interface RewardCard {
  readonly slot: number;
  readonly id: string;
  readonly title: string;
}

export interface RewardSceneProps {
  readonly gold: number;
  readonly cards: readonly RewardCard[];
  readonly potion: string;
  readonly relic: string;
  readonly deckSize: number;
  readonly onTakeCard: (slot: number) => void;
  readonly onTakePotion: () => void;
  readonly onTakeRelic: () => void;
  readonly onSkip: () => void;
}

export function RewardScene({
  gold,
  cards,
  potion,
  relic,
  deckSize,
  onTakeCard,
  onTakePotion,
  onTakeRelic,
  onSkip,
}: RewardSceneProps) {
  return (
    <section className="scene scene-reward" data-scene="SC-04">
      <header className="scene-head">
        <h2>战斗奖励</h2>
        <p className="scene-sub">
          牌组 {deckSize} 张{gold > 0 ? ` · 金币 +${gold}` : ""}
        </p>
      </header>

      <div className="reward-rows">
        {gold > 0 && (
          <div className="reward-row" data-reward-gold={gold}>
            <span className="reward-glyph" aria-hidden>
              ◈
            </span>
            <span className="reward-label">金币</span>
            <span className="reward-value">+{gold}</span>
            <span className="reward-action muted">自动收取</span>
          </div>
        )}

        {potion && (
          <div className="reward-row" data-reward-potion={potion}>
            <span className="reward-glyph" aria-hidden>
              ⚗
            </span>
            <span className="reward-label">药水</span>
            <span className="reward-value">{displayName("potions", potion)}</span>
            <button type="button" data-take-potion onClick={onTakePotion}>
              收下
            </button>
          </div>
        )}

        {relic && (
          <div className="reward-row" data-reward-relic={relic}>
            <span className="reward-glyph" aria-hidden>
              ✦
            </span>
            <span className="reward-label">遗物</span>
            <span className="reward-value">{displayName("relics", relic)}</span>
            <button type="button" data-take-relic onClick={onTakeRelic}>
              收下
            </button>
          </div>
        )}
      </div>

      <h3 className="reward-cards-head">
        选一张牌 <span className="muted">（可以不拿）</span>
      </h3>
      <div className="reward-cards" data-reward-card-count={cards.length}>
        {cards.map((card) => (
          <button
            key={card.slot}
            type="button"
            className="reward-card"
            data-reward-card={card.slot}
            data-reward-card-id={card.id}
            onClick={() => onTakeCard(card.slot)}
          >
            {/*
              ⚠️ 中文名**优先用 i18n**：内核的 `reward_card_title` 是 `CARD.NameKey`（英文
              `Spot Weakness`），直接显示会让中文界面里混进英文牌名。
            */}
            <span className="reward-card-title">{displayName("cards", card.id) || card.title}</span>
            <span className="reward-card-id muted">{card.id}</span>
          </button>
        ))}
        {cards.length === 0 && <p className="muted">这一场没有给牌。</p>}
      </div>

      <button type="button" className="primary" data-reward-skip onClick={onSkip}>
        领完了 · 继续
      </button>
    </section>
  );
}
