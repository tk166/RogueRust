"""Add the §144 keyword cards: Ethereal, Retain, Innate.

Two of the three are **fixtures**: the Ironclad has no Retain and no Innate cards in StS
(checked: "why doesn't Ironclad have a Retain card" is a real community question), so the content
cannot borrow one. What is being exercised is the *keyword*, and the ids say so.

Run:  python D:\\Vibe\\sts-tui\\native\\patch_144_keywords.py
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

cards = document["Cards"]
existing = {card["Id"] for card in cards}

# The shape every card in this package has (cloned from `slimed` so nothing is invented).
template = next(card for card in cards if card["Id"] == "slimed")


def card(card_id, name, text, cost, tags, program_root, rarity="Common",
         retain=False, turn_end_zone="DiscardPile", played_zone="DiscardPile"):
    record = json.loads(json.dumps(template))
    record["Id"] = card_id
    record["NameKey"] = name
    record["DescriptionKey"] = text
    record["Costs"] = [{"ResourceId": {"value": "standard.energy"}, "Amount": cost}]
    record["Tags"] = [{"value": tag} for tag in tags]
    record["Program"]["Root"] = program_root
    record["Rarity"] = rarity
    record["RetainInHandOnTurnEnd"] = retain
    record["TurnEndHandDestinationZone"] = turn_end_zone
    record["PlayedCardDestinationZone"] = played_zone
    return record


def damage(amount):
    return {
        "kind": "node.dealDamage",
        "value": {
            "TargetSelector": {
                "kind": "sel.eventTarget",
                "value": {"Cardinality": "ZeroOrOne",
                          "RequiredContextCapabilities": "EventTarget"},
            },
            "Amount": {"kind": "const", "value": {"Value": amount}},
            "ResultKey": None,
            "IgnoresBlock": False,
            "Element": None,
        },
    }


def block(amount):
    return {
        "kind": "node.gainBlock",
        "value": {
            "TargetSelector": {
                "kind": "sel.source",
                "value": {"Cardinality": "ZeroOrOne",
                          "RequiredContextCapabilities": "Source"},
            },
            "Amount": {"kind": "const", "value": {"Value": amount}},
            "ResultKey": None,
        },
    }


new_cards = [
    # **A real card.** Sentinel (Ironclad, common skill): 5 Block, Ethereal.
    # The kernel gets Ethereal from `TurnEndHandDestinationZone`, not from the tag -- the tag is
    # documentation, and the content gate keeps the two in step.
    card("sentinel", "Sentinel", "Gain 5 Block. Ethereal.", 1,
         ["skill", "ethereal"], block(5), turn_end_zone="ExhaustPile"),
    # **A fixture.** The Ironclad has no Retain card in StS. The keyword is the subject here.
    card("patient_guard", "Patient Guard", "Gain 5 Block. Retain.", 1,
         ["skill", "retain"], block(5), retain=True),
    # **A fixture.** Same reason: no Ironclad card is Innate.
    card("swift_strike", "Swift Strike", "Innate. Deal 6 damage.", 1,
         ["attack", "strike", "innate"], damage(6)),
]

for record in new_cards:
    if record["Id"] in existing:
        raise SystemExit("already patched: %s exists" % record["Id"])
    cards.append(record)

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("cards:", len(cards))
print("added:", [record["Id"] for record in new_cards])
