"""Insert the PendingChoice methods into rd-core's CombatState (§161.3).

One shot; asserts the anchor is unique, so re-running it is a loud failure rather than a
second copy of every method.
"""
import io

PATH = "kernel/rd-core/src/state.rs"

ANCHOR = """        zones.insert_slot_front(zone, slot)?;
        self.cards.push(card, Container::CardInstances)?;
        Ok(CardSlot(slot))
    }
}
"""

METHODS = """        zones.insert_slot_front(zone, slot)?;
        self.cards.push(card, Container::CardInstances)?;
        Ok(CardSlot(slot))
    }

    // ── 待决的选牌（§161.3）────────────────────────────────────────────────────────────────────
    //
    // REVIEW §四.2 的要求原话是「战斗侧补一个边界明确的待决操作即可，例如选牌来源、最少/最多
    // 张数、选完后的操作。同一机制应能服务卡牌、药水和事件」。下面四个函数就是那句话的全部：
    // `begin_choice` 提出问题、`choice_legal` 把合法选项**列出来**、`resolve_choice` 收答案并
    // 执行、`pending_choice` 让宿主知道现在该问什么。
    //
    // 三条纪律：
    //
    // 1. **拒绝不改任何东西。** 这是 §161.2(a) 在战斗层的同一条话：`resolve_choice` 先做完
    //    全部校验（张数、来源、重复、两个目的牌区的容量），再动第一张牌。半途而废比拒绝更糟
    //    —— 拒绝是可见的，半途是「两张被消耗、一张还在」。
    // 2. **选牌不嵌套。** 两个待决问句叠在一起，界面无法表达先后，回放也无法表达。
    //    `begin_choice` 见到已经有一个就拒绝（不是排队）。
    // 3. **`min == 0` 时取消永远可用。** 这不是方便，是语义：Elixir 与 Gambler's Brew 的
    //    原文都是「任意张」，选 0 张就是玩家的合法答案。

    /// 当前待决的选牌（`None` = 没有）。
    #[must_use]
    pub const fn pending_choice(&self) -> Option<PendingChoice> {
        self.choice
    }

    /// 提出一个待决的选牌。
    ///
    /// 三道前置校验，全部**响亮**：
    ///
    /// * 已经有一个待决的 ⇒ [`ChoiceError::AlreadyPending`]（不排队）；
    /// * `min > max` ⇒ [`ChoiceError::Count`]：这是内容错误，不是玩家输入错误；
    /// * `min` 超过来源牌区的实际张数 ⇒ [`ChoiceError::Count`]：那样的问句**永远无法回答**，
    ///   而一个答不出来的问句会把这一局钉死。宁可在这里红。
    pub fn begin_choice(&mut self, choice: PendingChoice) -> Result<(), ChoiceError> {
        if self.choice.is_some() {
            return Err(ChoiceError::AlreadyPending);
        }
        let zone = choice.source.zone();
        let available = self
            .card_zones(&choice.chooser)
            .ok_or(ChoiceError::NotInSource)?
            .count(zone);
        if choice.min > choice.max || choice.min as usize > available {
            return Err(ChoiceError::Count {
                picked: available,
                min: choice.min,
                max: choice.max,
            });
        }
        self.choice = Some(choice);
        Ok(())
    }

    /// 合法的卡，按**来源牌区的顺序**写进 `out`，返回个数。
    ///
    /// 「可枚举」在这里是字面意思：宿主/训练器不需要知道 Elixir 和 Gambler's Brew 的区别，
    /// 它问一次就拿到完整的候选清单。`out` 装不下整份清单 ⇒ [`Container::ChoiceOptions`]，
    /// **不截断**（截断掉的选项等于一个不存在的规则）。
    pub fn choice_legal(&self, out: &mut [CardInstanceId]) -> Result<usize, ChoiceError> {
        let choice = self.choice.ok_or(ChoiceError::NotPending)?;
        let zones = self
            .card_zones(&choice.chooser)
            .ok_or(ChoiceError::NotInSource)?;
        let zone = choice.source.zone();
        let mut count = 0usize;
        for index in 0..zones.count(zone) {
            // 槽位表与卡池必须一致；不一致的槽位跳过（`card()` 的 `Option` 兜住，不 panic）。
            let Some(slot) = zones.slot_at(zone, index) else {
                continue;
            };
            let Some(card) = self.card(slot) else {
                continue;
            };
            if count == out.len() {
                return Err(ChoiceError::Capacity(CapacityError::Full(
                    Container::ChoiceOptions,
                )));
            }
            out[count] = card.id;
            count += 1;
        }
        Ok(count)
    }

    /// 结算待决的选牌：把选中的牌按 [`ChoiceThen`] 送走，然后清掉问句。
    ///
    /// **全部校验在动手之前**（见本节头第 1 条）。成功之后 [`Self::pending_choice`] 是 `None`。
    pub fn resolve_choice(&mut self, picks: &[CardInstanceId]) -> Result<ChoiceDone, ChoiceError> {
        let choice = self.choice.ok_or(ChoiceError::NotPending)?;
        let picked = picks.len();
        if picked < choice.min as usize || picked > choice.max as usize {
            return Err(ChoiceError::Count {
                picked,
                min: choice.min,
                max: choice.max,
            });
        }

        let source = choice.source.zone();
        let destination = choice.then.destination();
        let Some(zones) = self.card_zones(&choice.chooser) else {
            return Err(ChoiceError::NotInSource);
        };
        // (a) 每张都在来源牌区里，而且不重复。重复直接比 id —— 卡实例 id 在整场里唯一，
        //     所以「同一个 id 出现两次」就是「同一张牌被选了两次」，不需要第二张表。
        let mut slots = [CardSlot::from_index(0); MAX_CARDS_PER_ZONE];
        for (index, id) in picks.iter().enumerate() {
            let Some((zone, slot)) = self.find_card(&choice.chooser, id) else {
                return Err(ChoiceError::NotInSource);
            };
            if zone != source {
                return Err(ChoiceError::NotInSource);
            }
            if picks[..index].iter().any(|earlier| earlier == id) {
                return Err(ChoiceError::Duplicate);
            }
            slots[index] = slot;
        }
        // (b) 目的牌区装得下。三条一起看，因为「搬第一张时才发现第三张装不下」正是要避免的。
        let destination_room = MAX_CARDS_PER_ZONE.saturating_sub(zones.count(destination));
        if picked > destination_room {
            return Err(ChoiceError::Capacity(CapacityError::Full(
                Container::CardsInZone(destination),
            )));
        }
        // (c) `DiscardThenDraw` 会把 `picked` 张抽回**同一只手牌**。先丢掉 `picked` 张，手牌
        //     因此空了 `picked` 格，所以抽满 `picked` 张在构造上装得下 —— 这里把它断言成前置
        //     条件，而不是指望下游的 `move_card` 半路报错。
        if choice.then == ChoiceThen::DiscardThenDraw
            && zones.count(CardZone::Hand) + picked > MAX_CARDS_PER_ZONE
        {
            return Err(ChoiceError::Capacity(CapacityError::Full(
                Container::CardsInZone(CardZone::Hand),
            )));
        }

        // ---- 到这里为止一个字节都没改。----
        for &slot in &slots[..picked] {
            self.move_card(&choice.chooser, source, destination, slot, ZonePlacement::Bottom)?;
        }
        self.choice = None;

        let mut drawn = 0usize;
        if choice.then == ChoiceThen::DiscardThenDraw {
            drawn = self.draw_cards_with_reshuffle(&choice.chooser, picked)?;
        }
        Ok(ChoiceDone { picked, drawn })
    }

    /// 在**一个战斗员**的七个牌区里按 id 找卡，返回 `(在哪个区, 池槽位)`。
    ///
    /// 参考的 `zones.GetCard(id)`（`Cards/CardZones.cs:192-200`）的等价物：只在这套牌区里找，
    /// 所以「找不到」同时覆盖了「卡不存在」与「卡的主人不是这个战斗员」。
    #[must_use]
    pub fn find_card(
        &self,
        owner: &CombatantId,
        card_id: &CardInstanceId,
    ) -> Option<(CardZone, CardSlot)> {
        let zones = self.card_zones(owner)?;
        for zone in CardZone::ALL {
            for index in 0..zones.count(zone) {
                let Some(slot) = zones.slot_at(zone, index) else {
                    continue;
                };
                if self.card(slot).map(|card| card.id == *card_id) == Some(true) {
                    return Some((zone, slot));
                }
            }
        }
        None
    }

    /// 抽 `wanted` 张，抽牌堆空了就**重洗弃牌堆**（每次调用最多一次），返回真抽到的张数。
    ///
    /// 这是从 `turn.rs::draw_for_turn_start` 的循环体里搬出来的，因为消费者从**一个变成了两个**
    /// （回合开始抽牌，以及 §161.3 的 `ChoiceThen::DiscardThenDraw`）。抄第二份的后果是可预测的：
    /// 两边的重洗策略会分叉，而「少重洗一次」只表现为某一步的 `step=` 与牌序不同 —— 那是最难
    /// 从失败信息里读回来的错。
    ///
    /// 循环一定会停：重洗会**搬空弃牌堆**，而循环体内没有任何东西会再往里放牌 ⇒ 最多重洗一次，
    /// 重洗后抽牌堆非空 ⇒ 下一圈必然抽到牌。「抽不满」的唯一成因是**两堆都空**，与参考一致
    /// （`Cards/CardZones.cs:59-60`）。
    pub fn draw_cards_with_reshuffle(
        &mut self,
        owner: &CombatantId,
        wanted: usize,
    ) -> StateResult<usize> {
        let mut drawn = 0usize;
        while drawn < wanted {
            while drawn < wanted {
                if self.draw_card(owner)?.is_none() {
                    break;
                }
                drawn += 1;
            }
            if drawn >= wanted {
                break;
            }
            if self
                .card_zones(owner)
                .is_none_or(|zones| zones.count(CardZone::DiscardPile) == 0)
            {
                break;
            }
            if self.reshuffle_discard_into_draw(owner)? == 0 {
                break;
            }
        }
        Ok(drawn)
    }
}
"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "pub fn resolve_choice" not in text, "already inserted"
    text = text.replace(ANCHOR, METHODS)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("methods inserted")


if __name__ == "__main__":
    main()
