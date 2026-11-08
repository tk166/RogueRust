"""§293 B：运行层的"拾取时挑一张牌**加**进牌组"问句。

## 为什么是新通道而不是 `Pending`

`Pending` 是"**这个节点**要什么"，一个流程一个写者。而拾取可能发生在**另一个屏开着的时候**
（宝箱、奖励屏、商人货架）—— §274 已经为"欠着的牌组编辑"立了这条规矩（`pickup_change` /
`pickup_picks`）。这一节照同一条形状再加一组："欠着几张牌要**加**"（`pickup_add`）与
"这一次可以挑哪几张"（`pickup_offer`）。

## 三件遗物

| 遗物 | wiki | 用到的部分 |
|---|---|---|
| `orrery` | 拾取时挑 5 张牌加入牌组 | `pickup_add = 5` |
| `tiny_house` | +50 金币、上限 +5、1 瓶药水、**1 张牌** | 四件事一件遗物 |
| `singing_bowl` | 加牌时**可以**改拿 +2 上限 | 奖励屏与拾取问句各一个"换"的入口 |

## 候选牌怎么来

与战斗奖励**同一套档位**（`reward_bands(FightKind::Normal, …)` + `pick_of`），但**不动**
`rarity_offset`：那本账是"战斗奖励的稀有度保底"（`inv:§3.5`），而 orrery/tiny_house 不是战斗奖励
—— 动它会让"三场没出稀有"被一件商店遗物重置。这条偏差写在这里，不在别处。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(text, old, new, count=1):
    assert text.count(old) == count, (text.count(old), old[:110])
    return text.replace(old, new)


VARIANT_ANCHOR = '''    /// §292：`sacred_bark` —— 药水效果乘以 `percent`（wiki: *"Double the effectiveness"* = 200）。
    PotionEffectPercent(i32),
}'''

VARIANTS = '''    /// §292：`sacred_bark` —— 药水效果乘以 `percent`（wiki: *"Double the effectiveness"* = 200）。
    PotionEffectPercent(i32),
    /// §293：`orrery`(5) / `tiny_house`(1) —— 往牌组里加 `count` 张牌，玩家从**三选一**里挑。
    ///
    /// 走 [`RunState::pickup_add`] 那条欠账通道（不是 `Pending`）：拾取可能发生在另一个屏开着
    /// 的时候，把 `pending` 抢过来会把那一屏顶掉（§274 的老账）。
    PickupAddCards(u8),
    /// §293：`tiny_house` —— +50 金币、上限 +5、一瓶药水、一张牌。四件事一件遗物。
    PickupTinyHouse,
    /// §293：`singing_bowl` —— 加牌时**可以**改拿 +`amount` 上限（wiki: *"you may raise your Max
    /// HP by 2 instead"*）。它自己不给牌，只在两个"加牌"的问句上多一个按钮。
    SingingBowl(i32),
}'''

# 三处"不是这个钩子"的清单里要补的三个变体（`push_relic` 里是**真的**要实现，不补）
NOT_HERE = '''| RelicEffect::PickupAddCards(_)
                    | RelicEffect::PickupTinyHouse
                    | RelicEffect::SingingBowl(_),'''

ACTIONS = '''    /// §293：欠着**几张牌**要加进牌组（`orrery` 的 5、`tiny_house` 的 1）。0 = 不欠。
    #[must_use]
    pub const fn pickup_add(&self) -> u8 {
        self.pickup_add
    }

    /// §293：这一次**可以挑**的那几张牌（`pickup_add == 0` 时是空切片）。
    #[must_use]
    pub fn pickup_offer(&self) -> &[RunId] {
        &self.pickup_offer[..self.pickup_offer_len as usize]
    }

    /// §293：抽一手"可以挑的牌"（三张，档位与战斗奖励同一套）。
    ///
    /// ⚠️ **不动** `rarity_offset`：那是"战斗奖励的稀有度保底"（`inv:§3.5`），而 orrery /
    /// tiny_house 不是战斗奖励 —— 让一件商店遗物重置那条保底会让"三场没出稀有"凭空消失。
    fn roll_pickup_offer(&mut self, pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        self.pickup_offer = [RunId::EMPTY; MAX_REWARD_CARDS];
        self.pickup_offer_len = 0;
        // 与 `roll_reward` 同一条过滤：状态/诅咒/特殊牌不进候选。
        let mut eligible = [0usize; MAX_POOL];
        let mut eligible_len = 0usize;
        Self::pool_fits(pool.len())?;
        for index in 0..pool.len() {
            if !matches!(
                pool[index].rarity,
                Rarity::Status | Rarity::Curse | Rarity::Special
            ) {
                eligible[eligible_len] = index;
                eligible_len += 1;
            }
        }
        if eligible_len == 0 {
            return Err(RunError::PoolTooSmall {
                pool: 0,
                need: 1,
            });
        }
        let eligible = &eligible[..eligible_len];
        let mut used = [false; MAX_POOL];
        let wanted = MAX_REWARD_CARDS.min(eligible_len);
        for slot in 0..wanted {
            let (rare_top, uncommon_top) = reward_bands(FightKind::Normal, self.rarity_offset);
            let roll = self.rng.roll(RunStream::Reward, 100)? as i32;
            let band = if roll < rare_top {
                Rarity::Rare
            } else if roll < uncommon_top {
                Rarity::Uncommon
            } else {
                Rarity::Common
            };
            // 与 `roll_reward` 同一条兜底链：空档先落 `Basic`，再落"剩下什么给什么"。
            let mut picked = self.pick_of(pool, eligible, &used, Some(band))?;
            if picked.is_none() {
                picked = self.pick_of(pool, eligible, &used, Some(Rarity::Basic))?;
            }
            if picked.is_none() {
                picked = self.pick_of(pool, eligible, &used, None)?;
            }
            let Some(index) = picked else { break };
            used[index] = true;
            self.pickup_offer[slot] =
                RunId::new(pool[index].id).map_err(|_| RunError::BadId)?;
            self.pickup_offer_len = (slot + 1) as u8;
        }
        Ok(())
    }

    /// §293：挑 `slot` 那一张加进牌组。
    ///
    /// **先验后改**：牌组满了（`Capacity`）时欠账**不递减**，否则一次被拒的点击会白白吃掉
    /// 一次额度（§274 的 `pickup_card` 踩过同一个坑）。
    pub fn pickup_add_card(
        &mut self,
        slot: usize,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pickup_add == 0 {
            return Err(RunError::WrongPhase);
        }
        let Some(id) = self.pickup_offer.get(slot).copied() else {
            return Err(RunError::EmptyOffer(slot as u8));
        };
        if id == RunId::EMPTY {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        let Some(row) = pool.iter().find(|card| card.id == id.as_str()) else {
            return Err(RunError::NoSuchCard);
        };
        let row = *row;
        self.push_card(row)?;
        self.pickup_add -= 1;
        if self.pickup_add == 0 {
            self.pickup_offer = [RunId::EMPTY; MAX_REWARD_CARDS];
            self.pickup_offer_len = 0;
        } else {
            // 下一次挑的是**新的一手** —— 同一手牌不能给两次（StS 的"挑 5 张"是 5 次奖励屏）。
            self.roll_pickup_offer(pool)?;
        }
        Ok(())
    }

    /// §293：跳过这一次（少拿一张牌）。StS 的奖励屏可以跳过，orrery 的每一次也是。
    pub fn pickup_add_skip(&mut self) -> Result<(), RunError> {
        if self.pickup_add == 0 {
            return Err(RunError::WrongPhase);
        }
        self.pickup_add -= 1;
        self.pickup_offer = [RunId::EMPTY; MAX_REWARD_CARDS];
        self.pickup_offer_len = 0;
        Ok(())
    }

    /// §293：`singing_bowl` —— 把这一次"加牌"换成 **+`amount` 上限**。
    ///
    /// 没有这件遗物 ⇒ `UnsupportedRelic`（不是"静默不给"：那个按钮本来就不该出现，
    /// 出现说明调用方在猜）。
    pub fn pickup_add_max_hp(&mut self) -> Result<(), RunError> {
        let Some(RelicEffect::SingingBowl(amount)) =
            self.first_relic_effect_of(RelicEffect::SingingBowl(2))
        else {
            return Err(RunError::UnsupportedRelic { index: 0 });
        };
        if self.pickup_add == 0 {
            return Err(RunError::WrongPhase);
        }
        self.health_max += amount;
        self.adjust_health(amount);
        self.pickup_add -= 1;
        self.pickup_offer = [RunId::EMPTY; MAX_REWARD_CARDS];
        self.pickup_offer_len = 0;
        Ok(())
    }

    /// §293：`singing_bowl` 在**战斗奖励屏**上的那一条 —— 不拿牌，改拿 +`amount` 上限。
    ///
    /// 与 [`Self::take_card`] 同一条规矩：它只花掉**卡牌那一行**，金币/药水/遗物都还留在屏上
    /// （`inv:§9.3`：药水是它自己的一份 offer）。
    pub fn take_max_hp_instead(&mut self) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let Some(RelicEffect::SingingBowl(amount)) =
            self.first_relic_effect_of(RelicEffect::SingingBowl(2))
        else {
            return Err(RunError::UnsupportedRelic { index: 0 });
        };
        // 牌已经被拿走了 ⇒ 没有"换成上限"这回事（否则可以拿一张牌再加 2 点上限）。
        if self.reward.cards_len == 0 {
            return Err(RunError::EmptyOffer(0));
        }
        self.health_max += amount;
        self.adjust_health(amount);
        for row in self.reward.cards.iter_mut() {
            *row = RunId::EMPTY;
        }
        self.reward.cards_len = 0;
        Ok(())
    }

'''


def main():
    s = io.open(STATE, encoding='utf-8').read()

    # ── 1. 三个变体
    s = patch(s, VARIANT_ANCHOR, VARIANTS)

    # ── 2. 表项
    s = patch(s, '''            "sacred_bark" => Some(RelicEffect::PotionEffectPercent(200)),
            _ => None,''', '''            "sacred_bark" => Some(RelicEffect::PotionEffectPercent(200)),
            // §293：加牌的三个入口（`orrery` / `tiny_house` / `singing_bowl`）。
            "orrery" => Some(RelicEffect::PickupAddCards(5)),
            "tiny_house" => Some(RelicEffect::PickupTinyHouse),
            "singing_bowl" => Some(RelicEffect::SingingBowl(2)),
            _ => None,''')

    # ── 3. 拾取副作用
    s = patch(s, '''            // §292：宝箱的那两件计数器。
            RelicEffect::ChestExtraRelic { chests } => self.chest_extra = chests,
            RelicEffect::NextChestEmpty(chests) => self.chest_empty = chests,''',
                 '''            // §292：宝箱的那两件计数器。
            RelicEffect::ChestExtraRelic { chests } => self.chest_extra = chests,
            RelicEffect::NextChestEmpty(chests) => self.chest_empty = chests,
            // §293：`orrery` —— 欠 5 张，先抽一手候着。
            RelicEffect::PickupAddCards(count) => {
                self.pickup_add = self.pickup_add.saturating_add(count);
                self.roll_pickup_offer(pool)?;
            }
            // §293：`tiny_house` —— 四件事。金币走 `adjust_gold`（所以 `ectoplasm` 该拦就拦、
            // `bloody_idol` 该回血就回血），上限 +5 与 `MaxHealthUp` 同一条规矩（当前血跟着涨）。
            RelicEffect::PickupTinyHouse => {
                self.adjust_gold(TINY_HOUSE_GOLD);
                self.health_max += TINY_HOUSE_MAX_HEALTH;
                self.adjust_health(TINY_HOUSE_MAX_HEALTH);
                self.pickup_potions = self.pickup_potions.saturating_add(1);
                self.pickup_add = self.pickup_add.saturating_add(1);
                self.roll_pickup_offer(pool)?;
            }
            // §293：`singing_bowl` 在拾取这一刻**什么都不做**（它只是"加牌"问句上多一个按钮）。
            RelicEffect::SingingBowl(_) => {}''')

    # ── 4.（三处清单已单独补好：脚本化插进 `Some(...)` 分组会踩 §3b）

    # ── 5. 字段
    s = patch(s, '''    /// §292：拾取时**欠着**的几瓶药水（`cauldron` 的 5 瓶）。同 [`Self::pickup_relics`]。
    pickup_potions: u8,
}''', '''    /// §292：拾取时**欠着**的几瓶药水（`cauldron` 的 5 瓶）。同 [`Self::pickup_relics`]。
    pickup_potions: u8,
    /// §293：欠着**几张牌**要加进牌组（`orrery` 的 5、`tiny_house` 的 1）。
    ///
    /// 与 `pickup_picks` 分开：那个是"改**已有**的一张"，这个是"从候选里**加**一张"。
    /// 两件事共用一个字段会让"还要选几张"说不清是哪一种。
    pickup_add: u8,
    /// §293：这一次可以挑的那几张（`pickup_add > 0` 时有意义）。
    pickup_offer: [RunId; MAX_REWARD_CARDS],
    pickup_offer_len: u8,
}''')
    s = patch(s, '''            pickup_relics: 0,
            pickup_potions: 0,''', '''            pickup_relics: 0,
            pickup_potions: 0,
            pickup_add: 0,
            pickup_offer: [RunId::EMPTY; MAX_REWARD_CARDS],
            pickup_offer_len: 0,''')

    # ── 6. 动作 + 访问器（挂在 `add_random_curse` 之前）
    s = patch(s, '''    /// §292：往牌组里塞**一张随机诅咒**（`cursed_key`）。''', ACTIONS + '''    /// §292：往牌组里塞**一张随机诅咒**（`cursed_key`）。''')

    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('§293 run layer in')


main()
