"""§156: two more relic effects, and **rarity-weighted** relic and potion drops.

Effects (both faithful to the wiki, both tiny):

* `RestHealBonus(i32)` -- Regal Pillow: "Resting heals 15 additional HP". The rest heal is computed
  in `rest()`, so this is one `+` there.
* `EndOfCombatHealIfBelow { percent, amount }` -- Meat on the Bone: "If your HP is at or below 50% at
  the end of combat, heal 12". A conditional version of the existing `EndOfCombatHeal`, and the
  condition reads the *current* max HP (Pear/Strawberry move it).

Drops: one weighted helper for both relics and potions, because both are "pick from a pool whose
entries have a rarity".

    relic  50 / 33 / 17  (Common / Uncommon / Rare)
    potion 65 / 25 / 10

Both sets are the wiki's. The helper picks a **band** by weight and then a uniform entry inside it --
that is what StS does, and it means "no uncommons left in the pool" degrades to the remaining bands
instead of biasing silently.
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


# ---- 1. the two effect variants ----------------------------------------------------------------
replace_once(
    """    StartCombatStatus(&'static str, i32),
}""",
    """    StartCombatStatus(&'static str, i32),
    /// Resting heals this much more (`regal_pillow`, wiki: +15).
    RestHealBonus(i32),
    /// Heal `amount` at the end of a fight **only when HP is at or below `percent` of maximum**
    /// (`meat_on_the_bone`, wiki: 12 HP at or below 50%).
    EndOfCombatHealIfBelow { percent: i32, amount: i32 },
}""",
    "RelicEffect variants",
)

replace_once(
    """            "thread_and_needle" => Some(RelicEffect::StartCombatStatus("standard.plated_armor", 4)),
            _ => None,""",
    """            "thread_and_needle" => Some(RelicEffect::StartCombatStatus("standard.plated_armor", 4)),
            // §156 (wiki numbers): Strawberry +7 max HP, Bronze Scales 3 Thorns at combat start,
            // Regal Pillow +15 on rest, Meat on the Bone 12 HP at or below 50%.
            "strawberry" => Some(RelicEffect::MaxHealthUp(7)),
            "bronze_scales" => Some(RelicEffect::StartCombatStatus("standard.thorns", 3)),
            "regal_pillow" => Some(RelicEffect::RestHealBonus(15)),
            "meat_on_the_bone" => Some(RelicEffect::EndOfCombatHealIfBelow {
                percent: 50,
                amount: 12,
            }),
            _ => None,""",
    "relic_effect table",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("effects added")
