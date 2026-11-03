"""§183 cards, generated (idempotent, one at a time so a broken shape can be bisected).

The binary image is what the kernel reads, and the content gate only reads the JSON -- so a card row
whose *shape* is wrong (an extra/missing key, a node field that decodes as `F_JSON`) passes
`sts_content_check.py` and fails at the first kernel test that touches any program at all. Bisecting
one card at a time is how that was found.

Usage: python native/patch_183_cards.py bandage_up [blind ...]
"""
import io
import json
import sys

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

SELF = {
    "kind": "sel.sourceIncludingDowned",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"},
}
EVENT = {
    "kind": "sel.eventTarget",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"},
}
ALL_ENEMIES = {
    "kind": "sel.allEnemies",
    "value": {"Cardinality": "Many", "RequiredContextCapabilities": "Source"},
}


def const(value):
    return {"kind": "const", "value": {"Value": value}}


def heal(target, amount):
    return {
        "kind": "node.heal",
        "value": {"TargetSelector": target, "Amount": const(amount), "ResultKey": None},
    }


def apply_status(target, status_id, stacks):
    return {
        "kind": "node.applyStatus",
        "value": {
            "TargetSelector": target,
            "StatusDefinitionId": {"value": status_id},
            "Stacks": const(stacks),
            "DurationTurns": const(0),
            "Charges": const(0),
            "ResultKey": None,
        },
    }


def sequence(children):
    return {"kind": "node.sequence", "value": {"Children": children}}


CARDS = {
    "bandage_up": {
        "name": "Bandage Up",
        "description": "Heal 4 HP. Exhaust.",
        "tags": ["skill", "colorless"],
        "rarity": "Uncommon",
        "root": heal(SELF, 4),
    },
    "blind": {
        "name": "Blind",
        "description": "Apply 2 Weak to ALL enemies.",
        "tags": ["skill", "colorless"],
        "rarity": "Common",
        "root": apply_status(ALL_ENEMIES, "standard.weak", 2),
    },
    "dark_shackles": {
        "name": "Dark Shackles",
        "description": "Enemy loses 9 Strength. At the end of this turn, regain it.",
        "tags": ["skill", "colorless"],
        "rarity": "Uncommon",
        "root": sequence(
            [
                apply_status(EVENT, "standard.lose_strength", 9),
                apply_status(EVENT, "standard.strength", -9),
            ]
        ),
    },
}


def main():
    wanted = sys.argv[1:]
    assert wanted, "name at least one card"
    document = json.load(io.open(SRC, encoding="utf-8"))
    # Copy the *shape* of a real card so no key is invented: every field the encoder knows comes
    # from an existing row, and only the program/tags/name differ.
    template = next(card for card in document["Cards"] if card["Id"] == "anger")
    existing = {card["Id"] for card in document["Cards"]}
    for card_id in wanted:
        spec = CARDS[card_id]
        if card_id in existing:
            print("already there:", card_id)
            continue
        row = {}
        for key, value in template.items():
            row[key] = json.loads(json.dumps(value))
        row["Id"] = card_id
        row["NameKey"] = spec["name"]
        row["DescriptionKey"] = spec["description"]
        row["Tags"] = [{"value": tag} for tag in spec["tags"]]
        row["Costs"] = [{"ResourceId": {"value": "standard.energy"}, "Amount": 0}]
        row["PlayedCardDestinationZone"] = "Exhaust"
        row["Rarity"] = spec["rarity"]
        row["Program"] = {"Id": {"Value": "(unnamed)"}, "Root": spec["root"]}
        document["Cards"].append(row)
        print("added", card_id)
    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
