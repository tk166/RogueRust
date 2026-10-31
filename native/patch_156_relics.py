"""§156: relic rarities in the content, and four more relics.

Rarities are the wiki's (Common / Uncommon / Rare); this content has no boss or shop relics, and the
run layer's `Rarity` has no such variants either -- written down rather than invented.

New relics, all built from effects the run layer already has (plus two small, faithful additions):

| relic | rarity | wiki effect | how |
|---|---|---|---|
| Strawberry | Common | +7 max HP on pickup | `MaxHealthUp(7)` |
| Bronze Scales | Common | deal 3 damage back when attacked | `StartCombatStatus("standard.thorns", 3)` |
| Regal Pillow | Uncommon | rest heals 15 more | `RestHealBonus(15)` -- new |
| Meat on the Bone | Uncommon | after combat, heal 12 if HP <= 50% | `EndOfCombatHealIfBelow { percent: 50, amount: 12 }` -- new |
"""

import io
import json
import os

SRC = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "tools", "contentc", "packages", "sts", "sts.roguedeck.json",
)

RARITY = {
    "burning_blood": "Common",
    "anchor": "Common",
    "vajra": "Common",
    "pear": "Uncommon",
    "blood_vial": "Common",
    "thread_and_needle": "Rare",
    "strawberry": "Common",
    "bronze_scales": "Common",
    "regal_pillow": "Uncommon",
    "meat_on_the_bone": "Uncommon",
}

NEW = [
    ("strawberry", "Strawberry"),
    ("bronze_scales", "Bronze Scales"),
    ("regal_pillow", "Regal Pillow"),
    ("meat_on_the_bone", "Meat on the Bone"),
]

with io.open(SRC, encoding="utf-8") as handle:
    document = json.load(handle)

relics = document["Relics"]
existing = {relic["Id"] for relic in relics}
for relic_id, display in NEW:
    if relic_id in existing:
        continue
    relics.append({
        "Id": relic_id,
        "DisplayName": display,
        "RunPrograms": None,
        "CombatRules": None,
    })

for relic in relics:
    relic["Rarity"] = RARITY.get(relic["Id"], "Common")

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print([(relic["Id"], relic["Rarity"]) for relic in relics])
