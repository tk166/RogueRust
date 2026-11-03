"""§195.3 content: The Collector gets the wiki's weighted move choice, with "cannot Buff twice in a row".

Wiki (`native/wiki_asc/the_collector.txt`):

    If both Torch Heads are alive:  Fireball 70%, Buff 30%
    (If 0-1 alive: Spawn 25%, Fireball 45%, Buff 30%)
    She cannot use Buff twice in a row and cannot use Fireball 3 times in a row.

Our content deploys the two Torch Heads with the boss (§194), so the first row is the one that
applies; `Spawn` does not exist here at all.

Shape (both halves are needed, and only both together say what the wiki says):

    rule P50  allOf[ counter(last_move) == 2 ]            -> Choice[ Fireball 100 ]
                "she cannot use Buff twice in a row" -- the *next* move after a Buff is Fireball
    rule P40  (no condition)                            -> Choice[ Fireball 70, Buff 30 ]
    rule P60  round == 4                                -> Mega Debuff   (already there)

    each action's program ends with setCombatantCounter{last_move, 1|2}

`last_move` is a **content** counter, not kernel state: the draw is a pure function of
`(seed, round, slot)` (§195.3), so "what came before" cannot be recovered by the kernel without a
snapshot field -- and the reference has none. Content already records phase flags this way (§194).
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

document = json.load(io.open(SRC, encoding="utf-8"))
actions = {row["Id"]: row for row in document["EnemyActions"]}
monsters = {row["Id"]: row for row in document["Monsters"]}

SOURCE = {"kind": "sel.source",
          "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def set_counter(name, value):
    return {
        "kind": "node.setCombatantCounter",
        "value": {
            "TargetSelector": SOURCE,
            "CounterId": {"value": name},
            "Amount": {"kind": "const", "value": {"Value": value}},
            "Relative": False,
            "ResultKey": None,
        },
    }


def with_marker(record, marker):
    """Append `last_move = marker` to the action's program (and to every ascension variant)."""
    def bump(program):
        root = program["Root"]
        if root.get("kind") == "node.sequence":
            children = root["value"]["Children"]
            children.append(set_counter("last_move", marker))
        else:
            program["Root"] = {"kind": "node.sequence",
                               "value": {"Children": [root, set_counter("last_move", marker)]}}

    for program in [record["Program"]] + [v["Program"] for v in record.get("ProgramAsc") or []]:
        bump(program)
    return record


with_marker(actions["the_collector.fireball"], 1)
with_marker(actions["the_collector.buff"], 2)

choice_default = {
    "Condition": {"kind": "intent.allOf", "value": {"Conditions": []}},
    "Priority": 40,
    "Choice": [
        {"Action": {"value": "the_collector.fireball"}, "Weight": 70},
        {"Action": {"value": "the_collector.buff"}, "Weight": 30},
    ],
}
# "cannot use Buff twice in a row": after a Buff (2), the only move is Fireball.
choice_after_buff = {
    "Condition": {"kind": "intent.selfHasCounter",
                  "value": {"Counter": {"value": "last_move"},
                            "Op": "Equal", "Value": 2}},
    "Priority": 50,
    "Choice": [{"Action": {"value": "the_collector.fireball"}, "Weight": 100}],
}
# `round == 4` -> Mega Debuff stays the highest priority rule.
mega = next(rule for rule in monsters["the_collector"]["IntentRules"]
            if rule["Action"]["value"] == "the_collector.mega_debuff")
mega["Priority"] = 60

collector = monsters["the_collector"]
# The `Actions` cycle is what `select_action` falls back to when nothing matches -- with the two
# weighted rules in place it is unreachable, but leaving a cycle is the safest fallback (a rule whose
# condition cannot be evaluated is a loud error, not a fallback).
collector["IntentRules"] = [mega, choice_after_buff, choice_default]
collector["AiNote"] = (
    "§194/§195.3：wiki 数值（HP 282/300；Fireball 18→A4 21；Buff 全体 +3 Str + 15 Block，"
    "A4 Str 4、A9 Block 18、A19 5/23；Mega Debuff 3/3/3，A19 5/5/5，第 4 回合必出）。"
    "出招现在是**带权抽签**（两只 Torch Head 在场 ⇒ wiki 的 Fireball 70% / Buff 30%），"
    "『不能连续两次 Buff』由 `last_move` 计数器 + 一条 P50 规则实现（内容自己记历史，不需要内核状态）。"
    "⚠️ 偏差：① 抽签是 `(seed, round, slot)` 的**派生值**，不是随机流（§195.3：意图每次观察都要重算，"
    "所以必须是纯函数）；② 『不能连续三次 Fireball』没做（要记两次历史，规则会挤满 8 格上限）；"
    "③ 两只 Torch Head 开局在场上，Spawn 被去掉（§194）。")

for encounter in document["Encounters"]:
    for record in encounter["Enemies"]:
        if record["Id"] == "the_collector":
            record["IntentRules"] = json.loads(json.dumps(collector["IntentRules"]))

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print("collector: weighted 70/30 + last_move guard")
