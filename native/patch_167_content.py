"""§161.7 content: three Ironclad **Power** cards, and the metallicize status they lean on.

Two things here are content **bug fixes**, not new toys:

  1. `standard.metallicize` had `Triggers: null` -- a status that does nothing. `Heart of Iron`
     (6 Metallicize) has been shipping a decorative buff since §158. The trigger below is written
     in the same shape `standard.combust` already uses, so it needs no kernel work.
  2. The `+` rows are in the offered pool. `choice_offered:attack` could hand out `twin_strike+`,
     which StS's Attack Potion never does (a potion gives the printed card). That filter is in
     `rd-wasm`, and §161.7 is where it was found -- while adding power cards made the pool small
     enough to see it.

Numbers are the wiki's: Inflame 2 (3) Strength; Metallicize 3 (4) Block at end of turn;
Combust 5 (7) damage to ALL enemies at the end of your turn, and you lose 1 HP.
"""
import io
import json

PACKAGE = "tools/contentc/packages/sts/sts.roguedeck.json"

SELF = {
    "kind": "sel.source",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"},
}


def apply_status(definition, stacks):
    return {
        "kind": "node.applyStatus",
        "value": {
            "TargetSelector": SELF,
            "StatusDefinitionId": {"value": definition},
            "Stacks": {"kind": "const", "value": {"Value": stacks}},
            "DurationTurns": 0,
            "Charges": 0,
            "ResultKey": None,
        },
    }


def power_card(card_id, name, description, cost, rarity, definition, stacks, upgraded_stacks):
    """One Power card and its `+` row (our upgrade convention: the id gains a `+`)."""
    out = []
    for suffix, amount, desc in (
        ("", stacks, description),
        ("+", upgraded_stacks, None),
    ):
        out.append(
            {
                "Id": card_id + suffix,
                "PackageId": "sts",
                "NameKey": name,
                "DescriptionKey": desc or description,
                "Costs": [
                    {"ResourceId": {"value": "standard.energy"}, "Amount": cost}
                ],
                "Tags": [{"value": "power"}],
                "Program": {
                    "Id": {"Value": "(unnamed)"},
                    "Root": apply_status(definition, amount),
                    "MaxNodeDepth": 64,
                    "MaxProgramSteps": 1024,
                },
                "LifecyclePrograms": {},
                "RetainInHandOnTurnEnd": False,
                "TurnEndHandDestinationZone": "DiscardPile",
                "PlayedCardDestinationZone": "DiscardPile",
                "Rarity": rarity,
            }
        )
    return out


METALLICIZE_TRIGGER = [
    {
        "Event": "TurnEnded",
        "Program": {
            "Id": {"Value": "(unnamed)"},
            "Root": {
                "kind": "node.gainBlock",
                "value": {
                    "TargetSelector": SELF,
                    "Amount": {
                        "kind": "combatantStatusStacks",
                        "value": {
                            "Selector": SELF,
                            "StatusDefinitionId": {"value": "standard.metallicize"},
                        },
                    },
                    "ResultKey": None,
                },
            },
            "MaxNodeDepth": 64,
            "MaxProgramSteps": 1024,
        },
    }
]


def main():
    raw = io.open(PACKAGE, encoding="utf-8").read()
    doc = json.loads(raw)

    # ---- 1. metallicize actually does something ------------------------------------------------
    for status in doc["Statuses"]:
        if status["Id"] == "standard.metallicize":
            assert status.get("Triggers") is None, "already has triggers"
            status["Triggers"] = METALLICIZE_TRIGGER
            break
    else:
        raise SystemExit("standard.metallicize not found")

    # ---- 2. three power cards ------------------------------------------------------------------
    assert not any(c["Id"] == "inflame" for c in doc["Cards"]), "already added"
    doc["Cards"].extend(
        power_card(
            "inflame",
            "Inflame",
            "Gain 2 Strength.",
            1,
            "Uncommon",
            "standard.strength",
            2,
            3,
        )
    )
    doc["Cards"].extend(
        power_card(
            "metallicize",
            "Metallicize",
            "At the end of your turn, gain 3 Block.",
            1,
            "Uncommon",
            "standard.metallicize",
            3,
            4,
        )
    )
    doc["Cards"].extend(
        power_card(
            "combust",
            "Combust",
            "At the end of your turn, lose 1 HP and deal 5 damage to ALL enemies.",
            1,
            "Uncommon",
            "standard.combust",
            5,
            7,
        )
    )

    # ---- 3. Power Potion (the pool now has 6 power rows: 3 cards + their `+`) -------------------
    ids = {p["Id"] for p in doc["Potions"]}
    assert "power_potion" not in ids, "already added"
    doc["Potions"].append(
        {
            "Id": "power_potion",
            "NameKey": "Power Potion",
            "DescriptionKey": "Choose 1 of 3 random Power cards to add to your hand. "
            "It costs 0 this turn.",
            "Effect": "choice_offered:power",
            "Amount": 0,
            "Rarity": "Common",
        }
    )

    io.open(PACKAGE, "w", encoding="utf-8", newline="").write(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    )
    print("content: metallicize trigger + 3 power cards + power_potion")


if __name__ == "__main__":
    main()
