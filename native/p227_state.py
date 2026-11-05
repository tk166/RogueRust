"""§227 (part 1): `ChoiceThen` 长出三种"选完再改它"的形态。

* `Copy { copies, into }` —— 复制从 §226 的 `PendingChoice::copies` 搬进变体里（"造几份"与
  "造到哪儿"是复制**这个词本身**的属性，不是问句的属性 ⇒ 让非法组合不可能被构造出来）；
* `Upgrade` —— 原地升级（Armaments）；
* `ToDrawPileTop` —— 放到抽牌堆顶（Warcry）。

外加两条公共小函数：升级后 id 的**唯一**拼法（`upgraded_id`）与它的长度校验。
"""
import io

STATE = 'kernel/rd-core/src/state.rs'


def rewrite(path, edits):
    src = io.open(path, encoding='utf-8').read()
    for old, new in edits:
        assert src.count(old) == 1, (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)


rewrite(STATE, [
    # 1) Copy 长载荷 + 两个新变体
    ('''    /// **复制**选中的牌（§226，Dual Wield）：原件**不动**，往手牌里造 [`PendingChoice::copies`] 份。
    ///
    /// 与 [`Self::ToHand`] 的区别是"搬"与"造"：那个把那一份**搬**过去（顺带给它一个每副本价格），
    /// 这个**造**新的 —— 新副本是印刷价（StS 的副本不是打折商品，所以 `Copies` 与 `cost_delta`
    /// 互斥由 `resolve_choice` 的上游那条判据守住）。
    Copy,
}''',
     '''    /// **复制**选中的牌（§226，Dual Wield / Nightmare）：原件**不动**，造 `copies` 份到 `into`。
    ///
    /// 与 [`Self::ToHand`] 的区别是"搬"与"造"：那个把那一份**搬**过去（顺带给它一个每副本价格），
    /// 这个**造**新的 —— 新副本是印刷价（StS 的副本不是打折商品，所以 `cost_delta` 对它
    /// 不适用，`resolve_choice` 上游那条判据守住）。
    ///
    /// §227：`copies` / `into` 从 `PendingChoice` 的字段搬进**变体本身**。理由是"造几份、造到哪儿"
    /// 是"复制"这个词的一部分：留在外面就要靠 `begin_choice` 校验"`then` 是 Copy 时 `copies` 非零"
    /// 这类外部不变量，而**能构造出来的非法状态迟早会被构造出来**。
    Copy {
        /// 每张选中的牌造几份（`>= 1`）。
        copies: u8,
        /// 副本落在哪个牌区（Dual Wield = 手牌，Nightmare = `SetAsidePile`）。
        into: CardZone,
    },
    /// **原地升级**选中的牌（§227，Armaments）：定义 id 变成 `<id>+`，牌**不动**。
    ///
    /// 内核只守**机械**那半（"`+` 只能加一次、id 不能超长"）；"这张牌有没有 `+` 行"是内容的
    /// 事，所以由发问的节点把候选**收窄**到有 `+` 行的牌（`upgrade_cards_node` 用的是同一条规则）。
    Upgrade,
    /// 把选中的牌放到**抽牌堆顶**（§227，Warcry）。
    ///
    /// `Top` 不是排版选择：`ZonePlacement::Top` 的注释写着"front is the draw top"，所以
    /// "下一张就抽它"与"塞进堆底"是两条不同的语义，内容不能靠顺序碰运气。
    ToDrawPileTop,
}'''),

    # 2) destination()
    ('''            // 副本进手牌；**原件不搬**（`resolve_from_pile` 的 `Copy` 分支在动第一张牌之前就
            // 分流出去了），所以这个返回值的唯一用途是给容量判据当"新卡落在哪儿"。
            Self::Copy => CardZone::Hand,
        }''',
     '''            // 副本落在 `into`（**原件不搬**）；这个返回值的用途是给容量判据当"新卡落在哪儿"。
            Self::Copy { into, .. } => into,
            // 升级**不动牌**（`resolve_from_pile` 的 `Upgrade` 分支在搬牌之前就分流出去了），
            // 这里填原处；它不会被当成搬迁目的地。
            Self::Upgrade => CardZone::Hand,
            Self::ToDrawPileTop => CardZone::DrawPile,
        }'''),

    # 3) PendingChoice 去掉 copies 字段
    ('''    /// 每张选中的牌**造几份副本**（§226）。只有 [`ChoiceThen::Copy`] 用得上。
    ///
    /// 其余 `then` 必须留 `0`，`begin_choice` **响亮拒绝** —— 静默忽略一个副本数，就是让
    /// "它复制了两份"变成"它复制了零份"，而零份也是一次成功的复制。
    pub copies: u8,
''', ''''''),

    # 4) begin_choice：副本数的自洽校验改成"变体自带"的那一条
    ('''        // §226：副本数只有 `Copy` 用得上，两个方向都要拒（"复制 0 份"是一次成功的空操作，
        // 那是最难发现的一种错）。
        if (choice.copies != 0) != (choice.then == ChoiceThen::Copy) {
            return Err(ChoiceError::CopiesNotApplicable);
        }''',
     '''        // §227：`copies` 已经在变体里了，所以只剩"0 份"这一种非法值 —— 它是一次**成功**的空
        // 操作，那是最难发现的一种错。
        if matches!(choice.then, ChoiceThen::Copy { copies: 0, .. }) {
            return Err(ChoiceError::CopiesNotApplicable);
        }'''),

    # 5) resolve_from_pile：Copy 分流 + Upgrade 分流 + 放置方向
    ('''        // §226：`Copy` 是"造"而不是"搬"—— 原件留在原处，所以它和下面的目的牌区容量判据
        // 是两件事（这里要的是**手牌的空位**，那要的是"要搬进去的那个区"）。分支放在
        // "一个字节都没改"这条线之前，两支各自保证自己全验证完再动手。
        if choice.then == ChoiceThen::Copy {
            return self.resolve_copy(choice, &slots[..picked]);
        }''',
     '''        // §226：`Copy` 是"造"而不是"搬"—— 原件留在原处，所以它和下面的目的牌区容量判据
        // 是两件事（这里要的是 `into` 的空位，那要的是"要搬进去的那个区"）。分支放在
        // "一个字节都没改"这条线之前，两支各自保证自己全验证完再动手。
        if let ChoiceThen::Copy { copies, into } = choice.then {
            return self.resolve_copy(choice, &slots[..picked], copies, into);
        }
        // §227：`Upgrade` 也不搬牌，只改那份副本的定义 id。
        if choice.then == ChoiceThen::Upgrade {
            return self.resolve_upgrade(choice, &slots[..picked]);
        }'''),

    ('''        // ---- 到这里为止一个字节都没改。----
        for &slot in &slots[..picked] {
            self.move_card(&choice.chooser, source, destination, slot, ZonePlacement::Bottom)?;''',
     '''        // §227：`ToDrawPileTop` 与其它"搬"只差**落在哪一头**（`Top` = 下一张就抽它）。
        let placement = match choice.then {
            ChoiceThen::ToDrawPileTop => ZonePlacement::Top,
            _ => ZonePlacement::Bottom,
        };

        // ---- 到这里为止一个字节都没改。----
        for &slot in &slots[..picked] {
            self.move_card(&choice.chooser, source, destination, slot, placement)?;'''),
])

