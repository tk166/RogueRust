"""§161.4 play.rs: the price is kept **once**.

Two edits:

  1. the counter id is now `state::CARD_COST_DELTA_COUNTER` -- one definition, two readers (the
     same shape `X_COST_TAG` already uses).
  2. the delta is **zeroed after the play is paid for** (`Cards/CardPlay.cs:176-183`). Without this
     step a delta is a standing discount for the rest of the fight instead of a promise to one card,
     and nothing would notice: the cost reads 0 forever, which looks like a generous rule rather
     than a bug.
"""
import io

PATH = "kernel/rd-core/src/play.rs"


def sub(text, old, new):
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)


def main():
    text = io.open(PATH, encoding="utf-8").read()

    text = sub(
        text,
        """/// `StandardCombatIds.CardCostDeltaCounter`（`:131`）。
const CARD_COST_DELTA_COUNTER: &str = "standard.card_cost_delta";""",
        """/// `StandardCombatIds.CardCostDeltaCounter`（`:131`）。
///
/// §161.4: 定义搬到了 [`crate::state::CARD_COST_DELTA_COUNTER`] —— 写它的人（`resolve_choice`）
/// 现在在 `state.rs`，两处字面量迟早漂。这里只是**读同一处**，与 `X_COST_TAG` 同形。
const CARD_COST_DELTA_COUNTER: &str = crate::state::CARD_COST_DELTA_COUNTER;""",
    )

    text = sub(
        text,
        """    // `:125` EnsureCostsCanBePaid 已经在计划里做过；`:126` PayCosts。
    ensure_affordable(state, &plan.source, &plan.paid)?;
    pay_costs(state, &plan.source, &plan.paid)?;""",
        """    // `:125` EnsureCostsCanBePaid 已经在计划里做过；`:126` PayCosts。
    ensure_affordable(state, &plan.source, &plan.paid)?;
    pay_costs(state, &plan.source, &plan.paid)?;

    // `Cards/CardPlay.cs:176-183`：*"A per-copy price is a promise to ONE card and is kept once:
    // the play has been paid for by now, so the mark is spent here rather than lingering into the
    // next time this card is drawn."*
    //
    // §161.4。位置是**付款之后**，和参考逐行对齐：放在付款之前就会在 `ensure_affordable` 失败时
    // 把折扣吞掉（一张付不起的牌本来就没打出去，它的承诺还在）。
    //
    // ⚠️ 这一步**不**等于 StS 的 "this turn"：回合结束时我们不清这里（参考也没有这条规则）。
    // 一张没被打出的折扣牌会一直带着它 —— 写明了的偏差，由
    // `the_per_copy_price_is_consumed_by_the_play` 钉住。
    if let Some((_, slot)) = find_card_slot(state, &plan.source, &plan.instance) {
        if let Some(card) = state.card_mut(slot) {
            if mark_counter(card, CARD_COST_DELTA_COUNTER) != 0 {
                if let Ok(key) = CounterId::new(CARD_COST_DELTA_COUNTER) {
                    card.set_mark_counter(key, 0)?;
                }
            }
        }
    }""",
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("play.rs: the price is spent by the play")


if __name__ == "__main__":
    main()
