"""§226 (part 3): 复制载体 —— `ChoiceThen::Copy` + 收窄清单 + `node.chooseCards`。

state.rs：
* `PendingChoice.copies`（每张选中的牌造几份）与 `PendingChoice.candidates`（收窄后的合法清单）；
* `ChoiceThen::Copy`；
* `begin_choice` / `choice_legal` / `resolve_from_pile`（新分支 `resolve_copy`）/ `ChoiceError`。
ir.rs：`NodeKind::ChooseCards`。
exec.rs：`choose_cards_node`（内容过滤 + 提问）+ 预检 + 分发。
"""
import io

STATE = 'kernel/rd-core/src/state.rs'
IR = 'kernel/rd-core/src/ir.rs'
EXEC = 'kernel/rd-core/src/exec.rs'


def rewrite(path, edits):
    src = io.open(path, encoding='utf-8').read()
    for old, new in edits:
        assert src.count(old) == 1, (path, src.count(old), old[:60])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)


# ────────────────────────────────── state.rs ──────────────────────────────────
rewrite(STATE, [
    # (1) PendingChoice 两个新字段
    ('''    /// 其余来源必须留空；`begin_choice` 两边都校验，因为「候选」和「来源」不一致，等于问一个
    /// 玩家答不出来的问题。
    pub offered: Bounded<CardDefinitionId, MAX_CHOICE_OFFERED>,
}''',
     '''    /// 其余来源必须留空；`begin_choice` 两边都校验，因为「候选」和「来源」不一致，等于问一个
    /// 玩家答不出来的问题。
    pub offered: Bounded<CardDefinitionId, MAX_CHOICE_OFFERED>,
    /// 每张选中的牌**造几份副本**（§226）。只有 [`ChoiceThen::Copy`] 用得上。
    ///
    /// 其余 `then` 必须留 `0`，`begin_choice` **响亮拒绝** —— 静默忽略一个副本数，就是让
    /// "它复制了两份"变成"它复制了零份"，而零份也是一次成功的复制。
    pub copies: u8,
    /// **收窄后的合法清单**（§226）：非空 ⇒ 只有这些实例能被选。
    ///
    /// 为什么它必须在状态里：StS 的 `Dual Wield` 是「选一张 **Attack 或 Power** 牌复制」，而这个
    /// 过滤要读**卡定义的 tag 表** —— 那是内容（`Content`）才有的东西，`CombatState` 里没有内容。
    /// 所以由**节点**（它拿得到内容）在提问那一刻把清单算好，状态只负责守着它：`choice_legal`
    /// 按这份清单出选项，`resolve_choice` 也只认这份清单里的牌。
    ///
    /// 空 = 不过滤（Elixir / Gambler's Brew / Liquid Memories 的老问句，逐字不变 ——
    /// 这也是加它**不动任何基线**的原因）。`begin_choice` 校验每一项**现在真的在来源牌区里**。
    pub candidates: Bounded<CardInstanceId, MAX_CHOICE_OFFERED>,
}'''),

    # (2) ChoiceThen::Copy
    ('''    /// 把选中的牌**拿进手牌**，并给它一个每副本价格（§161.4，Liquid Memories）。
    ///
    /// 价格由 `resolve_choice` 的 `cost_delta` 参数给出，因为"免费"是**负数张牌代价**，
    /// 而那个数字只有知道内容的人算得出来（`CombatState` 里没有内容）。
    ToHand,
}''',
     '''    /// 把选中的牌**拿进手牌**，并给它一个每副本价格（§161.4，Liquid Memories）。
    ///
    /// 价格由 `resolve_choice` 的 `cost_delta` 参数给出，因为"免费"是**负数张牌代价**，
    /// 而那个数字只有知道内容的人算得出来（`CombatState` 里没有内容）。
    ToHand,
    /// **复制**选中的牌（§226，Dual Wield）：原件**不动**，往手牌里造 [`PendingChoice::copies`] 份。
    ///
    /// 与 [`Self::ToHand`] 的区别是"搬"与"造"：那个把那一份**搬**过去（顺带给它一个每副本价格），
    /// 这个**造**新的 —— 新副本是印刷价（StS 的副本不是打折商品，所以 `Copies` 与 `cost_delta`
    /// 互斥由 `resolve_choice` 的上游那条判据守住）。
    Copy,
}'''),
    ('''            Self::DiscardThenDraw => CardZone::DiscardPile,
            Self::ToHand => CardZone::Hand,
        }''',
     '''            Self::DiscardThenDraw => CardZone::DiscardPile,
            Self::ToHand => CardZone::Hand,
            // 副本进手牌；**原件不搬**（`resolve_from_pile` 的 `Copy` 分支在动第一张牌之前就
            // 分流出去了），所以这个返回值的唯一用途是给容量判据当"新卡落在哪儿"。
            Self::Copy => CardZone::Hand,
        }'''),

    # (3) ChoiceError 新变体
    ('''    /// 给了一个 `cost_delta`，但这个问句的 `then` 根本没有价格（只有 [`ChoiceThen::ToHand`] 有）。''',
     '''    /// 副本数与 `then` 不自洽（§226）：非 [`ChoiceThen::Copy`] 的问句带了非零 `copies`，或者
    /// [`ChoiceThen::Copy`] 的 `copies` 是 0。
    ///
    /// **调用方（= 内容）的错，不是玩家的错**：静默取 `0` 或 `1` 都会把"复制"变成一个
    /// 看不出来的别的动作（零份 = 什么都没发生却扣了牌；一份 = 少了一份）。
    CopiesNotApplicable,
    /// 给了一个 `cost_delta`，但这个问句的 `then` 根本没有价格（只有 [`ChoiceThen::ToHand`] 有）。'''),

    # (4) begin_choice 校验
    ('''        if choice.min > choice.max || choice.min as usize > available {
            return Err(ChoiceError::Count {
                picked: available,
                min: choice.min,
                max: choice.max,
            });
        }
        self.choice = Some(choice);
        Ok(())''',
     '''        if choice.min > choice.max || choice.min as usize > available {
            return Err(ChoiceError::Count {
                picked: available,
                min: choice.min,
                max: choice.max,
            });
        }
        // §226：副本数只有 `Copy` 用得上，两个方向都要拒（"复制 0 份"是一次成功的空操作，
        // 那是最难发现的一种错）。
        if (choice.copies != 0) != (choice.then == ChoiceThen::Copy) {
            return Err(ChoiceError::CopiesNotApplicable);
        }
        // §226：收窄清单只能挂在**牌区来源**上，而且每一项**现在**都得在来源牌区里 ——
        // 否则玩家会看到一个点了没反应的选项。
        if !choice.candidates.is_empty() {
            let Some(zone) = choice.source.zone() else {
                return Err(ChoiceError::WrongAnswer);
            };
            for id in choice.candidates.as_slice() {
                match self.find_card(&choice.chooser, id) {
                    Some((where_it_is, _)) if where_it_is == zone => {}
                    _ => return Err(ChoiceError::NotInSource),
                }
            }
            // 清单比下限还短 ⇒ 这个问句永远答不出来（与上面那条 `available` 判据同一条理由，
            // 只是 `available` 数的是**整个牌区**，而玩家只能从清单里挑）。
            if choice.min as usize > choice.candidates.len() {
                return Err(ChoiceError::Count {
                    picked: choice.candidates.len(),
                    min: choice.min,
                    max: choice.max,
                });
            }
        }
        self.choice = Some(choice);
        Ok(())'''),

    # (5) choice_legal 认收窄清单
    ('''        let Some(zone) = choice.source.zone() else {
            return Err(ChoiceError::WrongAnswer);
        };
        let zones = self
            .card_zones(&choice.chooser)
            .ok_or(ChoiceError::NotInSource)?;
        let mut count = 0usize;''',
     '''        let Some(zone) = choice.source.zone() else {
            return Err(ChoiceError::WrongAnswer);
        };
        // §226：收窄清单优先 —— 它**就是**"哪些选项合法"的答案，顺序也照它（节点给的顺序，
        // 不是牌区顺序）。这一步同时是 `resolve_choice` 的镜像：两边认同一份清单，才不会出现
        // "页面能点、内核说不在来源里"。
        if !choice.candidates.is_empty() {
            let mut narrowed = 0usize;
            for id in choice.candidates.as_slice() {
                // 清单是提问那一刻的快照。问句挂着的时候牌区**不可能**变（`begin_choice` 挡掉
                // 了嵌套），所以"找不到"只可能是坏状态 —— 但跳过一项也比 panic 好，而且
                // `resolve_choice` 会在同一种情形下响亮拒绝。
                let Some((where_it_is, _)) = self.find_card(&choice.chooser, id) else {
                    continue;
                };
                if where_it_is != zone {
                    continue;
                }
                if narrowed == out.len() {
                    return Err(ChoiceError::Capacity(CapacityError::Full(
                        Container::ChoiceOptions,
                    )));
                }
                out[narrowed] = *id;
                narrowed += 1;
            }
            return Ok(narrowed);
        }
        let zones = self
            .card_zones(&choice.chooser)
            .ok_or(ChoiceError::NotInSource)?;
        let mut count = 0usize;'''),

    # (6) resolve_from_pile：成员校验加清单 + Copy 分流
    ('''            if picks[..index].iter().any(|earlier| earlier == id) {
                return Err(ChoiceError::Duplicate);
            }
            slots[index] = slot;
        }''',
     '''            if picks[..index].iter().any(|earlier| earlier == id) {
                return Err(ChoiceError::Duplicate);
            }
            // §226：有收窄清单时，清单之外的牌**不是**这个问句的答案（页面根本不会列它）。
            if !choice.candidates.is_empty() && !choice.candidates.as_slice().contains(id) {
                return Err(ChoiceError::NotInSource);
            }
            slots[index] = slot;
        }
        // §226：`Copy` 是"造"而不是"搬"—— 原件留在原处，所以它和下面的目的牌区容量判据
        // 是两件事（这里要的是**手牌的空位**，那要的是"要搬进去的那个区"）。分支放在
        // "一个字节都没改"这条线之前，两支各自保证自己全验证完再动手。
        if choice.then == ChoiceThen::Copy {
            return self.resolve_copy(choice, &slots[..picked]);
        }'''),

    # (7) resolve_copy 实体（插在 resolve_offered 之前）
    ('''    /// 候选来源的答案（[`ChoiceSource::Offered`]，§161.5）。''',
     '''    /// **复制**的答案（[`ChoiceThen::Copy`]，§226）。
    ///
    /// 语义：选中的每一张**留在原处**，往手牌里再造 [`PendingChoice::copies`] 份**同定义**的副本。
    /// 副本是全新的实例 ⇒ 印刷价、没有每副本价格、没有 `queued_target_id`（StS 的副本就是
    /// 印刷的那张牌，不是被打折或被瞄过的那一份）。
    ///
    /// 两条容量判据都在动手之前：手牌装得下**全部**副本、卡池还有**全部**槽位。
    /// `ChoiceDone::picked` 报的是**造出来几份**（不是选中几张）：调用方要能分辨
    /// "选了一张、造了两份"和"选了两张、各一份"，而这两件事对手牌的影响相同，对日志不同。
    fn resolve_copy(
        &mut self,
        choice: PendingChoice,
        slots: &[CardSlot],
    ) -> Result<ChoiceDone, ChoiceError> {
        let copies = usize::from(choice.copies);
        if copies == 0 {
            return Err(ChoiceError::CopiesNotApplicable);
        }
        let picked = slots.len();
        let total = picked.saturating_mul(copies);
        {
            let Some(zones) = self.card_zones(&choice.chooser) else {
                return Err(ChoiceError::NotInSource);
            };
            if total > MAX_CARDS_PER_ZONE.saturating_sub(zones.count(CardZone::Hand)) {
                return Err(ChoiceError::Capacity(CapacityError::Full(
                    Container::CardsInZone(CardZone::Hand),
                )));
            }
        }
        if self.cards.len() + total > MAX_CARD_INSTANCES {
            return Err(ChoiceError::Capacity(CapacityError::Full(
                Container::CardInstances,
            )));
        }
        // 定义 id 先抄出来：`create_card_instance` 要可变借用，抄完就放掉。
        let mut definitions = [CardDefinitionId::EMPTY; MAX_CHOICE_OFFERED];
        if picked > definitions.len() {
            return Err(ChoiceError::Count {
                picked,
                min: choice.min,
                max: choice.max,
            });
        }
        for (at, slot) in slots.iter().enumerate() {
            let Some(card) = self.card(*slot) else {
                return Err(ChoiceError::NotInSource);
            };
            definitions[at] = card.definition_id;
        }

        // ---- 到这里为止一个字节都没改。----
        let mut created = 0usize;
        for definition in &definitions[..picked] {
            for _ in 0..copies {
                self.create_card_instance(&choice.chooser, *definition, CardZone::Hand)?;
                created += 1;
            }
        }
        self.choice = None;
        Ok(ChoiceDone {
            picked: created,
            drawn: 0,
        })
    }

    /// 候选来源的答案（[`ChoiceSource::Offered`]，§161.5）。'''),

    # (8) Display 臂
    ('''            Self::NotInSource => f.write_str("a picked card is not in the source pile"),''',
     '''            Self::CopiesNotApplicable => {
                f.write_str("copies belong to `Copy` questions only, and `Copy` needs at least one")
            }
            Self::NotInSource => f.write_str("a picked card is not in the source pile"),'''),
])

