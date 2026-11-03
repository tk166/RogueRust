"""§183: Colorless Potion -- "Choose 1 of 3 random Colorless cards to add to your hand."

The potion atom already exists (`choice_offered:<tag>`, §161.5); what was missing was **colorless
cards to offer** and a guarantee that they never leak into the ordinary reward pool.

Wiki (`slaythespire.wiki.gg/wiki/Colorless_Cards`, base values):
* **Bandage Up** (Uncommon, Skill, 0) -- "Heal 4 HP. Exhaust."
* **Blind** (Common, Skill, 0) -- "Apply 2 Weak to ALL enemies."
* **Dark Shackles** (Uncommon, Skill, 0) -- "Enemy loses 9 Strength. At the end of this turn,
  regain the Strength." -- this one uses `standard.lose_strength`, which this content already has
  (Flex/Speed Potion's partner), so the "regain" half is a status this engine already understands.
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"
RUN = "kernel/rd-wasm/src/run.rs"

SELF = {
    "kind": "sel.sourceIncludingDowned",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"},
}
EVENT_TARGET = {
    "kind": "sel.eventTarget",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"},
}
ALL_ENEMIES = {
    "kind": "sel.allEnemies",
    "value": {"Cardinality": "Many", "RequiredContextCapabilities": "Source"},
}


def card(card_id, name, description, root, tags):
    return {
        "Id": card_id,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": description,
        "Costs": [{"ResourceId": {"value": "standard.energy"}, "Amount": 0}],
        "Tags": [{"value": tag} for tag in tags],
        "Program": {"Id": {"Value": "(unnamed)"}, "Root": root},
        "PlayedCardDestinationZone": {"value": "Exhaust"},
        "RetainInHandOnTurnEnd": False,
        "IsAction": False,
    }


def const(value):
    return {"kind": "const", "value": {"Value": value}}


def status_node(target, status_id, stacks):
    return {
        "kind": "node.applyStatus",
        "value": {
            "TargetSelector": target,
            "StatusDefinitionId": {"value": status_id},
            "Stacks": const(stacks),
            "Duration": const(0),
            "Charges": const(0),
            "ResultKey": None,
            "Children": [],
            "SourceCardId": None,
        },
    }


CARDS = [
    card(
        "bandage_up",
        "Bandage Up",
        "Heal 4 HP. Exhaust.",
        {"kind": "node.heal", "value": {"TargetSelector": SELF, "Amount": const(4)}},
        ["skill", "colorless"],
    ),
    card(
        "blind",
        "Blind",
        "Apply 2 Weak to ALL enemies.",
        status_node(ALL_ENEMIES, "standard.weak", 2),
        ["skill", "colorless"],
    ),
    card(
        "dark_shackles",
        "Dark Shackles",
        "Enemy loses 9 Strength. At the end of this turn, regain it.",
        {"kind": "node.sequence", "value": {"Children": [
            status_node(EVENT_TARGET, "standard.lose_strength", 9),
            status_node(EVENT_TARGET, "standard.strength", -9),
        ]}},
        ["skill", "colorless"],
    ),
]

POTION = {
    "Id": "colorless_potion",
    "NameKey": "Colorless Potion",
    "DescriptionKey": "Choose 1 of 3 random Colorless cards to add to your hand. It costs 0 this turn.",
    "Effect": "choice_offered:colorless",
    "Amount": 0,
    "Rarity": "Common",
}


def main():
    document = json.load(io.open(SRC, encoding="utf-8"))
    existing = {row["Id"] for row in document["Cards"]}
    for row in CARDS:
        if row["Id"] not in existing:
            document["Cards"].append(row)
            print("card added:", row["Id"])
    if not any(potion["Id"] == POTION["Id"] for potion in document["Potions"]):
        document["Potions"].append(POTION)
        print("potion added")
    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    # ---- the reward pool must not offer them ------------------------------------------------
    text = io.open(RUN, encoding="utf-8").read()
    old = """        // `rd-run` drops `Status`/`Curse` from the roll itself -- one rule, one owner.
        pool.push(card);"""
    new = """        // §183: **colorless cards are not combat rewards.** StS keeps them in their own pool
        // (shops and some events); before this filter the three colorless rows added for the
        // Colorless Potion would have made every fight able to pay one -- a content bug that no
        // gate would have caught, because "a card was offered" is true either way.
        if content.card_has_tag(id, "colorless") == Some(true) {
            continue;
        }
        // `rd-run` drops `Status`/`Curse` from the roll itself -- one rule, one owner.
        pool.push(card);"""
    assert text.count(old) == 1, text.count(old)
    io.open(RUN, "w", encoding="utf-8", newline="").write(text.replace(old, new))
    print("reward pool excludes colorless")
    print("cards:", len(document["Cards"]), "potions:", len(document["Potions"]))


if __name__ == "__main__":
    main()