# 6) resolve_copy 改签名 + 落区
src = io.open(STATE, encoding='utf-8').read()
old = '''    /// **复制**的答案（[`ChoiceThen::Copy`]，§226）。
    ///
    /// 语义：选中的每一张**留在原处**，往手牌里再造 [`PendingChoice::copies`] 份**同定义**的副本。'''
new = '''    /// **复制**的答案（[`ChoiceThen::Copy`]，§226/§227）。
    ///
    /// 语义：选中的每一张**留在原处**，往 `into` 再造 `copies` 份**同定义**的副本。'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    fn resolve_copy(
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
        }'''
new = '''    fn resolve_copy(
        &mut self,
        choice: PendingChoice,
        slots: &[CardSlot],
        copies: u8,
        into: CardZone,
    ) -> Result<ChoiceDone, ChoiceError> {
        let copies = usize::from(copies);
        if copies == 0 {
            return Err(ChoiceError::CopiesNotApplicable);
        }
        let picked = slots.len();
        let total = picked.saturating_mul(copies);
        {
            let Some(zones) = self.card_zones(&choice.chooser) else {
                return Err(ChoiceError::NotInSource);
            };
            if total > MAX_CARDS_PER_ZONE.saturating_sub(zones.count(into)) {
                return Err(ChoiceError::Capacity(CapacityError::Full(
                    Container::CardsInZone(into),
                )));
            }
        }'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''        for definition in &definitions[..picked] {
            for _ in 0..copies {
                self.create_card_instance(&choice.chooser, *definition, CardZone::Hand)?;
                created += 1;
            }
        }'''
new = '''        for definition in &definitions[..picked] {
            for _ in 0..copies {
                self.create_card_instance(&choice.chooser, *definition, into)?;
                created += 1;
            }
        }'''
assert src.count(old) == 1
src = src.replace(old, new)
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(src)

