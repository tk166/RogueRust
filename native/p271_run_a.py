"""§271 rd-run：节点类 3 件（meal_ticket / ssserpent_head / ancient_tea_set）
+ 药水类 2 件（sozu / toy_ornithopter）的运行层部分。

| 遗物 | wiki | 落点 |
|---|---|---|
| `meal_ticket` | "Whenever you enter a shop, heal 15 HP." | `begin_node` 的 Shop 分支（与 `Eternal Feather` 同一个"进门就付"的规矩） |
| `ssserpent_head` | "Whenever you enter a ? room, gain 50 Gold." | `begin_node` 的 Unknown 分支 |
| `ancient_tea_set` | "Whenever you enter a Rest Site, start the next combat with 2 extra Energy." | Rest 分支置 `tea_set_pending`，奖励里带上状态，开战后清 |
| `sozu` | "…You can no longer obtain Potions." | `push_potion` 拒绝 + `roll_reward` 不掷药水 |
| `toy_ornithopter` | "Whenever you use a potion, heal 5 HP." | `RelicEffect::PotionUseHeal`（wasm 用，血量在战斗里） |
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


VARIANTS = '''    /// §271：`meal_ticket` —— 进商店回 15 血。
    ShopEntryHeal(i32),
    /// §271：`ssserpent_head` —— 进 `?` 房 +50 金币。
    UnknownRoomGold(i32),
    /// §271：`ancient_tea_set` —— 进篝火 ⇒ **下一场**战斗开战 +`stacks` 能量（状态 id + 层数）。
    ///
    /// 带状态 id 而不是硬编码：能量是内容的事（`standard.ancient_tea_set` 的
    /// `TurnStarted` 触发器），运行层只负责"这一场要不要挂它"。
    RestEntryNextCombatEnergy(&'static str, i32),
    /// §271：`sozu` —— 不能再获得药水（第一半；"每回合 +1 能量"在 `RELIC_SECOND_HALVES`）。
    NoPotionGain,
    /// §271：`toy_ornithopter` —— 用一瓶药水回 5 血（血量在**战斗**里，所以这条只给数字，
    /// 由 `rd_env_use_potion` 在战斗员身上兑现）。
    PotionUseHeal(i32),'''

ROWS = '''            // §271：**节点类**三件（都落在 `begin_node` 的 `NodeKind` 分支上）。
            "meal_ticket" => Some(RelicEffect::ShopEntryHeal(15)),
            "ssserpent_head" => Some(RelicEffect::UnknownRoomGold(50)),
            "ancient_tea_set" => Some(RelicEffect::RestEntryNextCombatEnergy(
                "standard.ancient_tea_set",
                1,
            )),
            // §271：药水类两件。
            "sozu" => Some(RelicEffect::NoPotionGain),
            "toy_ornithopter" => Some(RelicEffect::PotionUseHeal(5)),
            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。'''

SECOND = '''const RELIC_SECOND_HALVES: [(&str, RelicEffect); 3] = [
    ("busted_crown", RelicEffect::RewardCardDelta(-2, KindMask::ALL)),
    ("ectoplasm", RelicEffect::StartCombatStatus("standard.ectoplasm", 1)),
    // §271：`sozu` 的第一半是"不能再获得药水"（运行时判断），第二半是每回合 +1 能量。
    ("sozu", RelicEffect::StartCombatStatus("standard.sozu", 1)),
];'''


def main():
    src = io.open(P, encoding='utf-8').read()

    # ① 新变体
    src = patch(src, '''    /// §270：`omamori` —— 拾取时给 2 次"挡诅咒"。''',
                VARIANTS + '''
    /// §270：`omamori` —— 拾取时给 2 次"挡诅咒"。''', 'variants')

    # ② 遗物行
    src = patch(src, '            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。',
                ROWS, 'rows')

    # ③ 第二半表 +1
    src = patch(src, '''const RELIC_SECOND_HALVES: [(&str, RelicEffect); 2] = [
    ("busted_crown", RelicEffect::RewardCardDelta(-2, KindMask::ALL)),
    ("ectoplasm", RelicEffect::StartCombatStatus("standard.ectoplasm", 1)),
];''', SECOND, 'second halves')

    # ④ 运行期字段 `tea_set_pending`
    src = patch(src, '''    /// §270：`maw_bank` 已经在商店花过钱 ⇒ 不再给爬层金币（wiki："No longer works when you spend
    /// any Gold at a shop"）。布尔就够 —— wiki 只有"失效没失效"，没有次数。
    maw_bank_broken: bool,''',
                '''    /// §270：`maw_bank` 已经在商店花过钱 ⇒ 不再给爬层金币（wiki："No longer works when you spend
    /// any Gold at a shop"）。布尔就够 —— wiki 只有"失效没失效"，没有次数。
    maw_bank_broken: bool,
    /// §271：`ancient_tea_set` —— 刚进过篝火 ⇒ **下一场**战斗开战多 2 能量。
    ///
    /// 为什么是运行期字段、而不是"在篝火那一刻直接加能量"：那时没有战斗，能量无处可加
    /// （能量是战斗状态的资源）。所以只记"欠一场"，开战那一刻兑现、然后清掉。
    tea_set_pending: bool,''', 'field')

    src = patch(src, '''            omamori_charges: 0,
            maw_bank_broken: false,''',
                '''            omamori_charges: 0,
            maw_bank_broken: false,
            tea_set_pending: false,''', 'field init')

    # ⑤ 访问器 + 清理点
    src = patch(src, '''    /// §270：`maw_bank` 是否已经失效（在商店花过钱）。''',
                '''    /// §271：`ancient_tea_set` 是否欠着一场"开战 +2 能量"。
    #[must_use]
    pub const fn tea_set_pending(&self) -> bool {
        self.tea_set_pending
    }

    /// §271：**兑现**那一场 —— 由战斗构建方在"开战加成已经应用"之后调用。
    ///
    /// ⚠️ 清理点只有这一个，而且它必须在**应用之后**：先清再算的话，`combat_bonus_for` 就
    /// 永远读不到它，`ancient_tea_set` 会变成一个什么都不做的遗物（而且所有判据都还是绿的，
    /// 因为没有任何东西"错"）。
    pub fn clear_tea_set(&mut self) {
        self.tea_set_pending = false;
    }

    /// §270：`maw_bank` 是否已经失效（在商店花过钱）。''', 'accessor + clear')

    # ⑥ `begin_node` 三个分支
    src = patch(src, '''            NodeKind::Rest => {
                let heal = self.rest_site_entry_heal();
                if heal > 0 {
                    self.heal_after_combat(heal);
                }
                Pending::Rest
            }''',
                '''            NodeKind::Rest => {
                let heal = self.rest_site_entry_heal();
                if heal > 0 {
                    self.heal_after_combat(heal);
                }
                // §271：`ancient_tea_set` —— "Whenever you enter a Rest Site, start the next
                // combat with 2 extra Energy"。**进门就欠上**（与上面那条 `Eternal Feather`
                // 同一个理由：wiki 说"on entering"，不是"on Rest"）。
                if self.holds_relic_effect(RelicEffect::RestEntryNextCombatEnergy(
                    "standard.ancient_tea_set",
                    1,
                )) {
                    self.tea_set_pending = true;
                }
                Pending::Rest
            }''', 'rest branch')

    src = patch(src, '''            NodeKind::Shop => {
                self.stock_shop(card_pool, relic_pool)?;
                Pending::Shop
            }''',
                '''            NodeKind::Shop => {
                self.stock_shop(card_pool, relic_pool)?;
                // §271：`meal_ticket` —— "Whenever you enter a shop, heal 15 HP"。
                // 与 `Eternal Feather` 同一条规矩：**进门就付**，不是"买了东西才付"。
                if let Some(RelicEffect::ShopEntryHeal(amount)) =
                    self.first_relic_effect_of(RelicEffect::ShopEntryHeal(15))
                {
                    self.heal_after_combat(amount);
                }
                Pending::Shop
            }''', 'shop branch')

    src = patch(src, '''            NodeKind::Unknown => Pending::None,''',
                '''            NodeKind::Unknown => {
                // §271：`ssserpent_head` —— "Whenever you enter a ? room, gain 50 Gold"。
                // 走 `adjust_gold`，所以 `ectoplasm` 该拦就拦、`bloody_idol` 该回血就回血。
                if let Some(RelicEffect::UnknownRoomGold(amount)) =
                    self.first_relic_effect_of(RelicEffect::UnknownRoomGold(50))
                {
                    self.adjust_gold(amount);
                }
                Pending::None
            }''', 'unknown branch')

    # ⑦ 开战加成里带上 pending 状态
    src = patch(src, '''        // §270：`RELIC_SECOND_HALVES` 里属于"开战加成"的那一类（`ectoplasm` 的每回合 +1 能量）。''',
                '''        // §271：`ancient_tea_set` —— 篝火之后的那**一场**多 2 能量。挂的是内容状态
        // （`standard.ancient_tea_set` 自己的 `TurnStarted` 程序），运行层只说"挂哪一条"。
        if self.tea_set_pending {
            if let Some(RelicEffect::RestEntryNextCombatEnergy(id, stacks)) =
                self.first_relic_effect_of(RelicEffect::RestEntryNextCombatEnergy(
                    "standard.ancient_tea_set",
                    1,
                ))
            {
                let mut merged = false;
                for entry in bonus.statuses.iter_mut().take(bonus.status_count) {
                    if let Some(existing) = entry {
                        if existing.id == id {
                            existing.stacks += stacks;
                            merged = true;
                            break;
                        }
                    }
                }
                if !merged {
                    let _ = bonus.push_status(id, stacks);
                }
            }
        }
        // §270：`RELIC_SECOND_HALVES` 里属于"开战加成"的那一类（`ectoplasm` 的每回合 +1 能量）。''',
                'combat bonus tea set')

    # ⑧ push_potion 拒绝
    src = patch(src, '''    pub fn push_potion(&mut self, potion_id: &str) -> Result<(), RunError> {
        let id = RunId::new(potion_id).map_err(|_| RunError::BadId)?;''',
                '''    /// §271：`sozu` —— "You can no longer obtain Potions"。
    ///
    /// 拒绝而不是静默不加入：`push_potion` 的所有调用方（奖励屏、事件、商店、调试入口）
    /// 都刚把一瓶药水递到玩家手里，**悄悄收下又悄悄丢掉**正是这个仓库一直在禁的那种损失。
    /// 所以除了这里，`roll_reward` 还会**不再掷**药水 —— 奖励屏上根本不会出现那一格。
    pub fn push_potion(&mut self, potion_id: &str) -> Result<(), RunError> {
        if self.holds_relic_effect(RelicEffect::NoPotionGain) {
            return Err(RunError::PotionGainBlocked);
        }
        let id = RunId::new(potion_id).map_err(|_| RunError::BadId)?;''',
                'push_potion')

    # ⑨ roll_reward：sozu 时不掷药水
    src = patch(src, '''        let drop = rolled && self.potion_room();''',
                '''        // §271：`sozu` —— 奖励屏上根本不该出现药水那一格。掷骰照旧（随机流的位置不动），
        // 只把"要不要给"按成 false。⚠️ 与 `push_potion` 的拒绝是**两件事**：这里是不发，
        // 那里是"别的路（事件/商店/调试）递过来的也收不了"。
        let drop = rolled && self.potion_room() && !self.holds_relic_effect(RelicEffect::NoPotionGain);''',
                'drop')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs: node + potion relics wired')


main()
