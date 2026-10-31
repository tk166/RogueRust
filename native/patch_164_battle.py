"""battle.rs: a `Step` that names the **instance**, not the definition.

The reference's scenario script is text, so `HeroPlaysCard` means "the first card in hand with this
definition" (`ScenarioRunner.cs:109-111`) -- and that is kept, because the four diff harnesses drive
it. But the **page** clicks a hand *position*: with two copies of one definition, "play a strike"
plays the first one, so §161.4's discounted copy would be unreachable whenever a plain copy sits in
front of it. A dead button, in the exact sense the project's §150/§151 keep finding.

`Step::HeroPlaysInstance` is additive: `HeroPlays` keeps its meaning, so no diff baseline moves.
"""
import io

PATH = "kernel/rd-core/src/battle.rs"


def sub(text, old, new):
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)


def main():
    text = io.open(PATH, encoding="utf-8").read()

    # ---- the step variant ------------------------------------------------------------------
    text = sub(
        text,
        """    /// `HeroPlaysCard`：英雄打出**手里第一张**该定义的卡。
    HeroPlays {
        /// 卡定义 id。
        card: &'a str,
        /// 目标（`None` = 没有目标，不是错误）。
        target: Option<&'a str>,
    },""",
        """    /// `HeroPlaysCard`：英雄打出**手里第一张**该定义的卡。
    ///
    /// ⚠️ 这是**参考的形状**，不是"该怎么打牌"：它是场景脚本的一步，脚本是文本、没有实例号，
    /// 所以只能按定义点名（`ScenarioRunner.cs:109-111`）。四条对拍流水线驱动的就是它，改语义会
    /// 移动基线 ⇒ 它的含义**冻着**。
    HeroPlays {
        /// 卡定义 id。
        card: &'a str,
        /// 目标（`None` = 没有目标，不是错误）。
        target: Option<&'a str>,
    },
    /// **按实例**打牌（本内核自己的扩展，§161.4）。
    ///
    /// 页面是**按手牌位置**点的，而按定义点名时"两份同定义副本"不可区分：如果一张普通
    /// `strike` 排在前面，玩家永远打不出后面那张带每副本价格的 `strike` —— 一个点了没反应的
    /// 按钮。§161.3 之前副本之间没有可观察的差别，所以这条一直没露出来；每副本价格是第一个
    /// 让"哪一张"变得有意义的东西。
    HeroPlaysInstance {
        /// 卡**实例** id。
        card: CardInstanceId,
        /// 目标（`None` = 没有目标，不是错误）。
        target: Option<&'a str>,
    },""",
    )

    # ---- Play learns the instance ------------------------------------------------------------
    text = sub(
        text,
        """#[derive(Clone, Copy, Debug)]
struct Play<'a> {
    card: &'a str,
    target: Option<&'a str>,
}""",
        """#[derive(Clone, Copy, Debug)]
struct Play<'a> {
    /// 按**定义**点名（参考的形状，见 [`Step::HeroPlays`]）。
    card: &'a str,
    /// 打**这一份副本**（[`Step::HeroPlaysInstance`]）；`Some` 时 `card` 被忽略。
    ///
    /// 不并进 `card` 是因为两者的**查法不同**：定义要"找第一张"，实例要"找那一张"，
    /// 而后者找不到时必须报 `CardNotInHand`，不能悄悄退回按定义找。
    instance: Option<CardInstanceId>,
    target: Option<&'a str>,
}""",
    )

    # ---- hero_plays: honour the instance -----------------------------------------------------
    text = sub(
        text,
        """    let Play { card, target } = play;""",
        """    let Play {
        card,
        instance,
        target,
    } = play;""",
    )

    text = sub(
        text,
        """    // `:109-111`：按**卡定义 id** 在手牌里找**第一张**。
    // ⚠️ 找不到 ≠ 定义不存在：这里只查手牌，不查内容注册表（参考也不查）。
    let Some(instance) = first_card_in_hand(state, hero, card) else {
        problems.push(Problem::CardNotInHand)?; // `:113-117`
        return Ok(context);
    };""",
        """    // `:109-111`：按**卡定义 id** 在手牌里找**第一张**。
    // ⚠️ 找不到 ≠ 定义不存在：这里只查手牌，不查内容注册表（参考也不查）。
    //
    // §161.4：`instance` 非空时改成"找**这一张**"。找不到同样报 `CardNotInHand` —— **绝不**退回
    // 按定义找：那会把"这个位置已经空了"变成"打了别的一张牌"，正是死按钮的另一种形状。
    let instance = match instance {
        Some(id) => {
            let in_hand = state
                .card_zones(hero)
                .map(|zones| {
                    zones
                        .slots(CardZone::Hand)
                        .iter()
                        .any(|raw| state.card(CardSlot::from_index(*raw)).map(|c| c.id == id) == Some(true))
                })
                .unwrap_or(false);
            if in_hand {
                Some(id)
            } else {
                None
            }
        }
        None => first_card_in_hand(state, hero, card),
    };
    let Some(instance) = instance else {
        problems.push(Problem::CardNotInHand)?; // `:113-117`
        return Ok(context);
    };""",
    )

    # ---- the dispatch ------------------------------------------------------------------------
    text = sub(
        text,
        """        Step::HeroPlays { card, target } => hero_plays(
            state,
            content,
            config,
            Play { card, target },
            host,
            hero,
            problems,
        ),""",
        """        Step::HeroPlays { card, target } => hero_plays(
            state,
            content,
            config,
            Play {
                card,
                instance: None,
                target,
            },
            host,
            hero,
            problems,
        ),
        Step::HeroPlaysInstance { card, target } => hero_plays(
            state,
            content,
            config,
            Play {
                card: "",
                instance: Some(card),
                target,
            },
            host,
            hero,
            problems,
        ),""",
    )

    # ---- the one test that builds a Play by hand ---------------------------------------------
    text = sub(
        text,
        """            Play {
                card: "defend",
                target: None,
            },""",
        """            Play {
                card: "defend",
                instance: None,
                target: None,
            },""",
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("battle.rs: HeroPlaysInstance")


if __name__ == "__main__":
    main()
