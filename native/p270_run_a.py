"""§270 基建：`CardKind` / `PoolCard{kind,upgraded}` / `push_card` 重写 / 两个运行期计数器
/ `RELIC_SECOND_HALVES` / 遗物行。

## 为什么 `push_card` 要拿到整张 `PoolCard` 而不是 id

三个蛋的规则是"加**这种类型**的牌 ⇒ 换成它的 `+` 行"，`omamori`/`darkstone_periapt` 的规则是
"**诅咒**"。类型在内容里是 **tag**（`attack`/`skill`/`power`/`curse`），运行层原本看不到它们 ——
所以把"这张牌是什么"放进 [`PoolCard`]，而不是让 13 个调用点各自判断。

`+` 行的解析**仍然只有一处**（`upgraded_id`，A12 用的就是它）：`full_pool` 在池子这一层
把它填进 `PoolCard::upgraded`，而不是让 `push_card` 自己拼 `id + "+"`
（拼错了就是把一张内容不认识的牌塞进牌组，而那种错**不会**报错）。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


POOL_CARD = '''/// §270：**卡牌的类型**（内容里是 tag：`attack` / `skill` / `power` / `curse` / `status`）。
///
/// 三个蛋要它（按类型升级），`omamori` / `darkstone_periapt` 也要它（只认诅咒）。
/// 与 [`Rarity`] 是两件事：稀有度决定"多常出现"，类型决定"它是什么"。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum CardKind {
    Attack,
    Skill,
    Power,
    Status,
    Curse,
    /// 类型未知（开局牌组、测试里的裸 id）。**三个蛋与两条诅咒规则都不会对它生效** ——
    /// 这是刻意的：宁可"这件遗物对这张牌没反应"，也不要按名字猜类型。
    Other,
}

/// A card as the reward roll sees it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PoolCard<'a> {
    /// The definition id.
    pub id: &'a str,
    /// Its rarity, from the content.
    pub rarity: Rarity,
    /// §270：its **type** (the content's `attack`/`skill`/`power`/`curse` tag).
    pub kind: CardKind,
    /// §270：its `+` row, if the content has one. Resolved by [`upgraded_id`] in `full_pool`,
    /// **not** by string concatenation at the point of use.
    pub upgraded: Option<&'a str>,
}

impl<'a> PoolCard<'a> {
    /// A card known only by id: `Basic` rarity, unknown type, no `+` row.
    ///
    /// For the starting deck and for tests. The three eggs and the two curse relics stay inert on
    /// these -- and they must: a run's starting deck is Strikes and Defends, so nothing that looks
    /// at types can fire before the first relic is picked up.
    #[must_use]
    pub const fn plain(id: &'a str) -> Self {
        Self { id, rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None }
    }
}
'''

PUSH_CARD = '''    /// Add a card to the deck. Past [`MAX_RUN_DECK`] this is an error.
    ///
    /// **The single add point** (§270): every way a card can arrive -- a reward, the merchant, an
    /// event, `Dream Catcher` -- goes through here, so the add-card relics fire exactly once:
    ///
    /// | 遗物 | 规则 | 在这一步做什么 |
    /// |---|---|---|
    /// | `omamori` | 挡掉接下来 2 个诅咒 | 诅咒且还有次数 ⇒ **不加入**、次数 -1 |
    /// | `darkstone_periapt` | 得到诅咒 ⇒ 上限 +6 | 加入之后加上限 |
    /// | `molten_egg` / `toxic_egg` / `frozen_egg` | 加该类型的牌 ⇒ 升级 | 有 `+` 行就换成 `+` 行 |
    /// | `ceramic_fish` | 加任何牌 ⇒ +9 金币 | 加入之后走 `adjust_gold` |
    ///
    /// ⚠️ **顺序是规则的一部分**：`omamori` 在**最前**（被挡掉的诅咒不算"得到"，
    /// 所以 `darkstone_periapt` 不该加血、`ceramic_fish` 也不该给钱）。这条不是"顺手写前一点" ——
    /// 换一下顺序，`omamori` 就会变成一个**付 6 点上限加 9 金币**的遗物。
    pub fn push_card(&mut self, card: PoolCard<'_>) -> Result<(), RunError> {
        let id = RunId::new(card.id).map_err(|_| RunError::BadId)?;
        let slot = self.deck_len as usize;
        if slot >= MAX_RUN_DECK {
            return Err(RunError::Capacity);
        }
        // §270：`omamori` —— "Negate the next 2 Curses you obtain"。被挡掉 ⇒ **什么都不加**，
        // 但这是**成功**（玩家没有做错事，诅咒只是没进牌组）。
        if card.kind == CardKind::Curse && self.omamori_charges > 0 {
            self.omamori_charges -= 1;
            return Ok(());
        }
        // §270：三个蛋 —— 类型对上且有 `+` 行就换成升级版。没有 `+` 行的牌保持原样（内容的事）。
        let chosen = if self.upgrades_added_card(card.kind) {
            match card.upgraded {
                Some(upgraded) => RunId::new(upgraded).map_err(|_| RunError::BadId)?,
                None => id,
            }
        } else {
            id
        };
        self.deck[slot] = chosen;
        self.deck_len += 1;
        // §270：`darkstone_periapt` —— "Whenever you obtain a Curse, increase your Max HP by 6"。
        // 上限涨了，当前血量**不跟**（wiki 只说上限；`Pear` 那种"也回等量"是另一件遗物的写法）。
        if card.kind == CardKind::Curse {
            if let Some(RelicEffect::CurseMaxHealthUp(amount)) =
                self.first_relic_effect_of(RelicEffect::CurseMaxHealthUp(6))
            {
                self.health_max += amount;
            }
        }
        // §270：`ceramic_fish` —— "Whenever you add a card to your deck, gain 9 Gold"。
        // 走 `adjust_gold`：`ectoplasm` 该拦就拦、`bloody_idol` 该回血就回血 —— 那两条规则
        // 只认"金币真的变了"这一件事，不该在第二个地方再写一遍。
        if let Some(RelicEffect::CardAddGold(amount)) =
            self.first_relic_effect_of(RelicEffect::CardAddGold(9))
        {
            self.adjust_gold(amount);
        }
        Ok(())
    }

    /// §270：这张牌进牌组时要不要换成 `+` 行（三个蛋）。
    ///
    /// 一条判据回答一个问题："有没有**哪个**蛋管这个类型"。所以它遍历遗物而不是匹配三条规则 ——
    /// 将来再加第四个蛋（StS 没有，但内容可以）时，这里不用动。
    fn upgrades_added_card(&self, kind: CardKind) -> bool {
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::UpgradeAddedCard(wanted)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                if wanted == kind {
                    return true;
                }
            }
        }
        false
    }

    /// §270：某件遗物给的某个变体，**取它带的参数**。
    ///
    /// `holds_relic_effect` 只能回答"有没有完全等于这个值的一条"，而 `push_card` 需要的是
    /// "**多少**"（+6 上限、+9 金币）。⚠️ 这里匹配的是**变体的形状**，所以参数必须与表里一致 ——
    /// 传错常量会得到一个"看起来没生效"的遗物。判据钉住了两条真实数字。
    fn first_relic_effect_of(&self, wanted: RelicEffect) -> Option<RelicEffect> {
        for slot in 0..self.relics_len as usize {
            if let Some(effect) = Self::relic_effect(self.relics[slot].as_str()) {
                let same_shape = match (effect, wanted) {
                    (RelicEffect::CurseMaxHealthUp(_), RelicEffect::CurseMaxHealthUp(_)) => true,
                    (RelicEffect::CardAddGold(_), RelicEffect::CardAddGold(_)) => true,
                    _ => false,
                };
                if same_shape {
                    return Some(effect);
                }
            }
        }
        None
    }
'''

VARIANTS = '''    /// §270：`omamori` —— 拾取时给 2 次"挡诅咒"。
    Omamori(u8),
    /// §270：`darkstone_periapt` —— 得到诅咒 ⇒ 上限 +6。
    CurseMaxHealthUp(i32),
    /// §270：`ceramic_fish` —— 每加一张牌 +9 金币。
    CardAddGold(i32),
    /// §270：`molten_egg`(Attack) / `toxic_egg`(Skill) / `frozen_egg`(Power) ——
    /// 加这个类型的牌时换成 `+` 行。
    UpgradeAddedCard(CardKind),
    /// §270：`bloody_idol` —— 每次**得到**金币回 5 血。
    GoldGainHeal(i32),
    /// §270：`ectoplasm` —— 不能再得到金币（正增量一律变 0）。
    NoGoldGain,
    /// §270：`maw_bank` —— 每爬一层 +12 金币；在商店花过钱之后失效。
    FloorClimbGold(i32),
    /// §270：`smiling_mask` —— 删牌服务**固定** 50 金币。
    RemovePriceFlat(i32),
    /// §270：`membership_card` —— 所有商品打折 `percent`（50 = 半价）。
    ShopDiscountPercent(i32),'''

ROWS = '''            // §270：加牌类（全部落在 `push_card` 一个点上）。
            "omamori" => Some(RelicEffect::Omamori(2)),
            "darkstone_periapt" => Some(RelicEffect::CurseMaxHealthUp(6)),
            "ceramic_fish" => Some(RelicEffect::CardAddGold(9)),
            "molten_egg" => Some(RelicEffect::UpgradeAddedCard(CardKind::Attack)),
            "toxic_egg" => Some(RelicEffect::UpgradeAddedCard(CardKind::Skill)),
            "frozen_egg" => Some(RelicEffect::UpgradeAddedCard(CardKind::Power)),
            // §270：金币/商店类。
            "bloody_idol" => Some(RelicEffect::GoldGainHeal(5)),
            "ectoplasm" => Some(RelicEffect::NoGoldGain),
            "maw_bank" => Some(RelicEffect::FloorClimbGold(12)),
            "smiling_mask" => Some(RelicEffect::RemovePriceFlat(50)),
            "membership_card" => Some(RelicEffect::ShopDiscountPercent(50)),
            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。'''

SECOND_HALVES = '''/// §270：一件遗物的**第二半**。
///
/// [`RunState::relic_effect`] 只返回**一个**变体，而有两件遗物各自要做两件事：
///
/// | 遗物 | 第一半（在 `relic_effect` 里） | 第二半（在这张表里） |
/// |---|---|---|
/// | `busted_crown` | 每回合 +1 能量的载体 | 奖励卡数 -2 |
/// | `ectoplasm` | 不能再得到金币 | 每回合 +1 能量的载体 |
///
/// 两个消费者（[`RunState::combat_bonus_for`] / [`RunState::reward_card_count`]）各自挑自己认识的
/// 变体、忽略其余 —— 所以这张表**只有一处**，而不是"每个消费者一张"。
const RELIC_SECOND_HALVES: [(&str, RelicEffect); 2] = [
    ("busted_crown", RelicEffect::RewardCardDelta(-2, KindMask::ALL)),
    ("ectoplasm", RelicEffect::StartCombatStatus("standard.ectoplasm", 1)),
];'''


def main():
    src = io.open(P, encoding='utf-8').read()

    # ---- ① PoolCard + CardKind
    src = patch(src, '''/// A card as the reward roll sees it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PoolCard<'a> {
    /// The definition id.
    pub id: &'a str,
    /// Its rarity, from the content.
    pub rarity: Rarity,
}''', POOL_CARD, 'PoolCard')

    # ---- ② 新变体
    src = patch(src, '''    /// §269：精英战敌人血量百分比修正（`preserved_insect`：-25）。''',
                VARIANTS + '''
    /// §269：精英战敌人血量百分比修正（`preserved_insect`：-25）。''',
                'variants')

    # ---- ③ 第二半表（替换 §269 的 EXTRA_REWARD_CARD_DELTAS）
    src = patch(src, '''/// §269：奖励卡数的**第二半**（见 [`RunState::reward_card_count`]）。
///
/// 只有一件：`busted_crown` 的 "card rewards have 2 less cards"（它的第一半 —— 每回合 +1 能量
/// —— 走 `relic_effect`）。表里用**遗物 id**，所以查的时候要经过 `relic_effect_static`。
const EXTRA_REWARD_CARD_DELTAS: [(&str, i32); 1] = [("busted_crown", -2)];
''', SECOND_HALVES + '\n', 'second halves')

    # ---- ④ 遗物行
    src = patch(src, '''            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。''',
                ROWS, 'rows')

    # ---- ⑤ push_card 重写
    src = patch(src, '''    pub fn push_card(&mut self, definition_id: &str) -> Result<(), RunError> {
        let id = RunId::new(definition_id).map_err(|_| RunError::BadId)?;
        let slot = self.deck_len as usize;
        if slot >= MAX_RUN_DECK {
            return Err(RunError::Capacity);
        }
        self.deck[slot] = id;
        self.deck_len += 1;
        Ok(())
    }
''', PUSH_CARD, 'push_card')

    # ---- ⑥ 两个运行期计数器
    src = patch(src, '''    /// §259：`Recall` 拿到的红钥匙（Act 4 的门票）。一个布尔就够 —— wiki 只有"拿没拿"。
    ruby_key: bool,''',
                '''    /// §259：`Recall` 拿到的红钥匙（Act 4 的门票）。一个布尔就够 —— wiki 只有"拿没拿"。
    ruby_key: bool,
    /// §270：`omamori` 还剩几次"挡诅咒"（0..=2）。**不是**"有几个诅咒"：这是遗物自己的计数器，
    /// 与牌组里有没有诅咒无关。
    omamori_charges: u8,
    /// §270：`maw_bank` 已经在商店花过钱 ⇒ 不再给爬层金币（wiki："No longer works when you spend
    /// any Gold at a shop"）。布尔就够 —— wiki 只有"失效没失效"，没有次数。
    maw_bank_broken: bool,''',
                'fields')

    src = patch(src, '''            girya_lifts: 0,
            ruby_key: false,''',
                '''            girya_lifts: 0,
            ruby_key: false,
            omamori_charges: 0,
            maw_bank_broken: false,''',
                'field init')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs: infra batch written')


main()
