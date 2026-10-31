"""§157: the rare potion band was **empty**, so 10% of the potion weight had nowhere to go.

The ten potions were nine Common and one Uncommon. The weights (65/25/10) re-normalise over what is
present, so the rare band silently merged into the others -- the exact shape of "declared and unused"
this project keeps banning.

Two fixes, both the wiki's:

* **Fruit Juice** (Rare): "Gain 5 Max HP." A new effect kind `max_hp`, applied to the **run** (not the
  fight) -- the ABI drinks potions inside a fight, and Fruit Juice is one of the few that also works
  outside combat, but "in combat" is the only place this ABI can drink.
* **Regen Potion** is Uncommon in StS (patch 24 notes: "Regen Potion and Ancient Potion are now
  Uncommon"), so the uncommon band gets a second entry too.
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

potions = document["Potions"]
by_id = {potion["Id"]: potion for potion in potions}

if "fruit_juice" not in by_id:
    potions.append({
        "Id": "fruit_juice",
        "NameKey": "Fruit Juice",
        "DescriptionKey": "Gain 5 Max HP.",
        "Effect": "max_hp",
        "Amount": 5,
        "Rarity": "Rare",
    })

if "regen_potion" in by_id:
    by_id["regen_potion"]["Rarity"] = "Uncommon"

# Every act's pool should be able to produce all three bands; the act-3 list gets the rare one and
# act 2 the uncommon, so no act has a band it cannot fill.
for name in ("Potions", "Potions2", "Potions3"):
    rows = document["PotionTables"][name]
    ids = [row["Id"] for row in rows]
    if name == "Potions3" and "fruit_juice" not in ids:
        rows[-1]["Id"] = "fruit_juice"
    if name == "Potions2" and "regen_potion" not in ids:
        rows[-1]["Id"] = "regen_potion"

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print([(potion["Id"], potion["Rarity"]) for potion in potions])
print({name: [row["Id"] for row in document["PotionTables"][name]]
       for name in ("Potions", "Potions2", "Potions3")})
