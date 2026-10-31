"""§161.5 rd-core: `resolve_choice` grows the second answer shape, and the core learns to mint.

The minting move is the load-bearing one: `exec.rs` has turned `next_card_instance_number` into
`card_%06d` since §88, but `Offered` needs it from `state.rs` too, and **two minting paths is how
you get two counters**. So `numbered_text` + `create_card_instance` move into `state.rs` and
`exec.rs` calls them.
"""
import io

PATH = "kernel/rd-core/src/state.rs"

START = """    /// 结算待决的选牌：把选中的牌按 [`ChoiceThen`] 送走，然后清掉问句。"""
END = """    /// 在**一个战斗员**的七个牌区里按 id 找卡，返回 `(在哪个区, 池槽位)`。"""

NEW = '''    /// 结算待决的选牌：把选中的牌按 [`ChoiceThen`] 送走，然后清掉问句。
    ///
    /// `answer` 的形状必须和问句的**来源**一致（[`ChoiceError::WrongAnswer`]）：牌区来源回答
    /// 实例，候选来源回答下标。
    ///
    /// `cost_delta` 是**每副本价格**（[`CARD_COST_DELTA_COUNTER`]），只有
    /// [`ChoiceThen::ToHand`] 用得上；其余 `then` 必须传 `0`，否则
    /// [`ChoiceError::DeltaNotApplicable`] —— 静默忽略一个折扣会让"它免费"变成一句谎。
    ///
    /// **全部校验在动手之前**（见本节头第 1 条）。成功之后 [`Self::pending_choice`] 是 `None`。
    pub fn resolve_choice(
        &mut self,
        answer: ChoiceAnswer<'_>,
        cost_delta: i32,
    ) -> Result<ChoiceDone, ChoiceError> {
        let choice = self.choice.ok_or(ChoiceError::NotPending)?;
        if cost_delta != 0 && choice.then != ChoiceThen::ToHand {
            return Err(ChoiceError::DeltaNotApplicable);
        }
        match (choice.source, answer) {
            (ChoiceSource::Offered, ChoiceAnswer::Offered(indices)) => {
                self.resolve_offered(choice, indices, cost_delta)
            }
            (ChoiceSource::Offered, ChoiceAnswer::Instances(_))
            | (_, ChoiceAnswer::Offered(_)) => Err(ChoiceError::WrongAnswer),
            (_, ChoiceAnswer::Instances(picks)) => {
                self.resolve_from_pile(choice, picks, cost_delta)
            }
        }
    }

    /// 牌区来源的答案（[`ChoiceSource::Hand`] / [`ChoiceSource::DiscardPile`]）。
    fn resolve_from_pile(
        &mut self,
        choice: PendingChoice,
        picks: &[CardInstanceId],
        cost_delta: i32,
    ) -> Result<ChoiceDone, ChoiceError> {
        let source = choice.source.zone().ok_or(ChoiceError::WrongAnswer)?;
        let destination = choice.then.destination();
        let picked = picks.len();
        if picked < choice.min as usize || picked > choice.max as usize {
            return Err(ChoiceError::Count {
                picked,
                min: choice.min,
                max: choice.max,
            });
        }

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
            // §161.4: the per-copy price rides **on the card**, so it travels with it through the
            // hand and the discard pile -- and `play.rs` zeroes it once the play is paid for.
            if choice.then == ChoiceThen::ToHand && cost_delta != 0 {
                self.write_price(slot, cost_delta)?;
            }
        }
        self.choice = None;

        let mut drawn = 0usize;
        if choice.then == ChoiceThen::DiscardThenDraw {
            drawn = self.draw_cards_with_reshuffle(&choice.chooser, picked)?;
        }
        Ok(ChoiceDone { picked, drawn })
    }

    /// 候选来源的答案（[`ChoiceSource::Offered`]，§161.5）。
    ///
    /// 选中的那一张在这一刻**才**被造出来。三张候选里没被选的两张**从来没有存在过** ——
    /// 如果先把三张造成实例再扔掉两张，`card_num=` 与两条 `aside=` 卡行会凭空出现，
    /// 而参考引擎里那个局面根本没有这些牌。指纹要像参考，就不能为了内部方便多造牌。
    fn resolve_offered(
        &mut self,
        choice: PendingChoice,
        indices: &[usize],
        cost_delta: i32,
    ) -> Result<ChoiceDone, ChoiceError> {
        let offered = choice.offered.as_slice();
        let picked = indices.len();
        if picked < choice.min as usize || picked > choice.max as usize {
            return Err(ChoiceError::Count {
                picked,
                min: choice.min,
                max: choice.max,
            });
        }
        let mut definitions = [CardDefinitionId::EMPTY; MAX_CHOICE_OFFERED];
        for (at, index) in indices.iter().enumerate() {
            let Some(definition) = offered.get(*index) else {
                return Err(ChoiceError::NotInSource);
            };
            if indices[..at].contains(index) {
                return Err(ChoiceError::Duplicate);
            }
            definitions[at] = *definition;
        }
        let destination = choice.then.destination();
        // 两张容量一起看：牌区装不下、或者卡池没有多余槽位，都在动手之前拒绝。
        {
            let Some(zones) = self.card_zones(&choice.chooser) else {
                return Err(ChoiceError::NotInSource);
            };
            if picked > MAX_CARDS_PER_ZONE.saturating_sub(zones.count(destination)) {
                return Err(ChoiceError::Capacity(CapacityError::Full(
                    Container::CardsInZone(destination),
                )));
            }
        }
        if self.cards.len() + picked > MAX_CARD_INSTANCES {
            return Err(ChoiceError::Capacity(CapacityError::Full(
                Container::CardInstances,
            )));
        }

        // ---- 到这里为止一个字节都没改。----
        let mut created = 0usize;
        for definition in &definitions[..picked] {
            let slot = self.create_card_instance(&choice.chooser, *definition, destination)?;
            if choice.then == ChoiceThen::ToHand && cost_delta != 0 {
                self.write_price(slot, cost_delta)?;
            }
            created += 1;
        }
        self.choice = None;
        Ok(ChoiceDone {
            picked: created,
            drawn: 0,
        })
    }

    /// 把每副本价格写到**那一份副本**上（[`CARD_COST_DELTA_COUNTER`]）。
    fn write_price(&mut self, slot: CardSlot, delta: i32) -> Result<(), ChoiceError> {
        let key = CounterId::new(CARD_COST_DELTA_COUNTER)
            .map_err(|_| ChoiceError::NotInSource)?;
        let Some(card) = self.cards.as_mut_slice().get_mut(slot.index()) else {
            return Err(ChoiceError::NotInSource);
        };
        card.set_mark_counter(key, delta)?;
        Ok(())
    }

'''

