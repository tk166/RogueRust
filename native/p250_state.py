"""§250 内核（1/3）：`state.rs`

三件事：

1. **`CombatState.gold_gained`** —— 战斗里拿到的金币（`Hand of Greed`："If Fatal, gain 20 Gold"）。
   `gold_carried_away` 已经是"被偷走"的那本账（§201），这是**反向**的第二本账；两本都在
   `fight_end` 被运行层读，所以它们必须**分开**：一个加、一个减。
   ⚠️ 与 `gold_carried_away` 同一条纪律：**不进 `hash_golden`** —— 参考资料里没有这个字段，
   而 `hash_golden` 是逐字节复刻的指纹（`state.rs` 里那段"七个字段"的注释）。

2. **`ChoiceThen::ToHandFree` / `ToDrawPileBottomFree`** —— `Discovery`（"选一张加进手牌，
   它这次免费"）与 `Forethought`（"放到抽牌堆**底**，它在你打出前免费"）。
   为什么不做成"给 `ToHand` 传一个 `cost_delta = 0`"：那个参数是**调用方**（页面/药水）算的，
   而"这张牌自己承诺免费"是卡牌节目的语义，必须能在内核里独立成立 —— 否则同一个问句由
   `Discovery` 发起时，页面得额外知道"这次要传 0"。两个变体各自带完整语义，页面上是两句话。

3. **`create_card_instance_at`** —— 造副本时能指定落**头**还是落**尾**。
   `Pride`（"put a copy of this card **on top of** your draw pile"）要 `Top`；`push_card`
   一直是追加（`Bottom`），而"牌堆头"= 索引 0。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/state.rs'

PATCHES = [
    # ---- 1) 金币账 ----------------------------------------------------------
    ('''    pub gold_carried_away: i32,''',
     '''    pub gold_carried_away: i32,
    /// §250：**战斗里赚到的金币**（`Hand of Greed` 的 "If Fatal, gain 20 Gold"）。
    ///
    /// 与 [`Self::gold_carried_away`] 是**两本独立的账**，方向相反：那一本是"被偷走、要减"，
    /// 这一本是"赚到手、要加"。合成一个 `gold_delta` 会让"偷 20 又赚 20"变成 0 —— 那在
    /// 页面显示上看起来完全正常，而玩家的钱少了 20。
    ///
    /// 由内容节点 `node.gainGold` 累加，运行层在 `fight_end` 读一次（`rd-wasm` 的桥）。
    /// ⚠️ **不进 `hash_golden`**：参考实现里没有这个字段，而那个指纹是逐字节复刻的。
    pub gold_gained: i32,'''),
    # 两处初始化（`CombatState::new` 与它的 tripwire 探针）都要加，所以两条分开写。
    ('''        vacated_seat: None,
        gold_carried_away: 0,''',
     '''        vacated_seat: None,
        gold_carried_away: 0,
        gold_gained: 0,'''),
    ('''            vacated_seat: None,
            gold_carried_away: 0,''',
     '''            vacated_seat: None,
            gold_carried_away: 0,
            gold_gained: 0,'''),
    # ---- 2) 两个新的 ChoiceThen --------------------------------------------
    ('''    /// 把选中的牌放到**抽牌堆顶**（§227，Warcry）。''',
     '''    /// §250：**拿进手牌，并且这一份的价格就是 0**（`Discovery`）。
    ///
    /// 与 [`Self::ToHand`] 的差别只有一点，但那一点必须由**内核**保证：`ToHand` 的价格来自
    /// 调用方传的 `cost_delta`（药水/页面算的），而 `Discovery` 是一张**卡**发起的问句 ——
    /// 页面没有任何理由知道"这次要传 0"。所以"免费"写进变体本身：
    /// 落手牌 + 把 `standard.card_cost_override` 设成 0。
    ///
    /// ⚠️ 与 StS 的差别（与 [`CARD_COST_DELTA_COUNTER`] 同一条，写明了的不对称）：StS 的
    /// "costs 0 **this turn**" 在回合结束过期；我们把"免费"记在**那一份副本**上、由出牌消费。
    ToHandFree,
    /// §250：**放到抽牌堆底，并且这一份的价格就是 0**（`Forethought`）。
    ///
    /// 为什么是"底"而不是"顶"：StS 的原文是 `the bottom of your draw pile` —— 那是"这一局
    /// 别指望很快再见到它"的意思。`ToDrawPileTop`（Warcry）已经占住"顶"那个语义，两者不可互换。
    ToDrawPileBottomFree,
    /// 把选中的牌放到**抽牌堆顶**（§227，Warcry）。'''),
    ('''            Self::ToDrawPileTop => CardZone::DrawPile,''',
     '''            Self::ToDrawPileTop => CardZone::DrawPile,
            // §250：两个 `Free` 变体各自落在自己的牌区；价格不是牌区的一部分。
            Self::ToHandFree => CardZone::Hand,
            Self::ToDrawPileBottomFree => CardZone::DrawPile,'''),
    # ---- 3) resolve_choice：Free 变体写绝对价格 ----------------------------
    ('''        if choice.then == ChoiceThen::ToHand && cost_delta != 0 {
            for &slot in &slots[..picked] {''',
     '''        // §250：`Free` 变体要占一个 mark counter（`card_cost_override`），所以与 `ToHand`
        // 走同一条容量预检 —— 否则"搬完才发现那张牌的计数器表满了"。
        let writes_a_price = matches!(
            choice.then,
            ChoiceThen::ToHandFree | ChoiceThen::ToDrawPileBottomFree
        ) || (choice.then == ChoiceThen::ToHand && cost_delta != 0);
        if writes_a_price {
            for &slot in &slots[..picked] {'''),
    ('''            // §161.4: the per-copy price rides **on the card**, so it travels with it through the
            // hand and the discard pile -- and `play.rs` zeroes it once the play is paid for.
            if choice.then == ChoiceThen::ToHand && cost_delta != 0 {
                self.write_price(slot, cost_delta)?;
            }''',
     '''            match choice.then {
                ChoiceThen::ToHand if cost_delta != 0 => self.write_price(slot, cost_delta)?,
                // §250：`Free` 变体写的是**绝对**价格 0（`standard.card_cost_override`），
                // 与 `createRandomCardInstance{CostZero}` 同一格 —— 它在 delta 之前生效，
                // 也正是"这一份的价格就是 0"要的那一格。
                ChoiceThen::ToHandFree | ChoiceThen::ToDrawPileBottomFree => {
                    let key = CounterId::new(CARD_COST_OVERRIDE_COUNTER)
                        .map_err(|_| ChoiceError::NotInSource)?;
                    let Some(card) = self.cards.as_mut_slice().get_mut(slot.index()) else {
                        return Err(ChoiceError::NotInSource);
                    };
                    card.set_mark_counter(key, 0)
                        .map_err(ChoiceError::Capacity)?;
                }
                _ => {}
            }'''),
    # ---- 4) 带位置的造牌 ---------------------------------------------------
    ('''    pub fn create_card_instance(
        &mut self,
        owner: &CombatantId,
        definition: CardDefinitionId,
        zone: CardZone,
    ) -> StateResult<CardSlot> {''',
     '''    pub fn create_card_instance(
        &mut self,
        owner: &CombatantId,
        definition: CardDefinitionId,
        zone: CardZone,
    ) -> StateResult<CardSlot> {
        self.create_card_instance_at(owner, definition, zone, ZonePlacement::Bottom)
    }

    /// §250：同 [`Self::create_card_instance`]，但能指定落在牌区的**哪一头**。
    ///
    /// `Pride`（"put a copy of this card **on top of** your draw pile"）要 `Top`。
    /// 默认那条走 `Bottom`（追加），因为那是参考 `MoveCardToZone(placement = Bottom)` 的默认值 ——
    /// 只有一个调用方需要"头"，所以**不改**老入口的含义。
    pub fn create_card_instance_at(
        &mut self,
        owner: &CombatantId,
        definition: CardDefinitionId,
        zone: CardZone,
        placement: ZonePlacement,
    ) -> StateResult<CardSlot> {'''),
    ('''        let slot = self.push_card(owner, zone, CardInstance::new(id, definition))?;
        self.next_card_instance_number = number.saturating_add(1);
        Ok(slot)''',
     '''        let slot = self.push_card_at(owner, zone, CardInstance::new(id, definition), placement)?;
        self.next_card_instance_number = number.saturating_add(1);
        Ok(slot)'''),
    # ---- 5) push_card 的带位置版本 ----------------------------------------
    ('''    pub fn push_card(
        &mut self,
        owner: &CombatantId,
        zone: CardZone,
        card: CardInstance,
    ) -> StateResult<CardSlot> {''',
     '''    pub fn push_card(
        &mut self,
        owner: &CombatantId,
        zone: CardZone,
        card: CardInstance,
    ) -> StateResult<CardSlot> {
        self.push_card_at(owner, zone, card, ZonePlacement::Bottom)
    }

    /// §250：[`Self::push_card`] + 落在**哪一头**（`Top` = 索引 0 = 抽牌堆头）。
    pub fn push_card_at(
        &mut self,
        owner: &CombatantId,
        zone: CardZone,
        card: CardInstance,
        placement: ZonePlacement,
    ) -> StateResult<CardSlot> {'''),
    ('''        zones.push_slot(zone, slot)?;''',
     '''        zones.push_slot_at(zone, slot, placement)?;'''),
]


def main():
    src = io.open(PATH, encoding='utf-8').read()
    for old, new in PATCHES:
        assert src.count(old) == 1, ('anchor', old[:60], src.count(old))
        src = src.replace(old, new)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs patched (%d edits)' % len(PATCHES))


main()
