"""§154: every upgradable card needs a `+` row -- the campfire was handing out cards the fight
builder had never heard of.

The report: `开战被拒 · build_fight_from_content: UnknownCard(CardDefinitionId("iron_wave+"))`.
The run's upgrade path appends `+` to the card id (`RunState::upgrade_at`), so a card **without** a
`+` row becomes an id the image does not contain: the run is fine until the next fight, which then
refuses to build. §147 fixed this for `whirlwind` only, and even wrote the lesson down; nine other
cards still had no upgraded row.

Numbers are the wiki's where the card is a real StS card (`Anger` 6→8, `Twin Strike` 5→7 twice,
`Iron Wave` 5/5→7/7, `Clothesline` 12→14 and 2→3 Weak, `Uppercut` 13 stays, 1→2 Weak and 1→2
Vulnerable, `Apparition` 1→2 Intangible, `Buffer` 1→2). `Sentinel` / `Patient Guard` / `Swift
Strike` are this content's own numbers, so they follow the same "+3 for a 1-cost attack or block
card" spread the basic cards use (`Strike` 6→9, `Defend` 5→8).

`Anger+` copies **itself** (`anger+`), not the base card: StS's Anger adds a copy of the card that
was played, and an upgraded Anger adding a downgraded copy is the kind of quiet downgrade a player
notices turns later.

Run:  python D:\\Vibe\\sts-tui\\native\\patch_154_upgrades.py
"""

import copy
import io
import json
import os

SRC = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "tools", "contentc", "packages", "sts", "sts.roguedeck.json",
)

# id -> (new damage amounts in traversal order, new block amounts, new status stacks, new text)
UPGRADES = {
    "anger": ([8], [], [], "Deal 8 damage. Add a copy of this card into your discard pile."),
    "twin_strike": ([7, 7], [], [], "Deal 7 damage twice."),
    "iron_wave": ([7], [7], [], "Gain 7 Block. Deal 7 damage."),
    "clothesline": ([14], [], [3], "Deal 14 damage. Apply 3 Weak."),
    "uppercut": ([13], [], [2, 2], "Deal 13 damage. Apply 2 Weak. Apply 2 Vulnerable."),
    "sentinel": ([], [8], [], "Gain 8 Block. Ethereal."),
    "patient_guard": ([], [8], [], "Gain 8 Block. Retain."),
    "swift_strike": ([9], [], [], "Innate. Deal 9 damage."),
    "apparition": ([], [], [2], "Gain 2 Intangible. Exhaust."),
    "buffer": ([], [], [2], "Gain 2 Buffer."),
}

with io.open(SRC, encoding="utf-8") as handle:
    document = json.load(handle)

cards = document["Cards"]
by_id = {card["Id"]: card for card in cards}


def apply_upgrade(node, damage, block, stacks, counters):
    """Walk the program in traversal order, replacing each effect's amount from the lists."""
    kind = node.get("kind")
    value = node.get("value") or {}
    if kind == "node.dealDamage" and counters[0] < len(damage):
        value["Amount"]["value"]["Value"] = damage[counters[0]]
        counters[0] += 1
    elif kind == "node.gainBlock" and counters[1] < len(block):
        value["Amount"]["value"]["Value"] = block[counters[1]]
        counters[1] += 1
    elif kind == "node.applyStatus" and counters[2] < len(stacks):
        value["Stacks"]["value"]["Value"] = stacks[counters[2]]
        counters[2] += 1
    for child in value.get("Children") or []:
        apply_upgrade(child, damage, block, stacks, counters)


added = []
for card_id, (damage, block, stacks, text) in UPGRADES.items():
    upgraded_id = card_id + "+"
    if upgraded_id in by_id:
        continue
    base = by_id.get(card_id)
    if base is None:
        raise SystemExit("no base card " + card_id)
    row = copy.deepcopy(base)
    row["Id"] = upgraded_id
    row["NameKey"] = base["NameKey"] + "+"
    row["DescriptionKey"] = text
    apply_upgrade(row["Program"]["Root"], damage, block, stacks, [0, 0, 0])
    # An upgraded `Anger` copies the upgraded card (§154).
    def retarget(node):
        value = node.get("value") or {}
        if node.get("kind") == "node.createCardInstance":
            if value["CardDefinitionId"]["value"] == card_id:
                value["CardDefinitionId"]["value"] = upgraded_id
        for child in value.get("Children") or []:
            retarget(child)
    retarget(row["Program"]["Root"])
    cards.append(row)
    added.append(upgraded_id)

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("added:", added)
print("cards now:", len(cards), [card["Id"] for card in cards])
