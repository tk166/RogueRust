"""§326 两个"已知缺口"：

1. **`parasite` 的移除惩罚** —— wiki：*"If transformed or removed from your deck, lose 3 Max HP."*
   落点是 `remove_at`（牌离开牌组的**唯一**入口：删牌、改造、`remove_all`、商店、烟斗都走它）。
   ⚠️ 这是"内容规则写在运行层"——**先例已经有了**：`ASCENDERS_BANE` 就是同一个形状
   （`remove_card` 直接拒绝删它）。所以这里也用一个命名常量，而不是去读内容（§133）。
2. **`mark_of_the_bloom` 的战斗内治疗** —— §321 只挡了运行层的治疗汇；战斗内（药水、卡牌、
   状态触发）走 `exec::heal_for`，那是战斗侧的**唯一**治疗汇（`magic_flower` 也在那儿）。
   加一个 model-only 的 `heal_blocked`，在 `heal_for` 里一次性挡住。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'
CSTATE = 'kernel/rd-core/src/state.rs'
EXEC = 'kernel/rd-core/src/exec.rs'
WASM = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


# ── 1. parasite ────────────────────────────────────────────────────────────────
t = io.open(STATE, encoding='utf-8').read()
t = sub(t, """pub const ASCENDERS_BANE: &str = "ascenders_bane";""",
        """pub const ASCENDERS_BANE: &str = "ascenders_bane";

/// §326：`parasite` —— *"If transformed or removed from your deck, lose 3 Max HP."*
///
/// 与 [`ASCENDERS_BANE`] 同一个形状：一条**点名某张卡**的规则写在运行层，因为它在
/// `remove_at`（牌离开牌组的唯一入口）里就必须生效，而运行层不读内容（§133）。
/// 常量在这儿、规则也在这儿 —— 抄到第二处就会有一处漏掉。
pub const PARASITE: &str = "parasite";

/// §326：`parasite` 被移出牌组时代价的上限损失。
pub const PARASITE_MAX_HP_LOSS: i32 = 3;""",
        'PARASITE const')

t = sub(t, """    fn remove_at(&mut self, index: usize) {
        let last = self.deck_len as usize - 1;""",
        """    fn remove_at(&mut self, index: usize) {
        // §326：`parasite` —— "If transformed or removed from your deck, lose 3 Max HP."
        //
        // 放在这里而不是 `apply_deck_change`：删牌、改造、`remove_all`、商店、烟斗**都**从
        // 这一个函数离开牌组，写在别处就会有一条路漏掉（而漏掉的那条看起来完全正常）。
        // 上限至少留 1：`parasite` 不该把一局的上限打到 0（那会让 `health_max` 变成负值，
        // 后面每一条按上限算的效果都跟着错）。
        let id = self.deck[index].as_str();
        let base = id.strip_suffix('+').unwrap_or(id);
        if base == PARASITE {
            self.health_max = (self.health_max - PARASITE_MAX_HP_LOSS).max(1);
            self.health = self.health.min(self.health_max);
        }
        let last = self.deck_len as usize - 1;""",
        'remove_at penalty')
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-run: parasite penalty in remove_at')

# ── 2. heal_blocked（战斗侧）────────────────────────────────────────────────────
t = io.open(CSTATE, encoding='utf-8').read()
t = sub(t, """    pub fn set_ascension(&mut self, level: u8) {
        self.ascension = level;
    }""",
        """    pub fn set_ascension(&mut self, level: u8) {
        self.ascension = level;
    }

    /// §326：`mark_of_the_bloom` —— "You can no longer heal"，**战斗内**也要挡。
    ///
    /// ⚠️ **model-only**：参考没有这个字段（它的 `MarkOfTheBloom` 是遗物侧的
    /// `canHeal` 钩子），所以它不进 `hash_golden`、也不进快照 —— 与 `encounter` 同一条规矩。
    /// 默认 `false`：没被设置过的局面（纯内核测试）行为**不变**。
    pub fn set_heal_blocked(&mut self, blocked: bool) {
        self.heal_blocked = blocked;
    }""",
        'set_heal_blocked')

t = sub(t, """    pub encounter: u32,""",
        """    pub encounter: u32,
    /// §326：这一场战斗里**治疗无效**（`mark_of_the_bloom`）。model-only，见
    /// [`CombatState::set_heal_blocked`]。
    pub heal_blocked: bool,""",
        'heal_blocked field')
io.open(CSTATE, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-core state: heal_blocked field + setter')

# ── 3. `heal_for` 的 gate ──────────────────────────────────────────────────────
t = io.open(EXEC, encoding='utf-8').read()
t = sub(t, """fn heal_for(ctx: &mut ExecContext<'_>, target: &CombatantId, amount: i32) -> Result<(), ExecError> {""",
        """fn heal_for(ctx: &mut ExecContext<'_>, target: &CombatantId, amount: i32) -> Result<(), ExecError> {
    // §326：`mark_of_the_bloom` —— 战斗内**一律**不回血（药水、卡牌、状态触发都走这里）。
    //
    // 放在修饰器**之前**：被挡住时连 `magic_flower` 的 ×150% 都不该算（没有治疗发生）。
    // 仍然记一条动画（`a = 0`），否则屏幕上"喝了药水什么都没发生"与"按钮坏了"分不开。
    if ctx.state.heal_blocked {
        return log_blocked_heal(ctx, target);
    }""",
        'heal gate')

t = sub(t, """/// [`heal_node`] 的实体（`DamageEffects.cs:331-377`）""",
        """/// §326：被 `heal_blocked` 挡住的那一次治疗 —— 记一条 `a = 0` 的动画并返回。
///
/// 与 [`heal_for`] 分开只是为了"挡住的理由只有一处"：`heal_for` 只问一次
/// [`CombatState::heal_blocked`]。
fn log_blocked_heal(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
) -> Result<(), ExecError> {
    let snapshot = *ctx.state.combatant(target).ok_or(ExecError::MissingCombatant)?;
    ctx.state.log_heal(
        target,
        snapshot.health_current,
        snapshot.health_current,
        0,
    );
    Ok(())
}

/// [`heal_node`] 的实体（`DamageEffects.cs:331-377`）""",
        'blocked heal log')
io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-core exec: heal gate')
