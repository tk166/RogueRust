"""§274 拾取类 7 件：`push_relic` 收池子 + 拾取效果 + "欠着的牌组选择"。

## wiki 原文（离线 `native/wiki_relics/relics_data.lua.txt`）

| 遗物 | 稀有度 | 原文 |
|---|---|---|
| Old Coin | Rare | "Upon pickup, gain 300 Gold." |
| Lee's Waffle | Shop | "Upon pickup, raise your Max HP by 7 and heal all of your HP." |
| War Paint | Common | "Upon pick up, Upgrade 2 random Skills." |
| Whetstone | Common | "Upon pickup, Upgrade 2 random Attacks." |
| Astrolabe | Boss | "Upon pickup, Transform 3 cards, then Upgrade them." |
| Pandora's Box | Boss | "Upon pickup, Transform all Strike and Defend cards." |
| Empty Cage | Boss | "Upon pickup, remove 2 cards from your deck." |

## 为什么 `push_relic` 现在要卡池

四件要看**牌的类型**（Attack/Skill）与**`+` 行**（升级/改造的目标），而运行层只存牌 id。
所以卡池从调用方流进来 —— 与 §270 的 `push_card(PoolCard)` 同一条纪律：内容的事，
在**有内容的那一层**解析，运行层不猜 `id + "+"`。

## 两件"要玩家选"的（Astrolabe / Empty Cage）

它们在 StS 里是一个**选择屏**。我们的 `pending` 是**一个槽**，而且它有"一个流程一个写者"的纪律
（奖励屏/宝箱/事件各写一次），所以在 `push_relic` 里直接改 `pending` 会把玩家正看着的那一屏
顶掉（尤其是"打完 Boss 拿 Boss 遗物，然后还想拿卡牌奖励"这条真实路径）。

所以它们走**另一个**通道：`pickup_change` + `pickup_picks`（"欠着几次牌组编辑"），
`pending` 一个字节都不动。页面在 `pickup_picks > 0` 时优先画选择面板，选完回到原来那一屏。
"""
import io
import re

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


VARIANTS = '''    /// §274：`old_coin` —— 拾取时 +300 金币。
    PickupGold(i32),
    /// §274：`lee's_waffle` —— 拾取时上限 +7、**回满血**。
    PickupMaxHealthAndHealAll(i32),
    /// §274：`war_paint`(Skill) / `whetstone`(Attack) —— 拾取时随机升级 2 张**该类型**的牌。
    PickupUpgradeRandom(CardKind, u8),
    /// §274：`pandoras_box` —— 拾取时把牌组里**所有** Strike / Defend 改造掉。
    PickupTransformStaples,
    /// §274：`astrolabe` —— 拾取时改造 3 张（玩家选），**然后**升级它们。
    PickupPick(DeckChange, u8),'''

ROWS = '''            // §274：**拾取类**（全部落在 `push_relic` 的副作用区）。
            "old_coin" => Some(RelicEffect::PickupGold(300)),
            "lee's_waffle" => Some(RelicEffect::PickupMaxHealthAndHealAll(7)),
            "war_paint" => Some(RelicEffect::PickupUpgradeRandom(CardKind::Skill, 2)),
            "whetstone" => Some(RelicEffect::PickupUpgradeRandom(CardKind::Attack, 2)),
            "pandoras_box" => Some(RelicEffect::PickupTransformStaples),
            "astrolabe" => Some(RelicEffect::PickupPick(DeckChange::TransformAndUpgrade, 3)),
            "empty_cage" => Some(RelicEffect::PickupPick(DeckChange::Remove, 2)),
            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。'''

