"""§237 内核：三个触发器钩子（BlockGained / CardsDrawn / CardExhausted）+ curse 标签位。"""
import io

ROOT = 'D:/Vibe/sts-tui/kernel/rd-core/src/'


def patch(name, pairs):
    path = ROOT + name
    s = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:60], s.count(old))
        s = s.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('patched', name)


# ---------------------------------------------------------------- state.rs：三个事件
patch('state.rs', [(
    '''    /// `CardCostPaid`（`CardPlay.cs:138`）：出牌付了费用。''',
    '''    /// §237：**有人获得了格挡**。Bearer = 获得格挡的那一方。
    ///
    /// `amount` 是**真的加了**多少（修饰后），不是请求额 —— `Juggernaut` 不看这个数，但把它带上
    /// 才对得起"事实"二字：将来有状态问"一次加了多少"时不用再改一次事件形状。
    BlockGained {
        /// 获得格挡的一方。
        combatant: CombatantId,
        /// 实际增量（被 `block_stage` 修饰之后）。
        amount: i32,
    },
    /// §237：**有人抽到了一张牌**（每张一次，不是"抽了几张"一次）。
    ///
    /// StS 的 `Evolve` / `Fire Breathing` 都是"每当你**抽到**一张 Status/Curse" ⇒ 计数单位是**张**，
    /// 所以这个事件必须一张一条。带 `card` 是为了让触发器能问"这张牌有 status tag 吗"
    /// （`event.bool: card.hasTag.status`）。
    CardsDrawn {
        /// 抽牌的人。
        combatant: CombatantId,
        /// 抽到的那张牌。
        card: crate::state::CardInstanceId,
    },
    /// §237：**一张牌被消耗了**（进了消耗堆）。`Dark Embrace` 就长在这上面。
    ///
    /// 三条入堆路径（§225 的审计：打出即消耗 / 虚无 / 内容 `moveCardToZone`）都在宿主侧汇到
    /// `Host::card_exhausted`，事件就发在那一处 —— 与 `LifecyclePrograms[Exhausted]` 同一个落点。
    CardExhausted {
        /// 牌的主人。
        combatant: CombatantId,
        /// 被消耗的那张牌。
        card: crate::state::CardInstanceId,
    },
    /// `CardCostPaid`（`CardPlay.cs:138`）：出牌付了费用。''',
)])

# ---------------------------------------------------------------- exec.rs：curse 位 + 格挡事件
patch('exec.rs', [
    ('''pub const CARD_HAS_TAG_STATUS: u8 = 1 << 3;''',
     '''pub const CARD_HAS_TAG_STATUS: u8 = 1 << 3;

/// §237：`curse` 标签（`Fire Breathing` 要"Status **或** Curse"）。第 7 位是当时唯一空着的。
pub const CARD_HAS_TAG_CURSE: u8 = 1 << 7;'''),
    ('''        crate::beat::record(
            ctx.state,
            crate::beat::Beat {
                kind: crate::beat::BeatKind::Block,
                actor: crate::beat::ordinal_of(ctx.state, target),
                target: crate::beat::ordinal_of(ctx.state, target),
                def: crate::beat::NO_DEF,
                flags: 0,
                a: modified,
                b: 0,
                c: 0,
            },
        );''',
     '''        crate::beat::record(
            ctx.state,
            crate::beat::Beat {
                kind: crate::beat::BeatKind::Block,
                actor: crate::beat::ordinal_of(ctx.state, target),
                target: crate::beat::ordinal_of(ctx.state, target),
                def: crate::beat::NO_DEF,
                flags: 0,
                a: modified,
                b: 0,
                c: 0,
            },
        );
        // §237：`BlockGained` —— 与伤害事件同一形状（唯一出口处入队），Bearer 是**获得格挡的人**。
        // 只在 `modified != 0` 时发：`Juggernaut` 是"每当你获得格挡"，加 0 点不算获得。
        ctx.state
            .enqueue_event(crate::state::CombatEvent::BlockGained {
                combatant: *target,
                amount: modified,
            })
            .map_err(ExecError::Capacity)?;'''),
])

# ---------------------------------------------------------------- content.rs：curse 位
patch('content.rs', [(
    '''        if self.card_has_tag(card, "status") == Some(true) {
            bits |= crate::exec::CARD_HAS_TAG_STATUS;
        }''',
    '''        if self.card_has_tag(card, "status") == Some(true) {
            bits |= crate::exec::CARD_HAS_TAG_STATUS;
        }
        // §237: `Fire Breathing` asks for "Status **or** Curse".
        if self.card_has_tag(card, "curse") == Some(true) {
            bits |= crate::exec::CARD_HAS_TAG_CURSE;
        }''',
)])

# ---------------------------------------------------------------- expr.rs：curse 关键字
patch('expr.rs', [(
    '''                "card.hasTag.status" => crate::exec::CARD_HAS_TAG_STATUS,''',
    '''                "card.hasTag.status" => crate::exec::CARD_HAS_TAG_STATUS,
                // §237: `Fire Breathing` is the only reader today.
                "card.hasTag.curse" => crate::exec::CARD_HAS_TAG_CURSE,''',
)])

