"""§147: Whirlwind's upgraded row + the Constricted status and its carrier (Spire Growth).

Numbers come from the wiki, not from invention:

* **Whirlwind+**: "Deal 8 damage to ALL enemies X times." (base 5) -- same X-cost mechanics.
* **Constricted X**: "At the end of your turn, lose X HP." (a debuff, no duration, stacks merge;
  the HP loss is *not* damage, so Block does not absorb it -- that is why the trigger's
  `dealDamage` sets `IgnoresBlock: true`).
* **Spire Growth** (act 3, "The Beyond"): HP **170**, moves `Strategic` (apply Constricted) /
  `Aggressive` (16 damage) / `Aggressive` (22 damage). Source: slayspiredb.com/sts1/bestiary/
  spire-growth, which lists 170 below Ascension 7 and 190 at 7+ -- this content has no Ascension,
  so 170.

Run:  python D:\\Vibe\\sts-tui\\native\\patch_147_constricted.py
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
statuses = document["Statuses"]
actions = document["EnemyActions"]
enemies = document["Encounters"]

# ---- 1. Whirlwind+ ---------------------------------------------------------------
whirlwind = next(card for card in cards if card["Id"] == "whirlwind")
if any(card["Id"] == "whirlwind+" for card in cards):
    raise SystemExit("already patched: whirlwind+ exists")

upgraded = json.loads(json.dumps(whirlwind))
upgraded["Id"] = "whirlwind+"
upgraded["NameKey"] = "Whirlwind+"
upgraded["DescriptionKey"] = "Deal 8 damage to ALL enemies X times."
# The upgrade is the **damage per hit** (5 -> 8); X stays X.
upgraded["Program"]["Root"]["value"]["Body"]["value"]["Amount"]["value"]["Value"] = 8
cards.append(upgraded)

# ---- 2. Constricted --------------------------------------------------------------
if not any(status["Id"] == "standard.constricted" for status in statuses):
    reference = next(status for status in statuses if status["Id"] == "standard.combust")


    def selector(kind, capability, cardinality="ZeroOrOne"):
        return {
            "kind": kind,
            "value": {"Cardinality": cardinality,
                      "RequiredContextCapabilities": capability},
        }


    statuses.append({
        "Id": "standard.constricted",
        "PackageId": "sts",
        "NameKey": "Constricted",
        "DescriptionKey": "At the end of your turn, lose HP equal to its stacks.",
        "Polarity": "Debuff",
        "UsesStacks": True,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["debuff", "constricted"],
        "PassiveModifiers": [],
        "Triggers": [
            {
                "Event": "TurnEnded",
                "Program": {
                    "Id": {"Value": "(unnamed)"},
                    "Root": {
                        "kind": "node.dealDamage",
                        "value": {
                            # 承受者 = 状态的持有者（`TurnEnded` 的 Bearer 就是 `sel.source`）。
                            "TargetSelector": selector("sel.source", "Source"),
                            "Amount": {
                                "kind": "combatantStatusStacks",
                                "value": {
                                    "Selector": selector("sel.source", "Source"),
                                    "StatusId": {"value": "standard.constricted"},
                                },
                            },
                            "ResultKey": None,
                            # "lose HP" 不是伤害：Block 挡不住，所以这一格必须是 true。
                            "IgnoresBlock": True,
                            "Element": None,
                        },
                    },
                    "MaxNodeDepth": 64,
                    "MaxProgramSteps": 1024,
                },
            }
        ],
    })
    del reference  # only used to confirm the shape above matches an existing row

# ---- 3. Spire Growth: three actions ------------------------------------------------
new_actions = [
    {
        "Id": "spire_growth.strategic",
        "PackageId": "sts",
        "NameKey": "Strategic",
        "DescriptionKey": "Strategic - 2 Constricted",
        "Intent": {"Kind": "Debuff", "Label": "Strategic - 2 Constricted"},
        "Program": {
            "Id": {"Value": "(unnamed)"},
            "Root": {
                "kind": "node.applyStatus",
                "value": {
                    "TargetSelector": {
                        "kind": "sel.eventTarget",
                        "value": {"Cardinality": "ZeroOrOne",
                                  "RequiredContextCapabilities": "EventTarget"},
                    },
                    "StatusDefinitionId": {"value": "standard.constricted"},
                    "Stacks": {"kind": "const", "value": {"Value": 2}},
                    "DurationTurns": 0,
                    "Charges": 0,
                    "ResultKey": None,
                },
            },
            "MaxNodeDepth": 64,
            "MaxProgramSteps": 1024,
        },
    },
]


def aggressive(action_id, damage):
    return {
        "Id": action_id,
        "PackageId": "sts",
        "NameKey": "Aggressive",
        "DescriptionKey": "Aggressive - %d damage" % damage,
        "Intent": {"Kind": "Attack", "Label": "Aggressive - %d damage" % damage},
        "Program": {
            "Id": {"Value": "(unnamed)"},
            "Root": {
                "kind": "node.dealDamage",
                "value": {
                    "TargetSelector": {
                        "kind": "sel.eventTarget",
                        "value": {"Cardinality": "ZeroOrOne",
                                  "RequiredContextCapabilities": "EventTarget"},
                    },
                    "Amount": {"kind": "const", "value": {"Value": damage}},
                    "ResultKey": None,
                    "IgnoresBlock": False,
                    "Element": None,
                },
            },
            "MaxNodeDepth": 64,
            "MaxProgramSteps": 1024,
        },
    }


new_actions.append(aggressive("spire_growth.aggressive", 16))
new_actions.append(aggressive("spire_growth.aggressive_heavy", 22))
existing_action_ids = {action["Id"] for action in actions}
for action in new_actions:
    if action["Id"] not in existing_action_ids:
        actions.append(action)

# ---- 4. The encounter (the monster roster is documentation; ENCT carries the inline record) ----
action_refs = [{"value": action["Id"]} for action in new_actions]
if any(encounter["Id"]["Value"] == "enc_spire_growth" for encounter in enemies):
    raise SystemExit("already patched: enc_spire_growth exists")
enemies.append({
    "Id": {"Value": "enc_spire_growth"},
    "Enemies": [
        {
            "Id": "spire_growth",
            "MaxHealth": 170,
            "Actions": action_refs,
            "StartingStatuses": [],
            "Position": 0,
            "IntentRules": [],
            "DisplayName": "Spire Growth",
        }
    ],
    "HeroResources": [
        {"Resource": {"value": "standard.energy"}, "Current": 3, "Max": 3}
    ],
    "HeroStartingStatuses": [],
    "TriggeredEffects": [],
    "HeroDisplayName": None,
    "CardsDrawnPerTurn": None,
})

# The roster entry (Monsters is "documentation only" per InertKeys, but the inventory checks it).
if not any(monster["Id"] == "spire_growth" for monster in document["Monsters"]):
    document["Monsters"].append({
        "Id": "spire_growth",
        "NameKey": "Spire Growth",
        "HpMin": 170,
        "HpMax": 170,
        "MaxHealth": 170,
        "Actions": action_refs,
        "StartingStatuses": [],
        "IntentRules": [],
        "Tier": "Normal",
        "InvRef": "https://slayspiredb.com/sts1/bestiary/spire-growth",
        "AiNote": "§147 第三幕普通怪；Constricted 的载体（wiki: Strategic / Aggressive 16 / 22）。",
    })

# ---- 5. Act 3's normal pool -------------------------------------------------------
tables = document["EventTables"]  # untouched; kept here to mirror the layout of the document
tables = document["EncounterTables"]
weak3 = tables.setdefault("Weak3", [])
if not any(entry["Id"] == "enc_spire_growth" for entry in weak3):
    weak3.append({"Id": "enc_spire_growth"})

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("cards:", len(cards), "statuses:", len(statuses), "actions:", len(actions),
      "encounters:", len(enemies))
print("weak3:", [entry["Id"] for entry in weak3])