# 7) 两个新实体 + 升级 id 的**唯一**拼法
src = io.open(STATE, encoding='utf-8').read()
anchor = '''    /// 候选来源的答案（[`ChoiceSource::Offered`]，§161.5）。'''
assert src.count(anchor) == 1
impl = '''    /// **原地升级**的答案（[`ChoiceThen::Upgrade`]，§227，Armaments）。
    ///
    /// 语义：把每一张选中的牌的定义 id 换成 [`upgraded_id`]（`<id>+`），牌**不搬**。
    ///
    /// 内核只守**机械**那半：`+` 不能加两次、id 不能超长。**"这张牌有没有 `+` 行"是内容的事**，
    /// 由发问的节点把候选收窄（这里没有 `Content`，也不该为了这一件事把它拖进来）——
    /// 两条判据合起来才是完整规则，缺哪条都会让"升级了一张没有升级版的牌"变成一次静默成功。
    fn resolve_upgrade(
        &mut self,
        choice: PendingChoice,
        slots: &[CardSlot],
    ) -> Result<ChoiceDone, ChoiceError> {
        let picked = slots.len();
        let mut upgraded = [CardDefinitionId::EMPTY; MAX_CHOICE_OFFERED];
        if picked > upgraded.len() {
            return Err(ChoiceError::Count {
                picked,
                min: choice.min,
                max: choice.max,
            });
        }
        // ---- 先把新 id 全部算出来：一张算不出来就整体拒绝，一个字节都不改。----
        for (at, slot) in slots.iter().enumerate() {
            let Some(card) = self.card(*slot) else {
                return Err(ChoiceError::NotInSource);
            };
            upgraded[at] =
                upgraded_id(card.definition_id.as_str()).ok_or(ChoiceError::NotUpgradable)?;
        }
        for (at, slot) in slots.iter().enumerate() {
            let Some(card) = self.cards.as_mut_slice().get_mut(slot.index()) else {
                return Err(ChoiceError::NotInSource);
            };
            card.definition_id = upgraded[at];
        }
        self.choice = None;
        Ok(ChoiceDone {
            picked,
            drawn: 0,
        })
    }

    /// 候选来源的答案（[`ChoiceSource::Offered`]，§161.5）。'''
src = src.replace(anchor, impl)

# `upgraded_id` 放在 `CARD_COST_OVERRIDE_COUNTER` 附近（自由函数，两个模块共用）
anchor2 = '''/// 一次候选最多几张（StS 的三张；留到 8 是因为 Attack/Skill/Power 三瓶都要同一个数，
/// 而"三"写在三处的常量迟早只有一个被改）。'''
assert src.count(anchor2) == 1
helper = '''/// 一张牌的**升级版定义 id**：`<id>+`（本内容的约定，§195.7）。
///
/// 这是那个拼法的**唯一**实现：`exec::upgrade_cards_node`（按定义 id 批量升级）与
/// [`CombatState::resolve_upgrade`]（升级玩家选中的那张）都调它 —— 两处各写一遍 `push(b'+')`
/// 就是"同一个词表被两处认识"，迟早一处改成 `<id>+1` 而另一处没改。
///
/// 返回 `None` 的两种情形都是**拒绝**、不是"随便给个值"：
/// * id 已经以 `+` 结尾（升级过的不再升级）；
/// * `+` 之后超出 [`ID_CAP`]（装不下就会被截断成一个**别的** id，那是撞名）。
#[must_use]
pub fn upgraded_id(definition: &str) -> Option<CardDefinitionId> {
    let bytes = definition.as_bytes();
    if bytes.last() == Some(&b'+') || bytes.len() + 1 > ID_CAP {
        return None;
    }
    let mut buffer = [0u8; ID_CAP];
    buffer[..bytes.len()].copy_from_slice(bytes);
    buffer[bytes.len()] = b'+';
    CardDefinitionId::new(core::str::from_utf8(&buffer[..bytes.len() + 1]).ok()?).ok()
}

''' + anchor2
src = src.replace(anchor2, helper)

# ChoiceError::NotUpgradable
src = src.replace('''    /// 副本数与 `then` 不自洽（§226）：非 [`ChoiceThen::Copy`] 的问句带了非零 `copies`，或者
    /// [`ChoiceThen::Copy`] 的 `copies` 是 0。''', '''    /// §227：选中的牌**升级不了**（id 已经以 `+` 结尾，或者 `+` 之后超出容量）。
    ///
    /// 这是**内核能看见的那一半**规则；"这张牌有没有 `+` 行"由发问的节点收窄候选来保证。
    NotUpgradable,
    /// 副本数与 `then` 不自洽（§226）：[`ChoiceThen::Copy`] 的 `copies` 是 0。''')
src = src.replace('''            Self::CopiesNotApplicable => {''', '''            Self::NotUpgradable => f.write_str("the picked card cannot be upgraded any further"),
            Self::CopiesNotApplicable => {''')
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(src)

# 8) 去掉所有 `copies: 0,` 字面量（`CopiesNotApplicable` 的旧校验已删）
src = io.open(STATE, encoding='utf-8').read()
lines = [line for line in src.split('\n') if line.strip() != 'copies: 0,']
io.open(STATE, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
print('ok state')
