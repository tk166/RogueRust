"""§157: the moving drop chance, the full-belt rule, and the three new relics.

* `roll_reward` rolls against `potion_chance` (not a constant), then moves it: `-10` on a drop, `+10`
  on a miss, clamped to `0..=100`.
* A **full belt still rolls** (the wiki: the roll happens even when the potion is not shown) -- only
  the offer is suppressed, so the chance keeps moving.
* The act start resets the chance to 40.
* New relics: `eternal_feather` (Rare, rest heals 3 per 5 cards), `golden_idol` (Rare, +25% fight gold),
  `potion_belt` (Common, +2 potion slots).
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


# ---- 1. the effect variants -------------------------------------------------------------------
replace_once(
    """    /// Heal `amount` at the end of a fight **only when HP is at or below `percent` of maximum**
    /// (`meat_on_the_bone`, wiki: 12 HP at or below 50%).
    EndOfCombatHealIfBelow { percent: i32, amount: i32 },
}""",
    """    /// Heal `amount` at the end of a fight **only when HP is at or below `percent` of maximum**
    /// (`meat_on_the_bone`, wiki: 12 HP at or below 50%).
    EndOfCombatHealIfBelow { percent: i32, amount: i32 },
    /// Resting also heals `amount` per **five cards** in the deck (`eternal_feather`, wiki: 3 HP).
    RestHealPerFiveCards(i32),
    /// Fight gold is multiplied by `100 + percent` (`golden_idol`, wiki: +25%).
    FightGoldPercent(i32),
    /// Extra potion slots (`potion_belt`, wiki: +2). The wiki calls it the **only** way to raise the
    /// three slots, which is why the slot count is a method and not the array length (§157).
    ExtraPotionSlots(i32),
}""",
    "three variants",
)

replace_once(
    """            "meat_on_the_bone" => Some(RelicEffect::EndOfCombatHealIfBelow {
                percent: 50,
                amount: 12,
            }),""",
    """            "meat_on_the_bone" => Some(RelicEffect::EndOfCombatHealIfBelow {
                percent: 50,
                amount: 12,
            }),
            // §157 (wiki numbers): Eternal Feather 3 HP per 5 cards on rest, Golden Idol +25% fight
            // gold, Potion Belt +2 slots.
            "eternal_feather" => Some(RelicEffect::RestHealPerFiveCards(3)),
            "golden_idol" => Some(RelicEffect::FightGoldPercent(25)),
            "potion_belt" => Some(RelicEffect::ExtraPotionSlots(2)),""",
    "relic_effect table",
)

# ---- 2. the moving chance + the full-belt rule ------------------------------------------------
replace_once(
    """        // `inv:§9.3`: a potion drops from 40% of fights, on the `Potion` stream.
        let drop = self.rng.roll(RunStream::Potion, 100)? < POTION_DROP_PERCENT;""",
    """        // §157: the wiki's **moving** chance -- 40% to start, -10 after a drop, +10 after a miss.
        // The roll happens even when the belt is full (the wiki's Colosseum note relies on that),
        // so the chance keeps moving; only the **offer** is suppressed below.
        let chance = self.potion_chance.clamp(0, 100) as u32;
        let rolled = self.rng.roll(RunStream::Potion, 100)? < chance;
        self.potion_chance = if rolled {
            (self.potion_chance - POTION_DROP_STEP).max(0)
        } else {
            (self.potion_chance + POTION_DROP_STEP).min(100)
        };
        let drop = rolled && self.potion_room();""",
    "drop roll",
)

# ---- 3. the act start resets it ----------------------------------------------------------------
replace_once(
    """        self.act += 1;""",
    """        self.act += 1;
        // §157: the wiki resets the potion chance "at the start of each Act".
        self.potion_chance = POTION_DROP_START;""",
    "act reset",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("drop chance + relics added")