# 所有 `PendingChoice { ... }` 字面量补两个字段（`gamblers_brew` 走 `..elixir(..)`，自动带上）。
src = io.open(STATE, encoding='utf-8').read()
old = '''            then: ChoiceThen::Exhaust,
            offered: Bounded::new(),
        }'''
new = '''            then: ChoiceThen::Exhaust,
            offered: Bounded::new(),
            copies: 0,
            candidates: Bounded::new(),
        }'''
assert src.count(old) == 1
src = src.replace(old, new)
old = '''            then: ChoiceThen::ToHand,
            offered,
        }'''
new = '''            then: ChoiceThen::ToHand,
            offered,
            copies: 0,
            candidates: Bounded::new(),
        }'''
assert src.count(old) == 1
src = src.replace(old, new)
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(src)

# ────────────────────────────────── ir.rs ──────────────────────────────────
rewrite(IR, [
    ('''    /// `node.selectCards` —— **挑卡并搬卡**（§195.4，本内核自己的节点）。''',
     '''    /// `node.chooseCards` —— **问玩家要哪几张牌，然后复制它们**（§226，本内核自己的节点）。
    ///
    /// StS 的 `Dual Wield`（"选一张 Attack 或 Power 牌，造一份/两份副本"）此前**没有载体**：
    /// `selectCards` 是内核自己按稀有度/顺序挑（不问人），而 `PendingChoice` 只有药水那三条路
    /// （由运行层发起、`then` 是消耗/弃抽/拿进手牌）。复制既不是"搬"也不是"造一张内容写死的牌"，
    /// 所以缺的是**"玩家的选择" × "复制"** 这个组合。
    ///
    /// 与 [`Self::SelectCards`] 的分工：那个是「选谁」（内容替玩家决定），这个是「玩家选」。
    ChooseCards,
    /// `node.selectCards` —— **挑卡并搬卡**（§195.4，本内核自己的节点）。'''),
    ('''            NodeKind::SelectCards => "node.selectCards",''',
     '''            NodeKind::ChooseCards => "node.chooseCards",
            NodeKind::SelectCards => "node.selectCards",'''),
    ('''        const ALL: [NodeKind; 23] = [''',
     '''        const ALL: [NodeKind; 24] = ['''),
    ('''            NodeKind::SelectCards,
            NodeKind::Repeat,
        ];''',
     '''            NodeKind::SelectCards,
            // §226：问玩家要哪几张牌，然后复制（Dual Wield）。
            NodeKind::ChooseCards,
            NodeKind::Repeat,
        ];'''),
])

print('ok state+ir')
