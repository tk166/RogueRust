"""§157: three more relics (2 Rare + 1 Common) so the rare band is not a single relic.

The rare band carries 17% of the weight, so with one rare in the pool a long run hands out the same
relic over and over and then stops offering (a held relic is filtered out). Two rares and one more
common is the cheapest honest fix -- and each new effect already exists in the run layer.

| relic | rarity | wiki effect |
|---|---|---|
| Eternal Feather | Rare | Resting heals 3 HP for every 5 cards in the deck |
| Golden Idol | Rare | Enemies drop 25% more gold |
| Potion Belt | Common | +2 potion slots (the only way to raise the three) |
"""

import io
import json
import os

SRC = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "tools", "contentc", "packages", "sts", "sts.roguedeck.json",
)

NEW = [
    ("eternal_feather", "Eternal Feather", "Rare"),
    ("golden_idol", "Golden Idol", "Rare"),
    ("potion_belt", "Potion Belt", "Common"),
]

with io.open(SRC, encoding="utf-8") as handle:
    document = json.load(handle)

relics = document["Relics"]
existing = {relic["Id"] for relic in relics}
for relic_id, display, rarity in NEW:
    if relic_id in existing:
        continue
    relics.append({
        "Id": relic_id,
        "DisplayName": display,
        "RunPrograms": None,
        "CombatRules": None,
        "Rarity": rarity,
    })

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print([(relic["Id"], relic["Rarity"]) for relic in relics])
