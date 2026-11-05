"""§224: the carrier `bag_of_marbles` needed -- a combat-start status that lands on the **enemies**.

§222 tried to express it with `RelicEffect::StartCombatStatus`, and the vertical slice caught the
mistake: `apply_combat_bonus` only knows the hero, so "1 Vulnerable to ALL enemies" became "the hero
is Vulnerable" and the boss fight was unwinnable. The missing thing was a **target** on the bonus,
not a different status.

So `CombatBonus` grows a second list. Two lists rather than one list of `(target, id, stacks)`:

* the two are applied by different code (hero: `combatant_mut(&hero)`; enemies: walk the fight's
  enemy slots), and
* a `Target` field would make every existing reader ask "which one?" for a case that has exactly two
  answers -- the same reason `Rarity` is an enum instead of a string.
"""
import io

RUN = 'kernel/rd-run/src/state.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


# ── ① RelicEffect 新变体 ────────────────────────────────────────────────────────────────────────
one(RUN, """    /// Extra potion slots (`potion_belt`, wiki: +2). The wiki calls it the **only** way to raise the
    /// three slots, which is why the slot count is a method and not the array length (§157).
    ExtraPotionSlots(i32),""",
    """    /// Extra potion slots (`potion_belt`, wiki: +2). The wiki calls it the **only** way to raise the
    /// three slots, which is why the slot count is a method and not the array length (§157).
    ExtraPotionSlots(i32),
    /// §224: start every fight with `stacks` of status `id` on **all enemies** (`bag_of_marbles`:
    /// "At the start of each combat, apply 1 Vulnerable to ALL enemies").
    ///
    /// A separate variant rather than a `Target` on [`Self::StartCombatStatus`]: the two land on
    /// different combatants and are applied by different code, and §222 already proved what happens
    /// when the hero-shaped one is reused ("the hero became Vulnerable and the boss was
    /// unwinnable" -- caught by `ACT1_SLICE`, not by any unit test).
    StartCombatStatusOnEnemies(&'static str, i32),""",
    'RelicEffect variant')

# ── ② CombatBonus 的第二张表 ────────────────────────────────────────────────────────────────────
one(RUN, """    pub statuses: [Option<CombatStatus>; MAX_COMBAT_STATUSES],
    /// How many of [`Self::statuses`] are set.
    pub status_count: usize,
}""",
    """    pub statuses: [Option<CombatStatus>; MAX_COMBAT_STATUSES],
    /// How many of [`Self::statuses`] are set.
    pub status_count: usize,
    /// §224: statuses **the enemies** start the fight with (`bag_of_marbles` = 1 Vulnerable each).
    ///
    /// A second list instead of a `Target` field on [`CombatStatus`]: hero statuses and enemy
    /// statuses are applied by two different pieces of code (one combatant vs "every enemy slot"),
    /// and a target field would make every existing reader ask a question with exactly two answers.
    pub enemy_statuses: [Option<CombatStatus>; MAX_COMBAT_STATUSES],
    /// How many of [`Self::enemy_statuses`] are set.
    pub enemy_status_count: usize,
}""",
    'CombatBonus fields')

one(RUN, """        Self {
            block: 0,
            statuses: [None; MAX_COMBAT_STATUSES],
            status_count: 0,
        }
    }""",
    """        Self {
            block: 0,
            statuses: [None; MAX_COMBAT_STATUSES],
            status_count: 0,
            enemy_statuses: [None; MAX_COMBAT_STATUSES],
            enemy_status_count: 0,
        }
    }""",
    'Default')

one(RUN, """    pub const fn is_empty(&self) -> bool {
        self.block == 0 && self.status_count == 0
    }""",
    """    pub const fn is_empty(&self) -> bool {
        // ⚠️ `enemy_status_count` 必须在这条里 —— 漏了它，"只给敌人挂状态"的遗物会被
        // `apply_combat_bonus` 的早退当成"这场战斗没有加成"，**静默不生效**。
        self.block == 0 && self.status_count == 0 && self.enemy_status_count == 0
    }""",
    'is_empty')

one(RUN, """    pub fn push_status(&mut self, id: &'static str, stacks: i32) -> bool {
        if self.status_count >= MAX_COMBAT_STATUSES {
            return false;
        }
        self.statuses[self.status_count] = Some(CombatStatus { id, stacks });
        self.status_count += 1;
        true
    }""",
    """    pub fn push_status(&mut self, id: &'static str, stacks: i32) -> bool {
        if self.status_count >= MAX_COMBAT_STATUSES {
            return false;
        }
        self.statuses[self.status_count] = Some(CombatStatus { id, stacks });
        self.status_count += 1;
        true
    }

    /// §224：同 [`Self::push_status`]，但**给敌人**。`false` = 表满（响亮，不静默丢一件遗物）。
    pub fn push_enemy_status(&mut self, id: &'static str, stacks: i32) -> bool {
        if self.enemy_status_count >= MAX_COMBAT_STATUSES {
            return false;
        }
        self.enemy_statuses[self.enemy_status_count] = Some(CombatStatus { id, stacks });
        self.enemy_status_count += 1;
        true
    }""",
    'push_enemy_status')

# ── ③ relic_effect + combat_bonus ──────────────────────────────────────────────────────────────
one(RUN, """            "oddly_smooth_stone" => Some(RelicEffect::StartCombatStatus("standard.dexterity", 1)),""",
    """            "oddly_smooth_stone" => Some(RelicEffect::StartCombatStatus("standard.dexterity", 1)),
            // §224（wiki `Bag of Marbles`）：开战给**所有敌人** 1 层易伤。§222 曾把它挂成
            // `StartCombatStatus`（加在英雄身上）⇒ 英雄自己变易伤、Boss 打不过，被 `ACT1_SLICE` 抓到。
            "bag_of_marbles" => Some(RelicEffect::StartCombatStatusOnEnemies(
                "standard.vulnerable",
                1,
            )),""",
    'relic_effect')

io.open(RUN, 'a', encoding='utf-8', newline='\n').write('')
print('phase A done')
