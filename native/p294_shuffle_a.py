"""§294 A1：`DeckShuffled` 触发器（一次改动服务 `the_abacus` + `sundial`）。

## 为什么是"我们自己的扩展"

参考的 `TriggerEvent` 有 25 个成员，**没有"洗牌"这一个**（它把这件事折进 `CardMovedToZone`）。
本内核 §237 已经为同一类缺口加过两个（`CardsDrawn` / `CardExhausted`），这一条是第三个：
被真实内容逼出来的，落点只有一处（`CombatState::reshuffle_discard_into_draw`），
于是"洗了牌却没通知"这种漏法结构上不存在。

## 事件与 Bearer

`DeckShuffled { combatant }` —— Bearer 是**洗牌的那个人**（弃牌堆进抽牌堆时牌堆的主人）。
`the_abacus`（+6 格挡）与 `sundial`（每 3 次 +2 能量）都只关心"我洗了"。

## 为什么发在 `reshuffle_discard_into_draw` 里

三条洗牌的路（抽牌时的自动重洗、内容里的 `shuffleDiscardIntoDraw`、`Havoc` 一类的辅助）
**全都**经过那个函数 —— 它已经在推进 `random_step`，也已经在处理"弃牌堆空 ⇒ 返回 0"。
发在别处就要三处各发一次，而那正是"漏发一处"的形状。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-core/src/state.rs'
HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:100])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── 1. `CombatEvent::DeckShuffled`
    patch(STATE, '''    /// `CardCostPaid`（`CardPlay.cs:138`）：出牌付了费用。''',
                 '''    /// §294：**有人把弃牌堆洗回了抽牌堆**（`the_abacus` / `sundial`）。
    ///
    /// 参考的 25 个触发器里没有这一个（它把洗牌折进 `CardMovedToZone`）。这是**本内核自己的
    /// 事件名**，与 §237 的 `CardsDrawn` / `CardExhausted` 同级：被真实内容逼出来的扩展。
    ///
    /// Bearer 是**洗牌的那个人**（弃牌堆的主人）。发在
    /// [`CombatState::reshuffle_discard_into_draw`] 里 —— 三条洗牌的路都经过它。
    DeckShuffled {
        /// 洗牌的人。
        combatant: CombatantId,
    },
    /// `CardCostPaid`（`CardPlay.cs:138`）：出牌付了费用。''')

    # ── 2. 在洗牌成功之后入队
    patch(STATE, '''        // 只有真的洗了才推进 —— 空弃牌堆上面已经早退，没有这一步。
        self.random_step += 1;
        Ok(count)''',
                 '''        // 只有真的洗了才推进 —— 空弃牌堆上面已经早退，没有这一步。
        self.random_step += 1;
        // §294：洗完了才通知（空弃牌堆**不算**洗过牌 —— `sundial` 的"每 3 次"不能数空的）。
        // ⚠️ 入队而不是立刻派发：这里没有 `Host`；事件由回合机的事件循环解析，
        // 与 `CardsDrawn` / `CardExhausted` 同一条路。
        self.enqueue_event(CombatEvent::DeckShuffled {
            combatant: *owner,
        })?;
        Ok(count)''')

    # ── 3. host：变体 + 线名 + 解码
    patch(HOST, '''    /// §237：**一张牌被消耗了**。Bearer = 牌的主人（`Dark Embrace`）。
    CardExhausted,''',
                '''    /// §237：**一张牌被消耗了**。Bearer = 牌的主人（`Dark Embrace`）。
    CardExhausted,
    /// §294：**有人洗了牌**。Bearer = 洗牌的那个人（`the_abacus` / `sundial`）。
    ///
    /// 参考的 25 个成员里没有它（洗牌被折进 `CardMovedToZone`），所以这是本内核的扩展 ——
    /// 与 [`Self::CardsDrawn`] / [`Self::CardExhausted`] 同一类：内容真的需要它。
    DeckShuffled,''')

    patch(HOST, '''            "CardExhausted" => Some(TriggerEvent::CardExhausted),''',
                 '''            "CardExhausted" => Some(TriggerEvent::CardExhausted),
            // §294：本内核的扩展（参考没有这个名字）。
            "DeckShuffled" => Some(TriggerEvent::DeckShuffled),''')

    patch(HOST, '''            TriggerEvent::CardExhausted => "CardExhausted",''',
                 '''            TriggerEvent::CardExhausted => "CardExhausted",
            TriggerEvent::DeckShuffled => "DeckShuffled",''')

    # ── 4. 事件 → 触发器（Bearer = 洗牌者）
    patch(HOST, '''            CombatEvent::CardExhausted { combatant, card } => {''',
                 '''            // §294：洗牌 —— Bearer 是洗牌的那个人，没有事实位（"洗了几张"由状态自己的
            // 计数器回答，而 `sundial` 数的是**次数**不是张数）。
            CombatEvent::DeckShuffled { combatant } => {
                let _ = combatant;
                TriggerEvent::DeckShuffled
            }
            CombatEvent::CardExhausted { combatant, card } => {''')
    print('kernel: DeckShuffled')


main()