BODY = '''    /// Add a relic. Past [`MAX_RUN_RELICS`] this is an error.
    ///
    /// **The single grant point** (§145): every way a relic can arrive -- chest, shop, elite reward,
    /// an event's `relic:<id>` -- goes through here, so three things happen exactly once:
    ///
    /// 1. an **unimplemented** relic is refused ([`RunError::UnsupportedRelic`]) while the player is
    ///    still looking at whatever handed it over, instead of at the end of the next fight;
    /// 2. the relic's **grant-time** effect fires (`MaxHealthUp` / `HealUp` / §274 的七件拾取类);
    /// 3. it enters the belt.
    ///
    /// Doing (2) at the call sites instead would mean four copies of "and then Pear's max HP goes
    /// up", which is how a relic comes to work in a chest but not in a shop.
    ///
    /// §274：`pool` 是**卡池**。四件拾取类遗物要看牌的类型（Attack/Skill）与 `+` 行，而运行层
    /// 只存牌 id —— 与 `push_card(PoolCard)` 同一条纪律：内容的事在有内容的那一层解析。
    pub fn push_relic(
        &mut self,
        relic_id: &str,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        let Some(effect) = Self::relic_effect(relic_id) else {
            return Err(RunError::UnsupportedRelic {
                index: self.relics_len,
            });
        };
        let id = RunId::new(relic_id).map_err(|_| RunError::BadId)?;
        let slot = self.relics_len as usize;
        if slot >= MAX_RUN_RELICS {
            return Err(RunError::Capacity);
        }
        match effect {
            // §270：`omamori` —— 拾取时给 2 次"挡诅咒"。
            RelicEffect::Omamori(charges) => self.omamori_charges = charges,
            RelicEffect::MaxHealthUp(amount) => {
                self.health_max += amount;
                // The current HP follows the maximum up — StS's "raise your max HP" always heals
                // you by the same amount.
                self.adjust_health(amount);
            }
            // §274：`old_coin` —— +300 金币。走 `adjust_gold`，所以 `ectoplasm` 该拦就拦、
            // `bloody_idol` 该回血就回血。
            RelicEffect::PickupGold(amount) => self.adjust_gold(amount),
            // §274：`lee's_waffle` —— 上限 +7 **且**回满。两件事分开写：`MaxHealthUp` 只回
            // "和上限一样多"的那 7 点，而 wiki 说的是 "heal **all** of your HP"。
            RelicEffect::PickupMaxHealthAndHealAll(amount) => {
                self.health_max += amount;
                self.health = self.health_max;
            }
            // §274：`war_paint` / `whetstone` —— 随机升级 2 张**该类型**的牌。
            // 只动"有 `+` 行、且还没升级"的牌：升级一张已经升级的牌是空操作，
            // 而把它的名额用掉就等于"随机升级 2 张"却什么都没发生。
            RelicEffect::PickupUpgradeRandom(kind, count) => {
                let mut candidates = [0u8; MAX_RUN_DECK];
                let mut found = 0usize;
                for index in 0..self.deck_len as usize {
                    let card = self.deck[index].as_str();
                    let Some(facts) = pool.iter().find(|entry| entry.id == card) else {
                        continue;
                    };
                    if facts.kind == kind && facts.upgraded.is_some() {
                        candidates[found] = index as u8;
                        found += 1;
                    }
                }
                // 只升级 `count` 张，用**这个**随机流（拾取是奖励的一种）。
                let mut remaining = found;
                let mut picked = 0u8;
                let mut pool_indexes = [0u8; MAX_RUN_DECK];
                for slot in 0..found {
                    pool_indexes[slot] = candidates[slot];
                }
                while picked < count && remaining > 0 {
                    let roll = self.rng.roll(RunStream::Reward, remaining as u32)? as usize;
                    let index = pool_indexes[roll] as usize;
                    self.upgrade_at(index, pool)?;
                    // 把用掉的那个换到尾部，然后缩小窗口（不放回抽样）。
                    pool_indexes[roll] = pool_indexes[remaining - 1];
                    remaining -= 1;
                    picked += 1;
                }
            }
            // §274：`pandoras_box` —— 把**所有** Strike / Defend 改造掉。
            // "Strike / Defend" 按**内容 id 的前缀**认（`strike` / `defend`，含它们的 `+` 行）：
            // 这是内容自己的命名，不是我们在运行层编的规则 —— 所以两条 id 写在这里而不是猜。
            RelicEffect::PickupTransformStaples => {
                let mut index = 0usize;
                while index < self.deck_len as usize {
                    let card = self.deck[index].as_str().trim_end_matches('+');
                    if card == STAPLE_STRIKE || card == STAPLE_DEFEND {
                        self.apply_deck_change(DeckChange::Transform, index, pool)?;
                    }
                    index += 1;
                }
            }
            // §274：`astrolabe` / `empty_cage` —— **欠着**几次牌组编辑，由页面来问。
            // ⚠️ 这里**不动** `pending`：它属于正在进行的那个流程（奖励屏/宝箱/事件），
            // 抢过来会把玩家正看着的那一屏顶掉。
            RelicEffect::PickupPick(change, picks) => {
                self.pickup_change = Some(change);
                self.pickup_picks = picks;
            }
'''

