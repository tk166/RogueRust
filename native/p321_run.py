"""§321 内核（二）：`upgrade_all` 与 `mark_of_the_bloom` 的"不能治疗"。

`mark_of_the_bloom` 原来映射成 `NoRest`（与 `coffee_dripper` 同一个）—— 那是**错的**：
wiki 说它 "You can no longer heal"。两者的可观察差别：Coffee Dripper 让 Rest 这个**选项消失**，
Mark of the Bloom 让 Rest **还在**、只是回 0 点（以及所有别的治疗途径都回 0）。

所以这条规则落在**唯一的治疗汇**上：`heal_after_combat`（休息、遗物、事件、`heal_pct`、
`heal_full` 全走它）。⚠️ 战斗内的治疗（药水 / `Burning Blood` 的战斗内触发）不在这条路上 ——
那条在 `rd-wasm` 的战斗侧，`docs/port-plan.md §321` 里如实记了这一点。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(STATE, encoding='utf-8').read()

# ── 1. `RelicEffect::NoHeal` ──────────────────────────────────────────────────────
t = sub(t, """    /// §259: this relic **removes** Rest (`coffee_dripper`).""",
        """    /// §259: this relic **removes** Rest (`coffee_dripper`).
    ///
    /// §321：`mark_of_the_bloom` **不再**在这里 —— 它不禁 Rest，它禁**治疗**（见 [`Self::NoHeal`]）。
    /// 两者的可观察差别正是判据：前者的 `campfire_options().rest` 是 false，后者是 true 但回 0 点。""",
        'NoRest doc')

t = sub(t, """    /// §259: `coffee_dripper` -- "you can no longer Rest at a campfire"."
""",
        """    /// §259: `coffee_dripper` -- "you can no longer Rest at a campfire"."
""", 'sanity') if False else t

# 在 `NoRest` 变体后面加 `NoHeal`（用 `NoRest` 的定义本身做锚点）。
t = sub(t, """            "mark_of_the_bloom" => Some(RelicEffect::NoRest),""",
        """            // §321：`mark_of_the_bloom` —— "You can no longer heal"（wiki）。
            // ⚠️ 原来映射到 `NoRest` 是**错的**：它不禁休息，它禁治疗。
            "mark_of_the_bloom" => Some(RelicEffect::NoHeal),""",
        'mark mapping')

# ── 2. 治疗汇：唯一的 gate ────────────────────────────────────────────────────────
t = sub(t, """    pub fn heal_after_combat(&mut self, amount: i32) {
        self.health = (self.health + amount).min(self.health_max);
    }""",
        """    pub fn heal_after_combat(&mut self, amount: i32) {
        // §321：`mark_of_the_bloom` —— "You can no longer heal"。这条规则放在**唯一的治疗汇**上，
        // 于是休息、遗物（`Meat on the Bone` / `Burning Blood` 的结算侧）、事件（`heal` /
        // `heal_pct` / `heal_full`）一次全覆盖 —— 而不是在每个调用点各记一遍。
        //
        // ⚠️ 战斗**内**的治疗（药水、战斗侧的回合末触发）不走这里，见 §321 的已知缺口。
        if self.blocks_healing() {
            return;
        }
        self.health = (self.health + amount).min(self.health_max);
    }

    /// §321：这一局还能不能治疗（`mark_of_the_bloom` = 不能）。
    ///
    /// 单独一个读法是因为**页面也要它**（血条旁边写"不能治疗"），而且判据要能直接问它 ——
    /// 一个埋在 `heal_after_combat` 里的 `if` 只能靠"回血量恰好是 0"间接证明。
    #[must_use]
    pub fn blocks_healing(&self) -> bool {
        self.holds_relic_effect(RelicEffect::NoHeal)
    }""",
        'heal gate')

# ── 3. `EventEffect::UpgradeAll` ─────────────────────────────────────────────────
t = sub(t, """    /// §320：**候选列表**（`offer_cards:<n>:<filter>`）""",
        """    /// §321：**升级牌组里的每一张**（`upgrade_all`）。`mind_bloom` 的 `[I am Awake]`。
    ///
    /// 与 `UpgradeCard`（问玩家一张）的区别：这是一次结算，没有问句。内容里的 `+` 行是**另一张卡**，
    /// 所以"能不能升"由池子决定（没有 `+` 行、或已经是 `+` ⇒ 什么也不发生，与 `Upgrade` 同一条规则）。
    UpgradeAll,
    /// §320：**候选列表**（`offer_cards:<n>:<filter>`）""",
        'UpgradeAll variant')

t = sub(t, """            "remove_card" => (Self::RemoveCard, None),""",
        """            "remove_card" => (Self::RemoveCard, None),
            // §321：`mind_bloom` 的 `[I am Awake]` —— 升级**所有**牌（没有问句）。
            "upgrade_all" => (Self::UpgradeAll, None),""",
        'parse upgrade_all')

t = sub(t, """            EventEffect::RemoveCard | EventEffect::UpgradeCard | EventEffect::TransformCard => {""",
        """            // §321：升级牌组里的每一张（`upgrade_at` 已经是"没有 `+` 行 ⇒ 什么也不做"）。
            EventEffect::UpgradeAll => {
                for index in 0..self.deck_len as usize {
                    self.upgrade_at(index, pool)?;
                }
            }
            EventEffect::RemoveCard | EventEffect::UpgradeCard | EventEffect::TransformCard => {""",
        'apply upgrade_all')

io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
print('state.rs: upgrade_all + NoHeal ok')
