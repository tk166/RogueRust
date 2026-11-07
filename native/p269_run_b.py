"""§269 rd-run 第二批：`combat_bonus_for(kind)` / `start_heal` / 遗物行 / 奖励层。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(src, old, new, what):
    assert src.count(old) == 1, '%s: %d matches' % (what, src.count(old))
    return src.replace(old, new)


def main():
    src = io.open(P, encoding='utf-8').read()

    # ---- ① CombatBonus 增加 start_heal
    src = patch(src, """    /// How many of [`Self::per_curse_statuses`] are set.
    pub per_curse_status_count: usize,
}""", """    /// How many of [`Self::per_curse_statuses`] are set.
    pub per_curse_status_count: usize,
    /// §269：开战时**先回这么多血**（`pantograph`：Boss 战 +25）。上限由战斗构建方钳
    /// （血量归战斗状态管，运行层只表达"想回多少"）。
    pub start_heal: i32,
}""", 'CombatBonus.start_heal')

    src = patch(src, """            per_curse_statuses: [None; MAX_COMBAT_STATUSES],
            per_curse_status_count: 0,
        }""", """            per_curse_statuses: [None; MAX_COMBAT_STATUSES],
            per_curse_status_count: 0,
            start_heal: 0,
        }""", 'CombatBonus default')

    src = patch(src, """            && self.per_curse_status_count == 0""",
                """            && self.per_curse_status_count == 0
            && self.start_heal == 0""", 'CombatBonus::is_empty')

    # ---- ② combat_bonus → combat_bonus_for(kind)，并让旧入口转发
    src = patch(src, """    pub fn combat_bonus(&self) -> CombatBonus {
        let mut bonus = CombatBonus::default();""",
                """    pub fn combat_bonus(&self) -> CombatBonus {
        self.combat_bonus_for(FightKind::Normal)
    }

    /// §269：**按战斗类型**算的开战加成 —— 有几件遗物只在精英/Boss 战里生效
    /// （`sling_of_courage` / `slavers_collar` / `pantograph`）。
    ///
    /// 旧入口 [`Self::combat_bonus`] 保留为 `Normal`：它的调用方（大量测试、`rd-wasm` 的
    /// 非战斗路径）没有"这一场是什么类型"这个概念，而 `Normal` 正是那些地方唯一说得通的答案。
    #[must_use]
    pub fn combat_bonus_for(&self, kind: FightKind) -> CombatBonus {
        let mut bonus = CombatBonus::default();""", 'combat_bonus_for')

    # ---- ③ 三个 kind 相关变体的处理（加在 StartCombatStatusPerCurse 之前）
    src = patch(src, """                Some(RelicEffect::StartCombatStatusPerCurse(id, stacks)) => {""",
                """                Some(RelicEffect::StartCombatStatusInKinds(id, stacks, kinds)) => {
                    // §269：掩码不覆盖这一场 ⇒ 这条遗物今天不存在。
                    if kinds.covers(kind) {
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
                Some(RelicEffect::StartCombatHealInKinds(amount, kinds)) => {
                    if kinds.covers(kind) {
                        bonus.start_heal += amount;
                    }
                }
                Some(RelicEffect::StartCombatStatusPerCurse(id, stacks)) => {""",
                'kind-gated effects')

    # ---- ④ 遗物行
    src = patch(src, """            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。""",
                """            // §269：**战斗类型**层（只在精英/Boss 战里生效的三件）。
            //   `sling_of_courage`：精英战 +2 力量；
            //   `slavers_collar`：Boss/精英战每回合 +1 能量（`TurnStartEnergy` 修饰器）；
            //   `pantograph`：Boss 战开战回 25。
            "sling_of_courage" => Some(RelicEffect::StartCombatStatusInKinds(
                "standard.strength",
                2,
                KindMask::ELITE,
            )),
            "slavers_collar" => Some(RelicEffect::StartCombatStatusInKinds(
                "standard.slavers_collar",
                1,
                KindMask(2 | 4),
            )),
            "pantograph" => {
                Some(RelicEffect::StartCombatHealInKinds(25, KindMask::BOSS))
            }
            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。""",
                'kind relics')

    # ---- ⑤ 精英血 -25%（preserved_insect）：与升阶的 +75% 同一条通道
    src = patch(src, """    pub const fn enemy_health_bonus_percent(&self, kind: FightKind) -> i32 {
        let level = match kind {""",
                """    /// §269：不再是 `const fn` —— `preserved_insect` 要看遗物表，而查表不是常量表达式。
    /// 调用点（`fight_begin`）本来就是普通函数，所以这条改动没有传播成本。
    pub fn enemy_health_bonus_percent(&self, kind: FightKind) -> i32 {
        // §269：`preserved_insect` —— 精英战敌人血量 -25%。与升阶的 +75% 走**同一条通道**
        // （战斗构建方只读这一个数），所以两个修正自动叠加、顺序无关（先升阶后遗物，
        // 整数加法可交换）。⚠️ 不能为它另开一条路径：那会让"精英血量"有两个来源。
        let preserved_insect = matches!(kind, FightKind::Elite)
            && self.holds_relic_effect(RelicEffect::EliteEnemyHealthPercent(-25));
        let level = match kind {""", 'enemy hp hook')

    src = patch(src, """        if self.at_least(level) {
            ASCENDED_ENEMY_HEALTH_PERCENT
        } else {
            0
        }
    }""", """        let ascension = if self.at_least(level) {
            ASCENDED_ENEMY_HEALTH_PERCENT
        } else {
            0
        };
        ascension - if preserved_insect { 25 } else { 0 }
    }""", 'enemy hp value')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs: combat_bonus_for + relics + elite hp')


main()
