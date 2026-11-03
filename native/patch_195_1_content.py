"""§195.1 content: The Guardian's Mode Shift becomes the wiki's "after losing X HP".

What §194 did (and why it was wrong): it keyed the shift on `intent.healthPercent <= 50`, because the
kernel's `DamageTaken` event carried **no number**, so "accumulate 30 HP of damage" was unwritable.
§195.1 added the number (`eventAmount` = HP actually lost), so the real thing is now expressible:

    status standard.mode_shift   (on the Guardian, 1 stack)
      Trigger DamageTaken -> setCombatantCounter{ mode_shift_damage += eventAmount, relative }

    intent rule   compare{ counter(mode_shift_damage)
                           >= add(30, multiply(counter(guard_shifts), 10)) }
                  -> the_guardian.defensive_mode

    defensive_mode  sets mode_shift_damage = 0 and guard_shifts += 1

Wiki (`native/wiki_asc/the_guardian.txt`): "After losing X HP, gains 20 Block and changes current
Intent to Defensive Mode. ... Twin Slam ... gains 30 (A9 35, A19 40) Mode Shift, **increased by 10 for
each time Mode Shift triggered this combat**."

So the threshold is `30 + 10 * triggers` (the wiki's "increased by 10 each time" is the same rule
StS implements by adding 10 to the power's amount), and it is written as one `compare` with an
expression on each side -- no new intent vocabulary.

⚠️ Two deviations, both stated:

1. **The damage that counts is HP actually lost** (`health_damage`), so a fully blocked hit shifts
   nothing. StS's `ModeShiftPower.onAttacked` sees the damage after block as well, so this matches;
   what it does *not* match is StS's exact ordering when several hits land in one turn (ours
   accumulates, theirs also accumulates -- fine).
2. **The swap lands on the next intent** in the sense that the *current* displayed intent is
   re-derived per observation, so the player sees the change as soon as the counter crosses the
   threshold; the boss's own turn then uses the new intent. There is no "cancel the action it is
   already performing" because an enemy action only runs on its own turn.
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

document = json.load(io.open(SRC, encoding="utf-8"))
statuses = document["Statuses"]
by_status = {row["Id"]: row for row in statuses}
actions = {row["Id"]: row for row in document["EnemyActions"]}
monsters = {row["Id"]: row for row in document["Monsters"]}
encounters = document["Encounters"]


def set_counter(name, value, relative=False):
    return {
        "kind": "node.setCombatantCounter",
        "value": {
            "TargetSelector": {"kind": "sel.source",
                               "value": {"Cardinality": "ZeroOrOne",
                                         "RequiredContextCapabilities": "Source"}},
            "CounterId": {"value": name},
            "Amount": {"kind": "const", "value": {"Value": value}},
            "Relative": relative,
            "ResultKey": None,
        },
    }


# ---------------------------------------------------------------- 1. the carrier status
if "standard.mode_shift" not in by_status:
    statuses.append({
        "Id": "standard.mode_shift",
        "PackageId": "sts",
        # Keep the counter on the **status'** bearer, in a counter the intent rules can read.
        "NameKey": "Mode Shift",
        "DescriptionKey": "After losing 30 HP, gains 20 Block and switches to Defensive Mode.",
        "Polarity": "Buff",
        "UsesStacks": False,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["buff", "mode_shift"],
        "PassiveModifiers": [],
        "Triggers": [{
            "Event": "DamageTaken",
            "Program": {
                "Id": {"Value": "(unnamed)"},
                "Root": set_counter("mode_shift_damage", 0, relative=True) | {
                    # relative + eventAmount : the amount is the HP actually lost (§195.1)
                    "value": {
                        "TargetSelector": {"kind": "sel.source",
                                           "value": {"Cardinality": "ZeroOrOne",
                                                     "RequiredContextCapabilities": "Source"}},
                        "CounterId": {"value": "mode_shift_damage"},
                        "Amount": {"kind": "eventAmount", "value": {}},
                        "Relative": True,
                        "ResultKey": None,
                    }
                },
                "MaxNodeDepth": 64,
                "MaxProgramSteps": 1024,
            },
        }],
    })

# ---------------------------------------------------------------- 2. Defensive Mode keeps the books
mode_shift = 30


def defensive(sharp_hide):
    return {
        "Id": {"Value": "(unnamed)"},
        "Root": {"kind": "node.sequence", "value": {"Children": [
            {"kind": "node.gainBlock",
             "value": {"TargetSelector": {"kind": "sel.source",
                                          "value": {"Cardinality": "ZeroOrOne",
                                                    "RequiredContextCapabilities": "Source"}},
                       "Amount": {"kind": "const", "value": {"Value": 20}},
                       "ResultKey": None}},
            {"kind": "node.applyStatus",
             "value": {"TargetSelector": {"kind": "sel.source",
                                          "value": {"Cardinality": "ZeroOrOne",
                                                    "RequiredContextCapabilities": "Source"}},
                       "StatusDefinitionId": {"value": "standard.sharp_hide"},
                       "Stacks": {"kind": "const", "value": {"Value": sharp_hide}},
                       "DurationTurns": 0,
                       "Charges": 0,
                       "ResultKey": None}},
            # The two books: damage since the last shift resets, and the threshold grows by 10.
            set_counter("mode_shift_damage", 0),
            set_counter("guard_shifts", 1, relative=True),
            set_counter("guard_mode", 1),
            set_counter("guard_step", 0),
        ]}},
        "MaxNodeDepth": 64,
        "MaxProgramSteps": 1024,
    }


guardian_defensive = actions["the_guardian.defensive_mode"]
guardian_defensive["Program"] = defensive(3)
guardian_defensive["ProgramAsc"] = [{"AscensionMin": 19, "Program": defensive(4)}]

# ---------------------------------------------------------------- 3. the intent rules
guardian = monsters["the_guardian"]

SRC_SEL = {"kind": "sel.source",
           "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def counter(name):
    return {"kind": "combatantCounter",
            "value": {"Selector": SRC_SEL, "CounterId": name}}


def threshold_rule():
    """damage >= 30 + 10 * shifts -- both sides of one `compare`, no new vocabulary."""
    return {
        "Condition": {"kind": "compare", "value": {
            "Op": "GreaterOrEqual",
            "Left": counter("mode_shift_damage"),
            "Right": {"kind": "add", "value": {
                "Left": {"kind": "const", "value": {"Value": mode_shift}},
                "Right": {"kind": "multiply", "value": {
                    "Left": counter("guard_shifts"),
                    "Right": {"kind": "const", "value": {"Value": 10}}}}}},
        }},
        "Action": {"value": "the_guardian.defensive_mode"},
        "Priority": 80,
    }


others = [rule for rule in guardian["IntentRules"]
          if rule["Action"]["value"] != "the_guardian.defensive_mode"]
assert len(others) == 3, len(others)
guardian["IntentRules"] = [threshold_rule()] + others
guardian["StartingStatuses"] = [{"StatusDefinitionId": {"value": "standard.mode_shift"},
                                 "Stacks": 1}]
guardian["AiNote"] = (
    "§195.1：wiki 数值（HP 240/250；Fierce Bash 32→A4 36；Whirlwind 5×4；Roll Attack 9→A4 10；"
    "Twin Slam 8×2；Defensive Mode 20 Block + 3 Sharp Hide，A19 4）。"
    "Mode Shift 现在是 **真·累计受伤**：`standard.mode_shift` 的 DamageTaken 触发器把"
    "**实际掉血**（`eventAmount`）加进 `mode_shift_damage`，意图规则在 "
    "`mode_shift_damage >= 30 + 10 × 已触发次数` 时切防御态；防御态把血量重置并让阈值 +10。"
    "Sharp Hide 是精确的（`CardPlayed` + `card.hasTag.attack`）。"
    "⚠️ 偏差：被完全挡住的攻击不算伤害（StS 同理）；切换在**下一次选意图**时生效，没有"
    "『打断正在进行的动作』这一步（敌人只在它自己的回合动作）。")

# ---------------------------------------------------------------- 4. the encounter copy
for encounter in encounters:
    if encounter["Id"]["Value"] != "enc_the_guardian":
        continue
    for slot, enemy in enumerate(encounter["Enemies"]):
        if enemy["Id"] != "the_guardian":
            continue
        encounter["Enemies"][slot]["StartingStatuses"] = list(guardian["StartingStatuses"])
        encounter["Enemies"][slot]["IntentRules"] = list(guardian["IntentRules"])

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print("guardian: real Mode Shift (damage counter + 30 + 10*shifts)")