# ---------------------------------------------------------------- host.rs
patch('host.rs', [
    # 变体
    ('''    /// `StatusApplied` —— 一条新状态实例落到某人身上。''',
     '''    /// §237：**获得了格挡**。Bearer = 获得格挡的那一方（`Juggernaut`）。
    ///
    /// 与 `DamageTaken` 一样是**承受者侧**的名字，但方向相反：那一条是"我被打"，
    /// 这一条是"我变厚了"。
    BlockGained,
    /// §237：**抽到了一张牌**。Bearer = 抽牌的人（`Evolve` / `Fire Breathing`）。
    ///
    /// 事实位给的是**抽到的那张牌**的标签（`card.hasTag.status|curse`，由 `card_tag_flags` 填）。
    CardsDrawn,
    /// §237：**一张牌被消耗了**。Bearer = 牌的主人（`Dark Embrace`）。
    CardExhausted,
    /// `StatusApplied` —— 一条新状态实例落到某人身上。'''),
    # from_wire_name
    ('''            "CardPlayed" => Some(TriggerEvent::CardPlayed),''',
     '''            "CardPlayed" => Some(TriggerEvent::CardPlayed),
            // §237: the three trigger hooks that used to be `NotHandled`.
            "BlockGained" => Some(TriggerEvent::BlockGained),
            "CardsDrawn" => Some(TriggerEvent::CardsDrawn),
            "CardExhausted" => Some(TriggerEvent::CardExhausted),'''),
    ('''            "Healed" | "StatusExpired"
            | "ResourceGained" | "StatusRemoved"
            | "BlockGained" | "CardsDrawn"
            | "CardMovedToZone" | "CardInstanceCreated" | "StatusApplicationPrevented"''',
     '''            "Healed" | "StatusExpired"
            | "ResourceGained" | "StatusRemoved"
            | "CardMovedToZone" | "CardInstanceCreated" | "StatusApplicationPrevented"'''),
    # wire_name
    ('''            TriggerEvent::CardPlayed => "CardPlayed",''',
     '''            TriggerEvent::CardPlayed => "CardPlayed",
            // §237
            TriggerEvent::BlockGained => "BlockGained",
            TriggerEvent::CardsDrawn => "CardsDrawn",
            TriggerEvent::CardExhausted => "CardExhausted",'''),
    # 生命周期钩子：Drawn / Exhausted 各入队一条事件
    ('''        self.run_card_lifecycle_hook(state, actor, slot, crate::state::CardLifecycleEvent::Drawn)''',
     '''        let outcome =
            self.run_card_lifecycle_hook(state, actor, slot, crate::state::CardLifecycleEvent::Drawn);
        // §237：`CardsDrawn` 在**生命周期节目之后**发 —— StS 的顺序也是"牌进了手，再问有没有人
        // 对'抽到它'有意见"。每张一条（`Evolve` 的单位是张，不是"抽牌动作"）。
        if outcome.is_ok() {
            if let Some(card) = state.card(slot) {
                let event = crate::state::CombatEvent::CardsDrawn {
                    combatant: *actor,
                    card: card.id,
                };
                state.enqueue_event(event).map_err(bridge)?;
            }
        }
        outcome'''),
    ('''        self.run_card_lifecycle_hook(
            state,
            actor,
            slot,
            crate::state::CardLifecycleEvent::Exhausted,
        )''',
     '''        let outcome = self.run_card_lifecycle_hook(
            state,
            actor,
            slot,
            crate::state::CardLifecycleEvent::Exhausted,
        );
        // §237：`CardExhausted` 与 `LifecyclePrograms[Exhausted]` 同一个落点 —— 三条入堆路径
        // （§225 的审计）都经过这里，所以"消耗了却没通知"这种漏法这次结构上不存在。
        if outcome.is_ok() {
            if let Some(card) = state.card(slot) {
                let event = crate::state::CombatEvent::CardExhausted {
                    combatant: *actor,
                    card: card.id,
                };
                state.enqueue_event(event).map_err(bridge)?;
            }
        }
        outcome'''),
    # dispatch：三个新臂
    ('''            // `CardPlayed`：派发给**所有战斗员**（Enrage 在敌人身上，由你出牌触发）。''',
     '''            // §237: `BlockGained` -- Bearer 是获得格挡的那一方（Juggernaut）。
            CombatEvent::BlockGained { combatant, .. } => {
                self.run_triggers(state, &combatant, TriggerEvent::BlockGained)
            }
            // §237: `CardsDrawn` / `CardExhausted` -- Bearer 是牌的主人，事实位是**那张牌**的标签。
            // 两者形状相同（"你身上有事发生，主语是一张牌"），所以共用一段。
            CombatEvent::CardsDrawn { combatant, card }
            | CombatEvent::CardExhausted { combatant, card } => {
                let event = match item.event {
                    CombatEvent::CardsDrawn { .. } => TriggerEvent::CardsDrawn,
                    _ => TriggerEvent::CardExhausted,
                };
                let flags = card_definition_of(state, card)
                    .map_or(0, |definition| card_tag_flags(self.content, definition));
                self.run_triggers_with_flags(state, &combatant, event, flags)
            }
            // `CardPlayed`：派发给**所有战斗员**（Enrage 在敌人身上，由你出牌触发）。'''),
    # 那个 ts 里的穷尽 match（镜像计数）
    ('''                    // §236：镜像（core）里没有 `HpLost` 触发器，计数恒 0。
                    TriggerEvent::HpLost => {}''',
     '''                    // §236/§237：镜像（core）里没有这几条触发器，计数恒 0。
                    TriggerEvent::HpLost => {}
                    TriggerEvent::BlockGained => {}
                    TriggerEvent::CardsDrawn => {}
                    TriggerEvent::CardExhausted => {}'''),
])
print('done')
