// 塔底祝福（`SC-01`，`pending == 6`）：三个候选，选一个。
//
// ## 为什么这一屏值得一个真界面
//
// 它是**每一局的第一个选择**，也是"标题 → 地图"之间唯一的一屏。如果这一屏做成"还没实现，
// 点一下用默认动作通过"，玩家对整套 UI 的第一印象就是"这玩意儿半成品"。
//
// 数据全部来自内核：条数（`rd_run_start_offer_count`，§346 **不许写死 2**）、
// 收益/代价的**判别值**（`rd_run_start_gain/cost` + `_amount`）。这里只做"数字 → 人话"。

export interface Blessing {
  readonly slot: number;
  readonly id: string;
  readonly gain: number;
  readonly gainAmount: number;
  readonly cost: number;
  readonly costAmount: number;
}

export interface BlessingSceneProps {
  readonly blessings: readonly Blessing[];
  readonly onChoose: (slot: number) => void;
}

/**
 * 收益/代价的判别值（`run-layer.md` 的 `BlessingGain`/`BlessingCost` 编码）。
 *
 * ⚠️ `nothing` 是 **5**（不是 0）：0 在别处是"没有"，这里"没有代价"有专门的取值，
 * 所以不能拿 `cost === 0` 判"免费" —— 那会把**所有**祝福都显示成免费。
 */
export const BLESSING_EFFECT = {
  heal: 1,
  gold: 2,
  loseHealth: 3,
  maxHealth: 4,
  nothing: 5,
} as const;

/** 判别值 → 人话（`amount` 是数量）。 */
export function blessingEffectLabel(kind: number, amount: number): string {
  switch (kind) {
    case BLESSING_EFFECT.heal:
      return `回复 ${amount} 点生命`;
    case BLESSING_EFFECT.gold:
      return `获得 ${amount} 金币`;
    case BLESSING_EFFECT.loseHealth:
      return `失去 ${amount} 点生命`;
    case BLESSING_EFFECT.maxHealth:
      return `生命上限 +${amount}`;
    case BLESSING_EFFECT.nothing:
      return "无";
    default:
      return `未知效果 ${kind}（${amount}）`;
  }
}

/**
 * 祝福 id → 中文名 + "选完还要做什么"。
 *
 * ⚠️ 这 8 个 id 是**内核的闭集**（`state.rs` 的 Neow 列表），不是内容数据 —— 所以表放在这里
 * 而不是 i18n（i18n 是内容 id → 中文，内容里没有祝福）。**多一个 id 就多一行**：
 * 兜底会显示原始 id，一眼能看出"内核加了新的而 UI 没跟上"。
 *
 * 四个 `*_card` 的 gain/cost 都是 `Nothing`：它们的效果体现在**后续**（`blessing_needs`），
 * 所以标题必须自己说清楚，否则玩家看到的是"无 · 没有代价"。
 */
const BLESSING_TITLES: Record<string, { title: string; followUp?: string }> = {
  max_hp: { title: "生命上限 +8" },
  gold: { title: "100 金币" },
  heal: { title: "回复 25 点生命" },
  blood_money: { title: "150 金币" },
  remove_card: { title: "删掉一张牌", followUp: "选完还要挑一张牌" },
  upgrade_card: { title: "升级一张牌", followUp: "选完还要挑一张牌" },
  transform_card: { title: "变形一张牌", followUp: "选完还要挑一张牌" },
  three_cards: { title: "三张牌选一张", followUp: "选完还要挑一张牌" },
};

function blessingTitle(id: string): { title: string; followUp?: string } {
  const known = BLESSING_TITLES[id];
  if (known) return known;
  const dot = id.lastIndexOf(".");
  return { title: dot >= 0 ? id.slice(dot + 1) : id };
}

export function BlessingScene({ blessings, onChoose }: BlessingSceneProps) {
  return (
    <section className="scene scene-blessing" data-scene="SC-01">
      <header className="scene-head">
        <h2>塔底祝福</h2>
        <p className="scene-sub">选一个带上路（每一项都有代价）</p>
      </header>
      <div className="blessing-list" data-blessing-count={blessings.length}>
        {blessings.map((blessing) => {
          const free = blessing.cost === BLESSING_EFFECT.nothing;
          const { title, followUp } = blessingTitle(blessing.id);
          return (
            <button
              key={blessing.slot}
              type="button"
              className="blessing"
              data-blessing={blessing.slot}
              data-blessing-id={blessing.id}
              onClick={() => onChoose(blessing.slot)}
            >
              <span className="blessing-title">{title}</span>
              {followUp && <span className="blessing-follow">{followUp}</span>}
              <span className="blessing-gain">
                {blessingEffectLabel(blessing.gain, blessing.gainAmount)}
              </span>
              <span className={free ? "blessing-cost is-free" : "blessing-cost"}>
                {free ? "没有代价" : `代价：${blessingEffectLabel(blessing.cost, blessing.costAmount)}`}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
