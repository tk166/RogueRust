"""§254 内核：`Wish` —— "选一张，**它立刻被打出**"。

## `Wish` 的原话（wiki）

> `Choose one: Gain 6 (8) Plated Armor, 3 (4) Strength, or 25 (30) Gold. Exhaust.`
> **Wish is the only card in the game that creates, then immediately plays a card. The three
> cards that Wish creates never enter your hand and cannot be added to the deck.**

三件事决定了实现形状：

1. **选项是"固定的三张定义"**，不是随机池 ⇒ 需要一个"给定候选表"的节点（`node.offerCards`）。
2. **选中那张要被打出**，而且它 `unplayable`（§253 的 `IgnoreUnplayable` 正是为此而来）。
3. **它从不进手牌**。而 `plan_play` 要求实例在**手牌**里（那是内核的受理前提，`Havoc` 也这么
   绕的）。所以"造 → 打"必须在**同一步**里完成，中间不留可观察的窗口：
   `resolve_offered` 把实例造进手牌，**同时**入队一条 `EffectRequest::PlayCard`；
   排空时先把它打出去，玩家看到的是"选项用掉了"，而不是"手牌里多了一张废牌"。

## 为什么出牌必须入队（`EffectRequest::PlayCard`）

`resolve_choice` 住在 `CombatState` 上，而那个结构**没有内容**（`plan_play` 要 `Content` 才能
算费用/tag）。所以"打出"这一步只能由**排空期**的执行器做 —— 那里有 `ctx.content`。
这与 §241 `Havoc` 的 `play_top_card_for` 是同一层，所以两者共用
`play::play_card_from_program`（§253），费用/事件/触发器/修饰器只有一份实现。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-core/src/state.rs'
EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
IR = 'D:/Vibe/sts-tui/kernel/rd-core/src/ir.rs'

STATE_PATCHES = [
    # 1) 新变体
    ('''    /// §250：**拿进手牌，并且这一份的价格就是 0**（`Discovery`）。''',
     '''    /// §254：**选中的那张被立刻打出**（`Wish`）。
    ///
    /// wiki 的原话是 "Wish is the only card in the game that creates, then immediately plays a
    /// card. The three cards that Wish creates **never enter your hand**"。所以这个变体的语义是
    /// "造 → 打"一步完成：`resolve_offered` 把实例造进手牌（`plan_play` 的受理前提），
    /// 同时入队一条 [`EffectRequest::PlayCard`]；排空时它被真的打出去，
    /// 于是玩家看不到"手牌里多了一张废牌"这个中间态。
    ///
    /// ⚠️ 它打出去的牌**一定**是 `unplayable` 的（`Become Almighty` / `Live Forever` /
    /// `Fame and Fortune` 都是）—— 入队的那条请求带 `ignore_unplayable = true`（§253）。
    PlayChosen,
    /// §250：**拿进手牌，并且这一份的价格就是 0**（`Discovery`）。'''),
    # 2) destination
    ('''            Self::ToHandFree => CardZone::Hand,''',
     '''            Self::ToHandFree => CardZone::Hand,
            // §254：先造进手牌（受理前提），紧接着入队"打出它"。
            Self::PlayChosen => CardZone::Hand,'''),
    # 3) resolve_offered：Free 那一支旁边加 PlayChosen
    ('''            // §250：候选来源的**免费**变体（`Discovery`）。这一支与 `resolve_from_pile` 是两条''',
     '''            // §254：`Wish` —— 造完立刻入队"打出它"。
            //
            // 顺序是语义：**先**入队再继续（同一轮循环里不会有别的请求插到它前面），
            // 而那条请求带 `ignore_unplayable`（这三张牌都是 unplayable）。
            // 目标给 `None`：Wish 的三个选项都不需要目标（它们打的是自己/运行层）。
            if choice.then == ChoiceThen::PlayChosen {
                self.enqueue_effect(
                    EffectRequest::PlayCard {
                        owner: choice.chooser,
                        card: self
                            .card(slot)
                            .map(|card| card.id)
                            .ok_or(ChoiceError::NotInSource)?,
                        target: None,
                        ignore_unplayable: true,
                    },
                    None,
                )
                .map_err(ChoiceError::Capacity)?;
            }
            // §250：候选来源的**免费**变体（`Discovery`）。这一支与 `resolve_from_pile` 是两条'''),
]

EXEC_PATCHES = [
    # request_target：新增变体 → None（它不是"针对某个战斗员"的请求）
    ('''        EffectRequest::DrawCards { .. }
        | EffectRequest::CreateCardInstance { .. }
        | EffectRequest::CreateRandomCard { .. }
        | EffectRequest::PlayTopCardOfDrawPile { .. }
        | EffectRequest::ShuffleDiscardIntoDraw { .. }
        | EffectRequest::MoveCardToZone { .. }
        | EffectRequest::EndTurn => None,
    }
}

/// 请求自带的出手方''',
     '''        EffectRequest::DrawCards { .. }
        | EffectRequest::CreateCardInstance { .. }
        | EffectRequest::CreateRandomCard { .. }
        | EffectRequest::PlayTopCardOfDrawPile { .. }
        | EffectRequest::ShuffleDiscardIntoDraw { .. }
        | EffectRequest::MoveCardToZone { .. }
        // §254：`PlayCard` 不针对战斗员（它的 `target` 是"给这张牌指定的出牌目标"，
        // 与"这条请求针对谁"不是一回事）—— 所以不进那张存在性检查表。
        | EffectRequest::PlayCard { .. }
        | EffectRequest::EndTurn => None,
    }
}

/// 请求自带的出手方'''),
    # resolve_effect 的 ctx.event_target 表
    ('''            EffectRequest::DrawCards { .. }
            | EffectRequest::CreateCardInstance { .. }
            | EffectRequest::CreateRandomCard { .. }
            | EffectRequest::PlayTopCardOfDrawPile { .. }
            | EffectRequest::ShuffleDiscardIntoDraw { .. }
            | EffectRequest::MoveCardToZone { .. }
            | EffectRequest::EndTurn => None,''',
     '''            EffectRequest::DrawCards { .. }
            | EffectRequest::CreateCardInstance { .. }
            | EffectRequest::CreateRandomCard { .. }
            | EffectRequest::PlayTopCardOfDrawPile { .. }
            | EffectRequest::ShuffleDiscardIntoDraw { .. }
            | EffectRequest::MoveCardToZone { .. }
            // §254：见 `request_target` 的同一条注释。
            | EffectRequest::PlayCard { .. }
            | EffectRequest::EndTurn => None,'''),
    # 实体分派
    ('''        EffectRequest::PlayTopCardOfDrawPile { owner } => play_top_card_for(ctx, &owner),''',
     '''        EffectRequest::PlayTopCardOfDrawPile { owner } => play_top_card_for(ctx, &owner),
        // §254：`Wish` 的那张牌 —— 与 `Havoc` 共用 `play_card_from_program`（§253）。
        EffectRequest::PlayCard {
            owner,
            card,
            target,
            ignore_unplayable,
        } => {
            let Some(content) = ctx.content else {
                return Err(ExecError::Ir(IrError::Missing("content")));
            };
            let played = crate::play::play_card_from_program(
                ctx.state,
                content,
                &owner,
                &card,
                target,
                ignore_unplayable,
            )?;
            // 参考对"打不出去"是 no-op（§253 的六种）；这里也一样 —— 但**必须**让那张牌留在
            // 原处而不是凭空消失。`play_card_from_program` 的 no-op 不改状态，所以什么都不用做。
            let _ = played;
            Ok(())
        }'''),
]

IR_PATCHES = [
    ('''    /// §253：**由别的牌把一张牌打出来**（`Wish` 的三个选项；参考的 `node.playCard`）。''',
     '''    /// §254：**给一张固定的候选表，选中的那张被立刻打出**（`Wish`）。
    ///
    /// 字段：`{Definitions, Min?, Max?, Then?}`。`Definitions` 是**卡定义 id 的表**
    /// （`F_STRLIST`），按给定顺序成为三个候选。
    ///
    /// 与 `node.offerRandomCards`（`Discovery`）的分工：那个从**随机池**里抽，"抽到什么"是运行期
    /// 的事；这个的候选是**内容写死的** —— `Wish` 的三个选项永远是那三张。合并成一个节点会让
    /// "候选是固定的"这件事没有地方可写。
    ///
    /// `Then` 缺席 = `ToHandFree`（与 `Discovery` 同义）；`Wish` 写 `PlayChosen`。
    OfferCards,
    /// §253：**由别的牌把一张牌打出来**（`Wish` 的三个选项；参考的 `node.playCard`）。'''),
    ('''            NodeKind::PlayCard => "node.playCard",''',
     '''            NodeKind::PlayCard => "node.playCard",
            NodeKind::OfferCards => "node.offerCards",'''),
    ('''            NodeKind::PlayCard,
            NodeKind::CreateCardCopy,''',
     '''            NodeKind::PlayCard,
            NodeKind::OfferCards,
            NodeKind::CreateCardCopy,'''),
]


def patch(path, pairs, label):
    src = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert src.count(old) == 1, (label, old[:60], src.count(old))
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('patched', label)


def main():
    patch(STATE, STATE_PATCHES, 'state.rs (PlayChosen + enqueue)')
    patch(EXEC, EXEC_PATCHES, 'exec.rs (PlayCard request)')
    patch(IR, IR_PATCHES, 'ir.rs (OfferCards)')
    src = io.open(IR, encoding='utf-8').read()
    old = '        const ALL: [NodeKind; 40] = ['
    assert src.count(old) == 1
    io.open(IR, 'w', encoding='utf-8', newline='\n').write(
        src.replace(old, '        const ALL: [NodeKind; 41] = ['))
    print('ir.rs: ALL -> 41')


main()
