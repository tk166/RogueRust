"""§180 content: the Fairy in a Bottle status + the potion.

Wiki (`slaythespire.wiki.gg/wiki/Potions_List`): **Fairy in a Bottle**, Rare --
"When you would die, heal to 30% of your Max HP instead and discard this potion."

Modelled as the reference models a death charm: a **status** whose `DeathPrevention` data holds the
surviving HP, consumed when it fires. `Percent: 30` is our extension -- the reference's record only
carries a flat `SurvivingHealth`, and a flat number cannot say "30% of Max HP" for every hero.

⚠️ Documented deviation: in StS the potion fires **from the belt**, without being drunk. Our belt is
not consulted during a fight (the kernel has no belt), so here the potion is drunk and *then* stands
between the hero and the next killing blow. Same outcome, one extra decision for the player.
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

STATUS = {
    "Id": "standard.fairy_in_a_bottle",
    "PackageId": "sts",
    "NameKey": "Fairy in a Bottle",
    "DescriptionKey": "When you would die, heal to 30% of your Max HP instead.",
    "Polarity": "Buff",
    "UsesStacks": False,
    "UsesDuration": False,
    "UsesCharges": False,
    "StackingBehavior": "RefreshDuration",
    "Tags": ["buff"],
    "PassiveModifiers": [],
    # The one field with any behaviour: the PreDown interceptor (§180).
    "DeathPrevention": {
        "SurvivingHealth": 0,
        "Percent": 30,
        "Repeating": False,
    },
    "Triggers": None,
}

POTION = {
    "Id": "fairy_in_a_bottle",
    "NameKey": "Fairy in a Bottle",
    "DescriptionKey": "When you would die, heal to 30% of your Max HP instead.",
    "Effect": "combat_status:standard.fairy_in_a_bottle",
    "Amount": 1,
    "Rarity": "Rare",
}


def main():
    document = json.load(io.open(SRC, encoding="utf-8"))
    if not any(status["Id"] == STATUS["Id"] for status in document["Statuses"]):
        document["Statuses"].append(STATUS)
        print("status added")
    if not any(potion["Id"] == POTION["Id"] for potion in document["Potions"]):
        document["Potions"].append(POTION)
        print("potion added")
    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("statuses:", len(document["Statuses"]), "potions:", len(document["Potions"]))


if __name__ == "__main__":
    main()
