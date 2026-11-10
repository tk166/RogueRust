"""§324 `augmenter` 的两件内核东西。

1. **`transform_choose:<n>`**（`EventEffect::OwedTransforms`）—— `[Become Test Subject]`
   "**Choose and** Transform 2 cards"。它是"N 次待办的改牌"，所以复用**拾取欠账**那条通道
   （`pickup_change` + `pickup_picks`）：那条通道本来就是"与 `pending` 无关的欠账"，
   页面也已经有一个按它画的选择器（`describePickupCard`）。→ **没有新状态、没有新屏**。
2. **`RelicEffect::StartCombatStatuses`**（复数）—— `mutagenic_strength` 要一次给两个状态：
   `strength 3` 与 `lose_strength 3`（后者是既有的 `TurnEnded` 触发器：回合末扣掉等量力量并自我移除，
   正好是 wiki 的"at the end of your first turn, lose 3 Strength"）。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'
WASM = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(STATE, encoding='utf-8').read()

# ── 1. 事件效果：`transform_choose:<n>` ─────────────────────────────────────────
t = sub(t, """    /// §321：**升级牌组里的每一张**（`upgrade_all`）。`mind_bloom` 的 `[I am Awake]`。""",
        """    /// §324：**玩家选 `n` 张、每张都改造成随机牌**（`transform_choose:<n>`）。
    /// `augmenter` 的 `[Become Test Subject]` —— wiki：*"Choose and Transform 2 cards"*。
    ///
    /// 复用**拾取欠账**通道（`pickup_change` + `pickup_picks`）：那条通道本来就是
    /// "与 `pending` 无关的 N 次待办"，页面也已经按它画选择器 —— 所以这里既不新增状态，
    /// 也不新增屏。
    OwedTransforms(u8),
    /// §321：**升级牌组里的每一张**（`upgrade_all`）。`mind_bloom` 的 `[I am Awake]`。""",
        'OwedTransforms variant')

t = sub(t, """            "remove_card" => (Self::RemoveCard, None),""",
        """            "remove_card" => (Self::RemoveCard, None),
            // §324：`augmenter` 的 `[Become Test Subject]` —— 选 n 张各改造一次（`n:1..=5`）。
            "transform_choose" => match amount {
                1..=5 => (Self::OwedTransforms(amount as u8), None),
                _ => return None,
            },""",
        'parse transform_choose')

t = sub(t, """            // §321：升级牌组里的每一张（`upgrade_at` 已经是"没有 `+` 行 ⇒ 什么也不做"）。""",
        """            // §324：`[Become Test Subject]` —— 欠 n 次改造（`pickup_*` 通道）。
            //
            // 两条拒绝都是为了"不静默吞掉一次额度"：牌组空（没有可指的牌）与**已经欠着**
            // 别的改牌（`empty_cage` / `astrolabe` 的欠账会被这一条覆盖掉）。
            EventEffect::OwedTransforms(count) => {
                if self.deck_len == 0 {
                    return Err(RunError::DeckEmpty);
                }
                if self.pickup_change.is_some() {
                    return Err(RunError::WrongPhase);
                }
                self.pickup_change = Some(DeckChange::Transform);
                self.pickup_picks = count;
            }
            // §321：升级牌组里的每一张（`upgrade_at` 已经是"没有 `+` 行 ⇒ 什么也不做"）。""",
        'apply OwedTransforms')

# ── 2. `RelicEffect::StartCombatStatuses`（复数）────────────────────────────────
t = sub(t, """    StartCombatStatus(&'static str, i32),""",
        """    StartCombatStatus(&'static str, i32),
    /// §324：一次给**几种**开战状态（`mutagenic_strength` 要 `strength 3` + `lose_strength 3`）。
    /// 合并规则与单数那条完全一样（同 id 相加）。
    StartCombatStatuses(&'static [(&'static str, i32)]),""",
        'StartCombatStatuses variant')

t = sub(t, """                Some(RelicEffect::StartCombatStatus(id, stacks)) => {
                    // Two relics granting the same status must **merge**, not overwrite: the same
                    // rule the kernel uses when a status is applied twice. §309: one place only.
                    add_status(&mut bonus.statuses, &mut bonus.status_count, id, stacks, "hero");
                }""",
        """                Some(RelicEffect::StartCombatStatus(id, stacks)) => {
                    // Two relics granting the same status must **merge**, not overwrite: the same
                    // rule the kernel uses when a status is applied twice. §309: one place only.
                    add_status(&mut bonus.statuses, &mut bonus.status_count, id, stacks, "hero");
                }
                // §324：复数版本走**同一个**合并函数 —— 不然就是第二份"同 id 相加"的规则。
                Some(RelicEffect::StartCombatStatuses(list)) => {
                    for (id, stacks) in list.iter().copied() {
                        add_status(&mut bonus.statuses, &mut bonus.status_count, id, stacks, "hero");
                    }
                }""",
        'combat bonus plural')

t = sub(t, """            "blood_vial" => Some(RelicEffect::HealUp(2)),""",
        """            "blood_vial" => Some(RelicEffect::HealUp(2)),
            // §324：wiki `Mutagenic_Strength` —— "Start each combat with 3 Strength. At the end of
            // your first turn, lose 3 Strength." 后半句由既有的 `standard.lose_strength` 提供
            // （它就在 `TurnEnded` 里扣掉等量力量并自我移除）。
            "mutagenic_strength" => Some(RelicEffect::StartCombatStatuses(&[
                ("standard.strength", 3),
                ("standard.lose_strength", 3),
            ])),""",
        'relic mapping')

io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
print('state.rs: transform_choose + StartCombatStatuses')

# ── wasm：效果码 ────────────────────────────────────────────────────────────────
t = io.open(WASM, encoding='utf-8').read()
t = sub(t, """        | EventEffect::UpgradeAll => -1,""",
        """        | EventEffect::UpgradeAll
        // §324：`transform_choose:<n>` 的落点是**牌组选择器**（`rd_run_pickup_*` 那条既有通道），
        // 不是效果码。
        | EventEffect::OwedTransforms(_) => -1,""",
        'wasm code')
t = sub(t, """        EventEffect::OfferCards(count, _) => i32::from(count),""",
        """        EventEffect::OfferCards(count, _) => i32::from(count),
        // §324："要选几张"就是数量。
        EventEffect::OwedTransforms(count) => i32::from(count),""",
        'wasm amount')
io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-wasm: effect code + amount')