# also: begin_choice + choice_legal need the new shape
BEGIN_MARK = """    pub fn begin_choice(&mut self, choice: PendingChoice) -> Result<(), ChoiceError> {
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
    }"""

BEGIN_NEW = """    pub fn begin_choice(&mut self, choice: PendingChoice) -> Result<(), ChoiceError> {
        if self.choice.is_some() {
            return Err(ChoiceError::AlreadyPending);
        }
        // 候选来源和牌区来源的"有多少可选"完全不是一件事：前者数**定义**，后者数牌区里的牌。
        // 两边都校验，因为一个"候选和来源对不上"的问句，玩家永远回答不了。
        let available = match choice.source.zone() {
            Some(zone) => {
                if !choice.offered.is_empty() {
                    return Err(ChoiceError::WrongAnswer);
                }
                self.card_zones(&choice.chooser)
                    .ok_or(ChoiceError::NotInSource)?
                    .count(zone)
            }
            None => choice.offered.len(),
        };
        if choice.min > choice.max || choice.min as usize > available {
            return Err(ChoiceError::Count {
                picked: available,
                min: choice.min,
                max: choice.max,
            });
        }
        self.choice = Some(choice);
        Ok(())
    }"""

LEGAL_MARK = """    pub fn choice_legal(&self, out: &mut [CardInstanceId]) -> Result<usize, ChoiceError> {
        let choice = self.choice.ok_or(ChoiceError::NotPending)?;
        let zones = self
            .card_zones(&choice.chooser)
            .ok_or(ChoiceError::NotInSource)?;
        let zone = choice.source.zone();"""

LEGAL_NEW = """    pub fn choice_legal(&self, out: &mut [CardInstanceId]) -> Result<usize, ChoiceError> {
        let choice = self.choice.ok_or(ChoiceError::NotPending)?;
        // 候选来源没有实例可列：它的选项是**下标 + 定义**，用 [`Self::choice_offered`] 读，
        // 这里**响亮拒绝**而不是返回 0 个（"零个选项"会被读成一个合法的空清单）。
        let Some(zone) = choice.source.zone() else {
            return Err(ChoiceError::WrongAnswer);
        };
        let zones = self
            .card_zones(&choice.chooser)
            .ok_or(ChoiceError::NotInSource)?;"""

OFFERED_ACC = '''    /// 候选来源的选项（[`ChoiceSource::Offered`]）：三条**卡定义**，按抽出的顺序。
    ///
    /// 牌区来源调用它 ⇒ [`ChoiceError::WrongAnswer`]（与 [`Self::choice_legal`] 互补：两个函数
    /// 各自只回答一种形态，而不是一个函数返回一个"看情况"的联合体）。
    pub fn choice_offered(&self) -> Result<&[CardDefinitionId], ChoiceError> {
        let choice = self.choice.ok_or(ChoiceError::NotPending)?;
        if choice.source.zone().is_some() {
            return Err(ChoiceError::WrongAnswer);
        }
        Ok(choice.offered.as_slice())
    }

'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    start = text.index(START)
    end = text.index(END)
    assert start < end
    text = text[:start] + NEW + text[end:]

    assert text.count(BEGIN_MARK) == 1
    text = text.replace(BEGIN_MARK, BEGIN_NEW)

    assert text.count(LEGAL_MARK) == 1
    text = text.replace(LEGAL_MARK, LEGAL_NEW)

    anchor = """    /// 结算待决的选牌：把选中的牌按 [`ChoiceThen`] 送走，然后清掉问句。"""
    assert text.count(anchor) == 1
    text = text.replace(anchor, OFFERED_ACC + anchor)

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("state.rs: resolve_choice grows the offered branch")


if __name__ == "__main__":
    main()
