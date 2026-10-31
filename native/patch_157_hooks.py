"""§157: the three new effects in the three hooks, plus the two that actually do work there.

* `push_relic` -- none of the three fires on pickup (the belt slot, the gold rate and the rest bonus
  are read where they are used);
* `end_of_combat` -- none is an end-of-combat effect;
* `combat_bonus` -- none is a combat-start effect;
* `rest_heal` -- Eternal Feather adds `amount * (deck / 5)`;
* `roll_reward` -- Golden Idol multiplies the fight's gold.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()


def replace_once(old, new, why):
    global source
    if old not in source:
        raise SystemExit("anchor missing: " + why)
    source = source.replace(old, new, 1)


# ---- push_relic --------------------------------------------------------------------------------
replace_once(
    """            RelicEffect::RestHealBonus(_)
            | RelicEffect::EndOfCombatHealIfBelow { .. } => {}""",
    """            RelicEffect::RestHealBonus(_)
            | RelicEffect::EndOfCombatHealIfBelow { .. }
            | RelicEffect::RestHealPerFiveCards(_)
            | RelicEffect::FightGoldPercent(_)
            | RelicEffect::ExtraPotionSlots(_) => {}""",
    "push_relic",
)

# ---- end_of_combat ----------------------------------------------------------------------------
replace_once(
    """                    | RelicEffect::StartCombatStatus(_, _)
                    | RelicEffect::RestHealBonus(_),
                ) => {}""",
    """                    | RelicEffect::StartCombatStatus(_, _)
                    | RelicEffect::RestHealBonus(_)
                    | RelicEffect::RestHealPerFiveCards(_)
                    | RelicEffect::FightGoldPercent(_)
                    | RelicEffect::ExtraPotionSlots(_),
                ) => {}""",
    "end_of_combat",
)

# ---- combat_bonus -----------------------------------------------------------------------------
replace_once(
    """                    | RelicEffect::HealUp(_)
                    | RelicEffect::RestHealBonus(_),
                )
                | None => {}""",
    """                    | RelicEffect::HealUp(_)
                    | RelicEffect::RestHealBonus(_)
                    | RelicEffect::RestHealPerFiveCards(_)
                    | RelicEffect::FightGoldPercent(_)
                    | RelicEffect::ExtraPotionSlots(_),
                )
                | None => {}""",
    "combat_bonus",
)

# ---- rest_heal: the feather ----------------------------------------------------------------
replace_once(
    """    pub fn rest_heal(&self) -> i32 {
        // §156: Regal Pillow adds a flat bonus on top of the percentage.
        self.health_max * REST_HEAL_PERCENT / 100 + self.rest_heal_bonus()
    }""",
    """    pub fn rest_heal(&self) -> i32 {
        // §156: Regal Pillow adds a flat bonus on top of the percentage. §157: Eternal Feather adds
        // 3 HP per **five cards** in the deck -- the deck is a run quantity, so it is read here.
        self.health_max * REST_HEAL_PERCENT / 100 + self.rest_heal_bonus() + self.rest_heal_per_cards()
    }

    /// The card-count part of the rest heal (`eternal_feather`, §157).
    #[must_use]
    pub fn rest_heal_per_cards(&self) -> i32 {
        let mut bonus = 0i32;
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::RestHealPerFiveCards(amount)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                bonus += amount * i32::from(self.deck_len) / 5;
            }
        }
        bonus
    }

    /// The fight-gold multiplier in percent (`golden_idol` = 125, §157).
    #[must_use]
    pub fn fight_gold_percent(&self) -> i32 {
        let mut percent = 100i32;
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::FightGoldPercent(bonus)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                percent += bonus;
            }
        }
        percent
    }""",
    "rest_heal",
)

# ---- roll_reward: the idol --------------------------------------------------------------------
replace_once(
    """        let (low, high) = kind.gold();
        let span = (high - low + 1).max(1) as u32;
        let paid = low + self.rng.roll(RunStream::Reward, span)? as i32;
        self.adjust_gold(paid);""",
    """        let (low, high) = kind.gold();
        let span = (high - low + 1).max(1) as u32;
        let base_gold = low + self.rng.roll(RunStream::Reward, span)? as i32;
        // §157: Golden Idol pays 25% more. The multiplier is applied to the rolled amount (integer,
        // truncated) so the reward's `gold` field is what the player was actually given.
        let paid = base_gold * self.fight_gold_percent() / 100;
        self.adjust_gold(paid);""",
    "gold",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("hooks wired")