FIELDS = '''    /// §272：`tiny_chest` 已经数到第几个 `?` 房（0..`TINY_CHEST_ROOMS`）。只在这件遗物在
    /// 身上时增长；换幕归零（与三条概率同一个理由）。
    tiny_chest_rooms: u8,
    /// §274：拾取时**欠着**的牌组编辑（`empty_cage` = 移除 2 张、`astrolabe` = 改造 3 张）。
    ///
    /// 为什么不是 `Pending` 的一个变体：`pending` 是"**这个节点**要什么"，一个流程一个写者。
    /// 而拾取可能发生在**另一个屏开着的时候**（打完 Boss 的奖励屏、宝箱），把 `pending` 抢过来
    /// 会把那一屏顶掉 —— 玩家会丢掉还没拿的卡牌奖励。所以欠的这几步走自己的通道。
    pickup_change: Option<DeckChange>,
    pickup_picks: u8,'''

PICK_API = '''    /// §274：还欠几次"拾取时的牌组编辑"（0 = 不欠）。
    #[must_use]
    pub const fn pickup_picks(&self) -> u8 {
        self.pickup_picks
    }

    /// §274：欠的是哪一种编辑（`Remove` = 移除、`Transform` = 改造、`TransformAndUpgrade` = 改造并升级）。
    #[must_use]
    pub const fn pickup_change(&self) -> Option<DeckChange> {
        self.pickup_change
    }

    /// §274：**兑现一次**拾取时的牌组编辑。
    ///
    /// 与 `pick_event_card` 的区别：不走 `pending`、**不 `mark_resolved`** —— 节点是那个流程的事
    /// （宝箱要 `leave`、奖励屏要 `skip_reward`），这里只还欠着的那一步。
    pub fn pickup_card(&mut self, index: usize, pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        let Some(change) = self.pickup_change else {
            return Err(RunError::WrongPhase);
        };
        // ⚠️ 先验后改：`apply_deck_change` 里的拒绝（越界 / Ascender's Bane / 没有 `+` 行）
        // 必须发生在 `pickup_picks` 递减**之前**，否则一次被拒的点击会白白吃掉一次额度。
        self.apply_deck_change(change, index, pool)?;
        self.pickup_picks = self.pickup_picks.saturating_sub(1);
        if self.pickup_picks == 0 {
            self.pickup_change = None;
        }
        Ok(())
    }

'''


def main():
    src = io.open(P, encoding='utf-8').read()

    # ① 新变体
    src = patch(src, '''    /// §273：`the_courier` —— 商人**补货**（买走一格就补一格）。''',
                VARIANTS + '''
    /// §273：`the_courier` —— 商人**补货**（买走一格就补一格）。''', 'variants')

    # ② 遗物行
    src = patch(src, '            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。',
                ROWS, 'rows')

    # ③ push_relic 收池子 + 拾取副作用
    start = src.index('    /// Add a relic. Past [`MAX_RUN_RELICS`] this is an error.')
    end = src.index('            RelicEffect::HealUp(amount) =>', start)
    src = src[:start] + BODY + '            ' + src[end:]
    # 去掉旧的 doc 重复段（上面 BODY 已经写全），保留原来的 HealUp 之后的内容

    # ④ 两个字段 + 初始化
    src = patch(src, '''    /// §272：`tiny_chest` 已经数到第几个 `?` 房（0..`TINY_CHEST_ROOMS`）。只在这件遗物在
    /// 身上时增长；换幕归零（与三条概率同一个理由）。
    tiny_chest_rooms: u8,''', FIELDS, 'fields')
    src = patch(src, '''            unknown_room: UnknownRoom::Unresolved,
            tiny_chest_rooms: 0,''',
                '''            unknown_room: UnknownRoom::Unresolved,
            tiny_chest_rooms: 0,
            pickup_change: None,
            pickup_picks: 0,''', 'field init')

    # ⑤ pickup API（放在 `pick_event_card` 之前）
    src = patch(src, '    pub fn pick_event_card(', PICK_API + '    pub fn pick_event_card(', 'pickup api')

    # ⑥ `DeckChange::TransformAndUpgrade`
    src = patch(src, '''    /// Remove it and grant a random card from the pool.
    Transform,''',
                '''    /// Remove it and grant a random card from the pool.
    Transform,
    /// §274：`astrolabe` —— 改造，**然后**升级改造出来的那张（wiki："Transform 3 cards, then
    /// Upgrade them"）。一个变体而不是"两次编辑"：两次编辑之间那张牌可能已经不在原位。
    TransformAndUpgrade,''', 'deck change variant')

    # ⑦ 两个常量（Strike/Defend 的 id）
    src = patch(src, '/// §272：`?` 房三条基础概率',
                '''/// §274：`pandoras_box` 认的两个"基础牌" id（内容的命名，不是运行层编的规则）。
pub const STAPLE_STRIKE: &str = "strike";
pub const STAPLE_DEFEND: &str = "defend";

/// §272：`?` 房三条基础概率''', 'staples')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs: 7 pickup relics + pool')


main()
