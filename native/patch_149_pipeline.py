"""§149: the three damage-pipeline statuses and their carriers.

* **Intangible** (wiki): "Reduce ALL damage and HP loss you receive to 1." -- kernel
  (`exec::resolve_damage_of_kind`, before Block absorbs).
* **Buffer** (wiki): "Prevent the next time you would lose HP." -- kernel, after Block absorbs
  (so a fully-blocked hit does not eat the Buffer).
* **Plated Armor** (wiki): "At the end of your turn, gain X Block. Loses 1 stack when you take
  unblocked damage." -- block half shares the Metallicize step, stack half is in the pipeline.

Carriers:

* `apparition` -- the real colourless card ("Gain 1 Intangible. Exhaust.").
* `buffer` -- StS's Buffer is a Defect power; here it is a skill with the same effect.
* `thread_and_needle` -- the real relic ("Start each combat with 4 Plated Armor"), which is how
  Plated Armor reaches the player in StS.

Run:  python D:\\Vibe\\sts-tui\\native\\patch_149_pipeline.py
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

statuses = document["Statuses"]
existing = {status["Id"] for status in statuses}

new_statuses = [
    {
        "Id": "standard.intangible",
        "PackageId": "sts",
        "NameKey": "Intangible",
        "DescriptionKey": "Reduce ALL damage and HP loss you receive to 1.",
        "Polarity": "Buff",
        "UsesStacks": True,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["buff", "intangible"],
        "PassiveModifiers": [],
        "Triggers": [],
    },
    {
        "Id": "standard.buffer",
        "PackageId": "sts",
        "NameKey": "Buffer",
        "DescriptionKey": "Prevent the next time you would lose HP.",
        "Polarity": "Buff",
        "UsesStacks": True,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["buff", "buffer"],
        "PassiveModifiers": [],
        "Triggers": [],
    },
    {
        "Id": "standard.plated_armor",
        "PackageId": "sts",
        "NameKey": "Plated Armor",
        "DescriptionKey": "At the end of your turn, gain Block equal to its stacks. "
                          "Loses 1 stack when you take unblocked damage.",
        "Polarity": "Buff",
        "UsesStacks": True,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["buff", "plated_armor"],
        "PassiveModifiers": [],
        "Triggers": [],
    },
]
for status in new_statuses:
    if status["Id"] not in existing:
        statuses.append(status)

# ---- cards: `apparition` and `buffer` ------------------------------------------------
cards = document["Cards"]
template = next(card for card in cards if card["Id"] == "sentinel")
existing_cards = {card["Id"] for card in cards}


def selector(kind, capability, cardinality="ZeroOrOne"):
    return {"kind": kind,
            "value": {"Cardinality": cardinality,
                      "RequiredContextCapabilities": capability}}


def apply_status(status_id, stacks, source):
    return {
        "kind": "node.applyStatus",
        "value": {
            "TargetSelector": selector("sel.source", "Source") if source else selector(
                "sel.eventTarget", "EventTarget"),
            "StatusDefinitionId": {"value": status_id},
            "Stacks": {"kind": "const", "value": {"Value": stacks}},
            "DurationTurns": 0,
            "Charges": 0,
            "ResultKey": None,
        },
    }


def card(card_id, name, text, cost, tags, root, rarity="Uncommon", played_zone="DiscardPile"):
    record = json.loads(json.dumps(template))
    record["Id"] = card_id
    record["NameKey"] = name
    record["DescriptionKey"] = text
    record["Costs"] = [{"ResourceId": {"value": "standard.energy"}, "Amount": cost}]
    record["Tags"] = [{"value": tag} for tag in tags]
    record["Program"]["Root"] = root
    record["Rarity"] = rarity
    record["RetainInHandOnTurnEnd"] = False
    record["TurnEndHandDestinationZone"] = "DiscardPile"
    record["PlayedCardDestinationZone"] = played_zone
    return record


new_cards = [
    # Real card (colourless): "Gain 1 Intangible. Exhaust." 1 cost.
    card("apparition", "Apparition", "Gain 1 Intangible. Exhaust.", 1,
         ["skill", "intangible"], apply_status("standard.intangible", 1, source=True),
         played_zone="ExhaustPile"),
    # StS's Buffer is a power; here it is a skill with the same effect.
    card("buffer", "Buffer", "Gain 1 Buffer.", 1,
         ["skill", "buffer"], apply_status("standard.buffer", 1, source=True)),
]
for record in new_cards:
    if record["Id"] not in existing_cards:
        cards.append(record)

# ---- relic: Thread and Needle ------------------------------------------------------
relics = document["Relics"]
if not any(relic["Id"] == "thread_and_needle" for relic in relics):
    relics.append({
        "Id": "thread_and_needle",
        "DisplayName": "Thread and Needle",
        "RunPrograms": None,
        "CombatRules": None,
    })

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("statuses:", len(statuses), "cards:", len(cards), "relics:", len(relics))
