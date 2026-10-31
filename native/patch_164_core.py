"""§161.4 rd-core: the per-copy price.

Three pieces, and only three -- the **cost stage that reads it already exists**
(`CostStage::CardInstance`, priority 1100, ported from `CardInstanceCostModifier`):

  1. `CARD_COST_DELTA_COUNTER` moves to `state.rs` and becomes public. It was a private `&str` in
     `play.rs`; the writer now lives in `state.rs`, and two literals would drift (the same
     one-definition-two-readers rule `X_COST_TAG` already follows).
  2. `ChoiceThen::ToHand` -- the third consumer of a `PendingChoice` (Liquid Memories).
  3. `resolve_choice` takes the delta and writes it; a non-zero delta on a `then` that has no price
     is a **caller error**, refused loudly.
"""
import io

PATH = "kernel/rd-core/src/state.rs"


def sub(text, old, new):
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)


def main():
    text = io.open(PATH, encoding="utf-8").read()

    # ---- 1. the counter id, defined once -----------------------------------------------------
    text = sub(
        text,
        """/// 一次待决的选牌：玩家（或任何战斗员）**必须**先回答它，才能继续（§161.3）。""",
        """/// 一张牌**自己的**价格：`standard.card_cost_delta`（`StandardCombatIds.cs:93`）。
///
/// 参考的模型（`Cards/CardInstanceCostModifier.cs:13-34`）：这是一个**每张牌副本**的 mark
/// counter，加到这张牌的**每一条**资源代价上、**钳到 0**、并且**在出牌付款之后清零**
/// （`Cards/CardPlay.cs:176-183`：*"A per-copy price is a promise to ONE card and is kept once"*）。
///
/// 它为什么不能用一个状态表达：状态是**按持有者**给每张牌定价的（"你的技能牌便宜 1"），而
/// "你刚拿回来的那张牌这次免费"是一个**只属于那一张牌**的承诺，得跟着它穿过弃牌堆与手牌。
///
/// ⚠️ **与 StS 的差别（写明了的不对称）**：StS 的 "costs 0 **this turn**" 在回合结束时过期；
/// 参考引擎的模型是"被出牌消费"，所以一张没被打出的折扣牌会一直带着它。我们照参考实现 ——
/// 给回合结束加一次清除等于发明一条参考没有的规则（§159.3 的教训是"不要实现一个关于不存在的
/// 事件的分数"），而这条差别由 `the_per_copy_price_is_consumed_by_the_play` 钉住。
pub const CARD_COST_DELTA_COUNTER: &str = "standard.card_cost_delta";

/// 一次待决的选牌：玩家（或任何战斗员）**必须**先回答它，才能继续（§161.3）。""",
    )

    # ---- 2. the ToHand variant ---------------------------------------------------------------
    text = sub(
        text,
        """    /// 把选中的牌**丢弃**，然后**抽同样多张**（Gambler's Brew）。
    DiscardThenDraw,
}""",
        """    /// 把选中的牌**丢弃**，然后**抽同样多张**（Gambler's Brew）。
    DiscardThenDraw,
    /// 把选中的牌**拿进手牌**，并给它一个每副本价格（§161.4，Liquid Memories）。
    ///
    /// 价格由 `resolve_choice` 的 `cost_delta` 参数给出，因为"免费"是**负数张牌代价**，
    /// 而那个数字只有知道内容的人算得出来（`CombatState` 里没有内容）。
    ToHand,
}""",
    )

    text = sub(
        text,
        """    pub const fn destination(self) -> CardZone {
        match self {
            Self::Exhaust => CardZone::ExhaustPile,
            Self::DiscardThenDraw => CardZone::DiscardPile,
        }
    }""",
        """    pub const fn destination(self) -> CardZone {
        match self {
            Self::Exhaust => CardZone::ExhaustPile,
            Self::DiscardThenDraw => CardZone::DiscardPile,
            Self::ToHand => CardZone::Hand,
        }
    }""",
    )

    # ---- 3. the error variant ----------------------------------------------------------------
    text = sub(
        text,
        """    /// 同一张牌被选了两次。
    Duplicate,""",
        """    /// 同一张牌被选了两次。
    Duplicate,
    /// 给了一个 `cost_delta`，但这个问句的 `then` 根本没有价格（只有 [`ChoiceThen::ToHand`] 有）。
    ///
    /// **调用方的错，不是玩家的错**：静默忽略一个折扣等于"这张牌本来就要钱，而且玩家以为它免费"。
    DeltaNotApplicable,""",
    )

    text = sub(
        text,
        """            Self::Duplicate => f.write_str("the same card was picked twice"),""",
        """            Self::Duplicate => f.write_str("the same card was picked twice"),
            Self::DeltaNotApplicable => {
                f.write_str("a cost delta was given to a choice whose then has no price")
            }""",
    )

    # ---- 4. resolve_choice ------------------------------------------------------------------
    text = sub(
        text,
        """    /// 结算待决的选牌：把选中的牌按 [`ChoiceThen`] 送走，然后清掉问句。
    ///
    /// **全部校验在动手之前**（见本节头第 1 条）。成功之后 [`Self::pending_choice`] 是 `None`。
    pub fn resolve_choice(&mut self, picks: &[CardInstanceId]) -> Result<ChoiceDone, ChoiceError> {
        let choice = self.choice.ok_or(ChoiceError::NotPending)?;
        let picked = picks.len();""",
        """    /// 结算待决的选牌：把选中的牌按 [`ChoiceThen`] 送走，然后清掉问句。
    ///
    /// `cost_delta` 是**每副本价格**（[`CARD_COST_DELTA_COUNTER`]），只有
    /// [`ChoiceThen::ToHand`] 用得上；其余 `then` 必须传 `0`，否则
    /// [`ChoiceError::DeltaNotApplicable`] —— 静默忽略一个折扣会让"它免费"变成一句谎。
    ///
    /// **全部校验在动手之前**（见本节头第 1 条）。成功之后 [`Self::pending_choice`] 是 `None`。
    pub fn resolve_choice(
        &mut self,
        picks: &[CardInstanceId],
        cost_delta: i32,
    ) -> Result<ChoiceDone, ChoiceError> {
        let choice = self.choice.ok_or(ChoiceError::NotPending)?;
        if cost_delta != 0 && choice.then != ChoiceThen::ToHand {
            return Err(ChoiceError::DeltaNotApplicable);
        }
        let picked = picks.len();""",
    )

    text = sub(
        text,
        """        // ---- 到这里为止一个字节都没改。----
        for &slot in &slots[..picked] {
            self.move_card(&choice.chooser, source, destination, slot, ZonePlacement::Bottom)?;
        }
        self.choice = None;""",
        """        // ---- 到这里为止一个字节都没改。----
        for &slot in &slots[..picked] {
            self.move_card(&choice.chooser, source, destination, slot, ZonePlacement::Bottom)?;
            // §161.4: the per-copy price rides **on the card**, so it travels with it through the
            // hand and the discard pile -- and `play.rs` zeroes it once the play is paid for.
            if choice.then == ChoiceThen::ToHand && cost_delta != 0 {
                let Ok(key) = CounterId::new(CARD_COST_DELTA_COUNTER) else {
                    return Err(ChoiceError::NotInSource);
                };
                if let Some(card) = self.cards.as_mut_slice().get_mut(slot.index()) {
                    card.set_mark_counter(key, cost_delta)?;
                }
            }
        }
        self.choice = None;""",
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("state.rs: ToHand + cost_delta + the counter id")


if __name__ == "__main__":
    main()
