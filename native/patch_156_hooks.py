"""§156: wire the two new relic effects into the three hooks that read the table.

* `push_relic` -- neither fires on pickup, so both join the "not now" arm;
* `end_of_combat` -- `EndOfCombatHealIfBelow` heals only when the HP percentage is at or below the
  threshold; `RestHealBonus` is not an end-of-combat effect;
* `combat_bonus` -- neither is a combat-start effect.

Then `rest()` adds the pillow's bonus. The `rest` heal is a run-layer number, so it is the only place
the bonus can land.
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


# ---- push_relic: neither is a pickup effect ----------------------------------------------------
replace_once(
    """            RelicEffect::EndOfCombatHeal(_)
            | RelicEffect::StartCombatBlock(_)
            | RelicEffect::StartCombatStatus(_, _) => {}""",
    """            RelicEffect::EndOfCombatHeal(_)
            | RelicEffect::StartCombatBlock(_)
            | RelicEffect::StartCombatStatus(_, _)
            | RelicEffect::RestHealBonus(_)
            | RelicEffect::EndOfCombatHealIfBelow { .. } => {}""",
    "push_relic",
)

# ---- end_of_combat: the conditional heal ------------------------------------------------------
replace_once(
    """                Some(RelicEffect::EndOfCombatHeal(amount)) => {
                    let before = self.health;
                    self.heal_after_combat(amount);
                    healed += self.health - before;
                }""",
    """                Some(RelicEffect::EndOfCombatHeal(amount)) => {
                    let before = self.health;
                    self.heal_after_combat(amount);
                    healed += self.health - before;
                }
                // §156: Meat on the Bone -- "if your HP is at or below 50%". The percentage is read
                // off the **current** maximum (Pear/Strawberry move it), same as the intent rules do.
                Some(RelicEffect::EndOfCombatHealIfBelow { percent, amount }) => {
                    let max = self.health_max.max(1);
                    if self.health * 100 <= max * percent {
                        let before = self.health;
                        self.heal_after_combat(amount);
                        healed += self.health - before;
                    }
                }""",
    "end_of_combat conditional",
)

replace_once(
    """                Some(
                    RelicEffect::MaxHealthUp(_)
                    | RelicEffect::HealUp(_)
                    | RelicEffect::StartCombatBlock(_)
                    | RelicEffect::StartCombatStatus(_, _),
                ) => {}""",
    """                Some(
                    RelicEffect::MaxHealthUp(_)
                    | RelicEffect::HealUp(_)
                    | RelicEffect::StartCombatBlock(_)
                    | RelicEffect::StartCombatStatus(_, _)
                    | RelicEffect::RestHealBonus(_),
                ) => {}""",
    "end_of_combat others",
)

# ---- combat_bonus: neither is a combat-start effect -------------------------------------------
replace_once(
    """                Some(
                    RelicEffect::EndOfCombatHeal(_)
                    | RelicEffect::MaxHealthUp(_)
                    | RelicEffect::HealUp(_),
                )
                | None => {}""",
    """                Some(
                    RelicEffect::EndOfCombatHeal(_)
                    | RelicEffect::EndOfCombatHealIfBelow { .. }
                    | RelicEffect::MaxHealthUp(_)
                    | RelicEffect::HealUp(_)
                    | RelicEffect::RestHealBonus(_),
                )
                | None => {}""",
    "combat_bonus others",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("three hooks wired")
