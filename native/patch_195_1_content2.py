"""§195.1 content (take 2): Mode Shift as a **budget**, seeded at spawn.

Take 1 wrote the threshold as `damage >= 30 + 10 * shifts` and put that expression in the *intent
rule* -- which the kernel refuses: a rule's `Condition` must be one of the eleven `intent.*`
kinds, and `intent.selfHasCounter` compares against a **constant**. That is not a bug to fix
(an arbitrary expression in a rule would mean the intent layer needs the whole expression engine
plus a way to explain *why* a rule fired); it is the vocabulary saying "keep the arithmetic in the
*effect* program and the rule a comparison".

So the arithmetic moves into the two programs, and StS's own representation is used:

    Counters: [{"Key": "mode_shift_budget", "Value": 30}]        -- 35 at A9, 40 at A19
    damage taken  -> setCombatantCounter{budget, += -eventAmount}  (relative)
    rule          -> selfHasCounter{budget, LessOrEqual, 0}       -> Defensive Mode
    Defensive Mode-> setCombatantCounter{budget, += 10}           (relative)

Thresholds fall out as 30, then +40, then +50 cumulative -- exactly the wiki's "increased by 10 for
each time Mode Shift triggered", with no counter that has to be initialised by hand and no
expression in the intent layer.
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

document = json.load(io.open(SRC, encoding="utf-8"))
statuses = {row["Id"]: row for row in document["Statuses"]}
actions = {row["Id"]: row for row in document["EnemyActions"]}
monsters = {row["Id"]: row for row in document["Monsters"]}

SOURCE = {"kind": "sel.source",
          "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def program(children):
    root = children[0] if len(children) == 1 else {
        "kind": "node.sequence", "value": {"Children": children}}
    return {"Id": {"Value": "(unnamed)"}, "Root": root, "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def set_counter(name, amount, relative):
    return {
        "kind": "node.setCombatantCounter",
        "value": {
            "TargetSelector": SOURCE,
            "CounterId": {"value": name},
            "Amount": amount,
            "Relative": relative,
            "ResultKey": None,
        },
    }


# ---------------------------------------------------------------- 1. the trigger: budget -= lost HP
statuses["standard.mode_shift"]["Triggers"] = [{
    "Event": "DamageTaken",
    "Program": program([
        # **relative** and **negative**: the budget shrinks by exactly the HP that was lost
        # (§195.1 put `eventAmount` on the event; a fully blocked hit loses 0 and shifts nothing).
        set_counter("mode_shift_budget",
                    {"kind": "subtract",
                     "value": {"Left": {"kind": "const", "value": {"Value": 0}},
                               "Right": {"kind": "eventAmount", "value": {}}}},
                    True),
    ]),
}]
statuses["standard.mode_shift"]["DescriptionKey"] = (
    "After losing 30 HP, gains 20 Block and switches to Defensive Mode (+10 HP each time).")

# ---------------------------------------------------------------- 2. Defensive Mode: +10 budget
defensive_children = {
    "block": {"kind": "node.gainBlock",
              "value": {"TargetSelector": SOURCE,
                        "Amount": {"kind": "const", "value": {"Value": 20}},
                        "ResultKey": None}},
}


def defensive(sharp_hide):
    return program([
        defensive_children["block"],
        {"kind": "node.applyStatus",
         "value": {"TargetSelector": SOURCE,
                   "StatusDefinitionId": {"value": "standard.sharp_hide"},
                   "Stacks": {"kind": "const", "value": {"Value": sharp_hide}},
                   "DurationTurns": 0, "Charges": 0, "ResultKey": None}},
        # the wiki's "increased by 10 for each time Mode Shift triggered"
        set_counter("mode_shift_budget", {"kind": "const", "value": {"Value": 10}}, True),
        set_counter("guard_mode", {"kind": "const", "value": {"Value": 1}}, False),
        set_counter("guard_step", {"kind": "const", "value": {"Value": 0}}, False),
    ])


actions["the_guardian.defensive_mode"]["Program"] = defensive(3)
actions["the_guardian.defensive_mode"]["ProgramAsc"] = [
    {"AscensionMin": 19, "Program": defensive(4)}]

# ---------------------------------------------------------------- 3. the rule: a constant
guardian = monsters["the_guardian"]
threshold = {
    "Condition": {"kind": "intent.selfHasCounter",
                  "value": {"Counter": {"value": "mode_shift_budget"},
                            "Op": "LessOrEqual",
                            "Value": 0}},
    "Action": {"value": "the_guardian.defensive_mode"},
    "Priority": 80,
}
others = [rule for rule in guardian["IntentRules"]
          if rule["Action"]["value"] != "the_guardian.defensive_mode"]
assert len(others) == 3, len(others)
guardian["IntentRules"] = [threshold] + others
guardian["StartingStatuses"] = [{"StatusDefinitionId": {"value": "standard.mode_shift"},
                                 "Stacks": 1}]
guardian["AiNote"] = (
    "§195.1：wiki 数值（HP 240/250；Fierce Bash 32→A4 36；Whirlwind 5×4；Roll Attack 9→A4 10；"
    "Twin Slam 8×2；Defensive Mode 20 Block + 3 Sharp Hide，A19 4）。"
    "Mode Shift 是**真·累计受伤**：开局 `Counters` 把 `mode_shift_budget` 种成 30（A9 35、A19 40），"
    "`standard.mode_shift` 的 DamageTaken 触发器把它减去**实际掉血**（`eventAmount`），意图规则在"
    "预算 ≤ 0 时切防御态，防御态把预算 +10（wiki 的『每次触发 +10』）。"
    "Sharp Hide 是精确的（`CardPlayed` + `card.hasTag.attack`）。"
    "⚠️ 偏差：被完全挡住的攻击不算伤害（StS 同理）。")

# ---------------------------------------------------------------- 4. the record + its copy
def counters_list():
    return [
        {"Key": "mode_shift_budget", "Value": 30},
        {"Key": "mode_shift_budget", "Value": 35, "AscensionMin": 9},
        {"Key": "mode_shift_budget", "Value": 40, "AscensionMin": 19},
    ]


guardian["Counters"] = counters_list()

# Every record gets the key (opcode shapes are derived per key *set* -- §193's lesson).
for record in monsters.values():
    record.setdefault("Counters", [])

for encounter in document["Encounters"]:
    for record in encounter["Enemies"]:
        record.setdefault("Counters", [])
        if record["Id"] == "the_guardian":
            record["Counters"] = counters_list()
            record["StartingStatuses"] = list(guardian["StartingStatuses"])
            record["IntentRules"] = list(guardian["IntentRules"])

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print("guardian: budget 30/35/40 at spawn, -= eventAmount, rule <= 0, +10 per shift")
