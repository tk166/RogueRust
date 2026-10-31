"""§161.5 rd-core: `ChoiceSource::Offered` -- three candidates, only one of which ever exists.

The design point worth stating: the candidates are **definitions**, not card instances.
Pre-creating three cards (in a set-aside pile, say) would put three cards that the reference never
had into `card_num=` and into three `hand=`/`aside=` lines -- i.e. it would move the fingerprint for
a card that is not in the game yet. Definitions cost nothing and disappear on their own.

So `resolve_choice` **creates** the one card that was picked. The core can mint instance ids (the
counter is a `CombatState` field and `exec.rs` has been doing it since §88); this section moves that
minting down into `state.rs` so there is exactly one place that turns a number into `card_%06d`.
"""
import io

PATH = "kernel/rd-core/src/state.rs"


def sub(text, old, new):
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)


def main():
    text = io.open(PATH, encoding="utf-8").read()

    # ---- 1. ChoiceSource gains Offered, and `zone()` becomes Option --------------------------
    text = sub(
        text,
        """/// ⚠️ 只有**真的被用到**的两种。`Offered`（从卡池抽三张候选，Attack / Skill / Power /
/// Colorless Potion 要的那一种）故意还不在：它需要「候选不是牌堆的一部分」这个第二形态的
/// 载荷，而先冻一个没有消费者的形态，正是本模块反复躲开的那种「提前把语义推给未来」。
/// 加它的时候，`choice_legal` 的 `match` 会逼着接的人把两条路都想清楚。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u8)]
pub enum ChoiceSource {
    /// 手牌（Elixir「消耗任意张手牌」/ Gambler's Brew「弃任意张，抽同样多」）。
    #[default]
    Hand,
    /// 弃牌堆（Liquid Memories「把弃牌堆里一张拿回手牌」）。
    DiscardPile,
}""",
        """/// ⚠️ `Offered` 是**第二个形态**：它的候选不是牌堆的一部分，而是三条**卡定义**（§161.5）。
/// 它不能落到任何一个 [`CardZone`] 上 —— 这也是 [`Self::zone`] 返回 `Option` 的原因：
/// `match` 会逼着每个读者回答「候选从哪来」，而不是把它当成一个空牌区。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u8)]
pub enum ChoiceSource {
    /// 手牌（Elixir「消耗任意张手牌」/ Gambler's Brew「弃任意张，抽同样多」）。
    #[default]
    Hand,
    /// 弃牌堆（Liquid Memories「把弃牌堆里一张拿回手牌」）。
    DiscardPile,
    /// **三条候选**（Attack / Skill Potion「从三张随机 X 牌里选一张加进手牌」）。
    Offered,
}""",
    )

    text = sub(
        text,
        """impl ChoiceSource {
    /// 这个来源对应哪个牌区。
    ///
    /// `const` 且有穷尽 `match`：加一种来源时，这里编译不过，而不是掉进一个默认分支。
    #[must_use]
    pub const fn zone(self) -> CardZone {
        match self {
            Self::Hand => CardZone::Hand,
            Self::DiscardPile => CardZone::DiscardPile,
        }
    }
}""",
        """impl ChoiceSource {
    /// 这个来源对应的牌区；`None` = 它的候选**不在任何一个牌区里**（[`Self::Offered`]）。
    ///
    /// `const` 且有穷尽 `match`：加一种来源时，这里编译不过，而不是掉进一个默认分支。
    #[must_use]
    pub const fn zone(self) -> Option<CardZone> {
        match self {
            Self::Hand => Some(CardZone::Hand),
            Self::DiscardPile => Some(CardZone::DiscardPile),
            Self::Offered => None,
        }
    }
}""",
    )

    # ---- 2. the offered payload --------------------------------------------------------------
    text = sub(
        text,
        """/// 一次待决的选牌：玩家（或任何战斗员）**必须**先回答它，才能继续（§161.3）。""",
        """/// 一次候选最多几张（StS 的三张；留到 8 是因为 Attack/Skill/Power 三瓶都要同一个数，
/// 而"三"写在三处的常量迟早只有一个被改）。
pub const MAX_CHOICE_OFFERED: usize = 8;

/// 一次待决的选牌：玩家（或任何战斗员）**必须**先回答它，才能继续（§161.3）。""",
    )

    text = sub(
        text,
        """    /// 选完之后做什么。
    pub then: ChoiceThen,
}""",
        """    /// 选完之后做什么。
    pub then: ChoiceThen,
    /// [`ChoiceSource::Offered`] 的候选：**卡定义**，不是实例（§161.5）。
    ///
    /// 其余来源必须留空；`begin_choice` 两边都校验，因为「候选」和「来源」不一致，等于问一个
    /// 玩家答不出来的问题。
    pub offered: Bounded<CardDefinitionId, MAX_CHOICE_OFFERED>,
}""",
    )

    # ---- 3. the answer enum -------------------------------------------------------------------
    text = sub(
        text,
        """/// [`CombatState::resolve_choice`] 做完了什么。""",
        """/// 一个选牌问句的**答案**。
///
/// 两种形态是因为两种来源问的是不同的问题：牌区来源问"这些实例里选哪些"，候选来源问
/// "这三张里要哪个下标"。合成一个类型就会逼出一个"另一种随便填什么"的字段。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ChoiceAnswer<'a> {
    /// 从牌区里选中的**实例**（[`ChoiceSource::Hand`] / [`ChoiceSource::DiscardPile`]）。
    Instances(&'a [CardInstanceId]),
    /// 从候选里选中的**下标**（[`ChoiceSource::Offered`]），升序、不重复。
    Offered(&'a [usize]),
}

/// [`CombatState::resolve_choice`] 做完了什么。""",
    )

    # ---- 4. the error --------------------------------------------------------------------------
    text = sub(
        text,
        """    /// 给了一个 `cost_delta`，但这个问句的 `then` 根本没有价格（只有 [`ChoiceThen::ToHand`] 有）。""",
        """    /// 答案的形状和问句的来源不匹配（`Instances` 回答 `Offered`，或反过来）。
    WrongAnswer,
    /// 给了一个 `cost_delta`，但这个问句的 `then` 根本没有价格（只有 [`ChoiceThen::ToHand`] 有）。""",
    )

    text = sub(
        text,
        """            Self::DeltaNotApplicable => {
                f.write_str("a cost delta was given to a choice whose then has no price")
            }""",
        """            Self::WrongAnswer => f.write_str("the answer does not match the question's source"),
            Self::DeltaNotApplicable => {
                f.write_str("a cost delta was given to a choice whose then has no price")
            }""",
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("state.rs: Offered + ChoiceAnswer")


if __name__ == "__main__":
    main()
