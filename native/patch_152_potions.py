"""§152: give the potion vocabulary the shapes the wiki's potions need.

Before this the content had five potions built from **three** effects, and two of them were wrong:

* `swift_potion` was declared as `combat_block` 12 -- a second Block Potion wearing a different name;
* `blood_potion` used `effect: "heal"`, which `rd_env_use_potion` did not handle at all, so drinking
  it was refused with "未知的药水效果" (a dead potion, found while writing the §152 soak).

New shapes (same `kind` or `kind:payload` convention as the event vocabulary, §143):

    combat_block               + amount                  (hero)
    combat_energy              + amount                  (hero)
    combat_heal_percent        + amount (percent of max) (hero)
    combat_draw                + amount                  (hero)
    combat_damage              + amount                  (needs an enemy target)
    combat_damage_all          + amount                  (every living enemy)
    combat_status:<status id>  + amount                  (hero)
    combat_status_target:<id>  + amount                  (needs an enemy target)

Numbers are the wiki's:

| potion | effect | amount |
|---|---|---|
| Fire Potion | combat_damage | 20 |
| Block Potion | combat_block | 12 |
| Energy Potion | combat_energy | 2 |
| Blood Potion | combat_heal_percent | 20 |
| Swift Potion | combat_draw | 3 |
| Explosive Potion | combat_damage_all | 10 |
| Strength Potion | combat_status:standard.strength | 2 |
| Dexterity Potion | combat_status:standard.dexterity | 2 |
| Weak Potion | combat_status_target:standard.weak | 3 |
| Fear Potion | combat_status_target:standard.vulnerable | 3 |

Run:  python D:\\Vibe\\sts-tui\\native\\patch_152_potions.py
"""

import io
import json
import os

SRC = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "tools", "contentc", "packages", "sts", "sts.roguedeck.json",
)

with io.open(SRC, encoding="utf-8") as handle:
    document = json.load(handle)

SPEC = [
    ("fire_potion", "Fire Potion", "Deal 20 damage to the chosen enemy.",
     "combat_damage", 20, "Common"),
    ("block_potion", "Block Potion", "Gain 12 Block.", "combat_block", 12, "Common"),
    ("energy_potion", "Energy Potion", "Gain 2 Energy.", "combat_energy", 2, "Uncommon"),
    ("blood_potion", "Blood Potion", "Heal 20% of your maximum HP.",
     "combat_heal_percent", 20, "Common"),
    ("swift_potion", "Swift Potion", "Draw 3 cards.", "combat_draw", 3, "Common"),
    ("explosive_potion", "Explosive Potion", "Deal 10 damage to ALL enemies.",
     "combat_damage_all", 10, "Common"),
    ("strength_potion", "Strength Potion", "Gain 2 Strength.",
     "combat_status:standard.strength", 2, "Common"),
    ("dexterity_potion", "Dexterity Potion", "Gain 2 Dexterity.",
     "combat_status:standard.dexterity", 2, "Common"),
    ("weak_potion", "Weak Potion", "Apply 3 Weak to the chosen enemy.",
     "combat_status_target:standard.weak", 3, "Common"),
    ("fear_potion", "Fear Potion", "Apply 3 Vulnerable to the chosen enemy.",
     "combat_status_target:standard.vulnerable", 3, "Common"),
]

document["Potions"] = [
    {
        "Id": potion_id,
        "NameKey": name,
        "DescriptionKey": text,
        "Effect": effect,
        "Amount": amount,
        "Rarity": rarity,
    }
    for potion_id, name, text, effect, amount, rarity in SPEC
]

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("potions:", [potion["Id"] for potion in document["Potions"]])
