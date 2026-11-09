"""§309（一）：`CombatBonus` 的容量与"不许静默丢"。

审阅报告说"容量 4 达到上限时仍会丢效果，但尚未验证合法组合能否触及"。核对之后比它想的更糟：

* 每件**带战斗程序**的遗物都推一条 `standard.<relic>` 标记状态（`runic_pyramid`、`lantern`、
  `ice_cream`、`calipers` … 主表里 **80 件**），所以 4 格的上限在第 **5** 件这类遗物就撞上；
* 结构上界不是"稀有组合"，而是**腰带容量**：48 件遗物 ⇒ 48 条。`native/p309_bound.py`
  量出三个桶的上界（hero 48 / enemy 3 / per-curse 1）。

改法三件：
1. `MAX_COMBAT_STATUSES = MAX_RUN_RELICS`（48），理由写进注释（不是拍的：腰带容量）；
2. 六处重复的"合并或追加"循环收成**一个** `add_status()` —— 同一份规则写六遍必然漂，
   而且它把"满了怎么办"这件事藏在了六个地方；
3. 满了 ⇒ `assert!`（本仓对"调用方破坏了前提"的既有做法：`Reachable::push` 同款）。
   `debug_assert!`/`let _ =` 在 release 里是**静默丢一件遗物的效果**，那正是报告指出的形态。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(old, new, count=1):
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(old) == count, (text.count(old), old[:90])
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    # ── 1. 容量 ────────────────────────────────────────────────────────────────────────────
    patch('''/// `CombatBonus` 最多能带几种"开战时给的状态"（遗物数量远小于它）。
pub const MAX_COMBAT_STATUSES: usize = 4;''',
'''/// `CombatBonus` 最多能带几种"开战时给的状态"。
///
/// §309：**等于腰带容量**，不是拍的 4。
///
/// 为什么：每件带战斗程序的遗物都会推一条 `standard.<relic>` **标记状态**（内核靠它知道
/// "这件遗物在身上"，`runic_pyramid` / `lantern` / `ice_cream` / `calipers` 都是这样），
/// 而主表里有 **80 件**这种遗物。`4` 意味着"拿着 5 件这类遗物，第 5 件的效果**静默消失**"。
///
/// 结构上界：一个 match 臂只给一件遗物一条效果，`RELIC_SECOND_HALVES` 里的 5 条又不与主表的
/// hero 效果重叠 ⇒ 最坏 = 腰带容量 [`MAX_RUN_RELICS`]（48）。三个桶的实测上界分别是
/// 48 / 3 / 1（`native/p309_bound.py`），而判据
/// `the_combat_status_capacity_covers_every_bucket` 每次都从**表本身**重算一遍。
pub const MAX_COMBAT_STATUSES: usize = MAX_RUN_RELICS;''')

    # ── 2. 帮助函数（放在 CombatBonus 的 impl 前后都行：放在 impl 内更近）────────────────
    patch('''    /// §224：同 [`Self::push_status`]，但**给敌人**。`false` = 表满（响亮，不静默丢一件遗物）。
    pub fn push_enemy_status(&mut self, id: &'static str, stacks: i32) -> bool {
        if self.enemy_status_count >= MAX_COMBAT_STATUSES {
            return false;
        }
        self.enemy_statuses[self.enemy_status_count] = Some(CombatStatus { id, stacks });
        self.enemy_status_count += 1;
        true
    }
}''',
'''    /// §224：同 [`Self::push_status`]，但**给敌人**。`false` = 表满（响亮，不静默丢一件遗物）。
    pub fn push_enemy_status(&mut self, id: &'static str, stacks: i32) -> bool {
        if self.enemy_status_count >= MAX_COMBAT_STATUSES {
            return false;
        }
        self.enemy_statuses[self.enemy_status_count] = Some(CombatStatus { id, stacks });
        self.enemy_status_count += 1;
        true
    }
}

/// §309：**"同一条状态相加，否则追加"—— 只此一处**。
///
/// 改之前这条规则在 `combat_bonus_for` 里写了六遍（英雄表 ×3、敌人表、每诅咒表、
/// `RELIC_SECOND_HALVES` 又一遍），而"表满了怎么办"藏在六个不同的地方：三处 `let _ =`、
/// 一处 `debug_assert!`（release 里等于没有）、一处静默。
/// 同一份规则写六遍必然漂 —— 而且漂的方向正好是"某一件遗物在某一种组合下不生效"。
///
/// 满了 ⇒ **断言**：这是"调用方破坏了前提"（内容里不可能凑出比腰带容量还多的这类遗物），
/// 与本仓 `Reachable::push` 同款裁决 —— 响亮，而不是丢一件遗物。
fn add_status(
    list: &mut [Option<CombatStatus>; MAX_COMBAT_STATUSES],
    count: &mut usize,
    id: &'static str,
    stacks: i32,
    what: &str,
) {
    for entry in list.iter_mut().take(*count) {
        if let Some(existing) = entry {
            if existing.id == id {
                existing.stacks += stacks;
                return;
            }
        }
    }
    assert!(
        *count < MAX_COMBAT_STATUSES,
        "too many combat-start statuses ({what}): capacity is MAX_RUN_RELICS = {MAX_COMBAT_STATUSES}"
    );
    list[*count] = Some(CombatStatus { id, stacks });
    *count += 1;
}''')

    # ── 3. 六处调用点 ──────────────────────────────────────────────────────────────────────
    # (a) 敌人表
    patch('''                Some(RelicEffect::StartCombatStatusOnEnemies(id, stacks)) => {
                    // §224: 给**敌人**的那张表。合并规则与英雄那张相同（两件遗物给同一条状态
                    // 要相加，不是覆盖）。
                    let mut merged = false;
                    for entry in bonus.enemy_statuses.iter_mut().take(bonus.enemy_status_count) {
                        if let Some(existing) = entry {
                            if existing.id == id {
                                existing.stacks += stacks;
                                merged = true;
                                break;
                            }
                        }
                    }
                    if !merged && !bonus.push_enemy_status(id, stacks) {
                        // 表满 = 内容的一次冲突，不能静默丢。
                        // `combat_bonus` 没有 Result 通道（它是纯读），所以这里的"响亮"是
                        // 一条断言级的事实：内容里最多 4 件这类遗物。
                        debug_assert!(false, "too many enemy combat-start statuses");
                    }
                }''',
'''                Some(RelicEffect::StartCombatStatusOnEnemies(id, stacks)) => {
                    // §224：给**敌人**的那张表。§309：合并 + 容量走同一处（`add_status`）。
                    add_status(
                        &mut bonus.enemy_statuses,
                        &mut bonus.enemy_status_count,
                        id,
                        stacks,
                        "enemy",
                    );
                }''')

    # (b) CampfireLift
    patch('''                Some(RelicEffect::CampfireLift) => {
                    if self.girya_lifts > 0 {
                        let stacks = i32::from(self.girya_lifts);
                        let mut merged = false;
                        for entry in bonus.statuses.iter_mut().take(bonus.status_count) {
                            if let Some(existing) = entry {
                                if existing.id == "standard.strength" {
                                    existing.stacks += stacks;
                                    merged = true;
                                    break;
                                }
                            }
                        }
                        if !merged {
                            let _ = bonus.push_status("standard.strength", stacks);
                        }
                    }
                }''',
'''                Some(RelicEffect::CampfireLift) => {
                    if self.girya_lifts > 0 {
                        // 与 `Vajra` 相加，不覆盖：`Girya` 2 次 + `Vajra` = 3 层。
                        add_status(
                            &mut bonus.statuses,
                            &mut bonus.status_count,
                            "standard.strength",
                            i32::from(self.girya_lifts),
                            "hero",
                        );
                    }
                }''')

    # (c) InKinds
    patch('''                Some(RelicEffect::StartCombatStatusInKinds(id, stacks, kinds)) => {
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
                }''',
'''                Some(RelicEffect::StartCombatStatusInKinds(id, stacks, kinds)) => {
                    // §269：掩码不覆盖这一场 ⇒ 这条遗物今天不存在。
                    if kinds.covers(kind) {
                        add_status(&mut bonus.statuses, &mut bonus.status_count, id, stacks, "hero");
                    }
                }''')

    print('capacity + helper + 3 sites done')


main()
