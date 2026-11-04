"""§195.6: minions are **summoned**, not pre-placed (`ENCT.Enemies[].Spawn: false`).

What was wrong (and documented as a deviation in §194/§195.4): a summoned minion must appear in an
encounter's roster, because that list is the only place `intent::locate_enemy` can find its move set
(§138). "In the roster" also meant "on the field at fight start", so the wiki's `Spawn Orbs` /
`Spawn` / `Spawn Dagger` moves had to be dropped and the minions were simply pre-placed:

    Bronze Automaton + 2 Orbs      -- all three on the field from turn 1
    The Collector  + 2 Torch Heads -- ditto
    Reptomancer    + 2 Daggers     -- ditto (wiki: 2 daggers **at fight start**, so this one was right)

`Spawn: false` splits the two meanings: the record stays in the roster (moves resolvable) and is
**not** placed. The summon actions create the minions, which is what the wiki says.

Reptomancer keeps its two Daggers pre-placed (`Spawn: true`): the wiki explicitly starts that fight
with two daggers, and `Spawn Dagger` then adds a third and beyond (the kernel's only bound is the
6-combatant container).
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

document = json.load(io.open(SRC, encoding="utf-8"))
actions = {row["Id"]: row for row in document["EnemyActions"]}
monsters = {row["Id"]: row for row in document["Monsters"]}

SOURCE = {"kind": "sel.source",
          "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def program(children):
    root = children[0] if len(children) == 1 else {
        "kind": "node.sequence", "value": {"Children": children}}
    return {"Id": {"Value": "(unnamed)"}, "Root": root, "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def summon(definition, health):
    return {
        "kind": "node.createCombatant",
        "value": {
            "DefinitionId": definition,
            "TeamId": "enemy",
            "Health": {"kind": "const", "value": {"Value": health}},
        },
    }


def set_counter(name, amount, relative=False):
    return {
        "kind": "node.setCombatantCounter",
        "value": {
            "TargetSelector": SOURCE,
            "CounterId": {"value": name},
            "Amount": amount if isinstance(amount, dict) else {"kind": "const", "value": {"Value": amount}},
            "Relative": relative,
            "ResultKey": None,
        },
    }


def counter(name):
    return {"kind": "combatantCounter", "value": {"Selector": SOURCE, "CounterId": name}}


def with_history(record, code):
    """Same convention as §195.5 (every selectable action records itself)."""
    for prog in [record["Program"]] + [v["Program"] for v in record.get("ProgramAsc") or []]:
        root = prog["Root"]
        nodes = [set_counter("prev_move", counter("last_move")), set_counter("last_move", code)]
        if root.get("kind") == "node.sequence":
            children = root["value"]["Children"]
            while children and children[-1].get("kind") == "node.setCombatantCounter" \
                    and children[-1]["value"]["CounterId"]["value"] in ("last_move", "prev_move"):
                children.pop()
            children.extend(nodes)
        else:
            prog["Root"] = {"kind": "node.sequence", "value": {"Children": [root] + nodes}}
    return record


# ---------------------------------------------------------------- 1. the summon moves
# `Spawn Orbs` summons **two** orbs, so it cannot be one `createCombatant`: the two calls must produce
# different combatant ids, and `node.createCombatant` mints `<definition>#<n>`. Two nodes do that.
if "bronze_automaton.spawn_orbs" not in actions:
    record = with_history({
        "Id": "bronze_automaton.spawn_orbs",
        "PackageId": "sts",
        "NameKey": "Spawn Orbs",
        "DescriptionKey": "Spawn Orbs - summons 2 Bronze Orbs",
        "Intent": {"Kind": "Special", "Label": "Spawn Orbs - summons 2 Bronze Orbs"},
        "Program": program([summon("bronze_orb", 52), summon("bronze_orb", 52)]),
    }, 8)
    document["EnemyActions"].append(record)
    actions[record["Id"]] = record

if "the_collector.spawn" not in actions:
    record = with_history({
        "Id": "the_collector.spawn",
        "PackageId": "sts",
        "NameKey": "Spawn",
        "DescriptionKey": "Spawn - summons 2 Torch Heads",
        "Intent": {"Kind": "Special", "Label": "Spawn - summons 2 Torch Heads"},
        "Program": program([summon("torch_head", 38), summon("torch_head", 38)]),
    }, 4)
    document["EnemyActions"].append(record)
    actions[record["Id"]] = record

# ---------------------------------------------------------------- 2. the bosses use them
automaton = monsters["bronze_automaton"]
automaton["Actions"] = [{"value": "bronze_automaton.spawn_orbs"}] + [
    entry for entry in automaton["Actions"] if entry["value"] != "bronze_automaton.spawn_orbs"]
automaton["IntentRules"] = [{
    # turn 1 is Spawn Orbs; after that the wiki's 6-cycle (whose index 0 *is* Spawn Orbs) would come
    # back on turn 7 -- so the cycle is shifted by one by putting the spawn last in `Actions`.
    "Condition": {"kind": "intent.round", "value": {"Op": "Equal", "Round": 1}},
    "Action": {"value": "bronze_automaton.spawn_orbs"},
    "Priority": 70,
}] + [
    rule for rule in automaton["IntentRules"]
    if rule["Action"]["value"] != "bronze_automaton.spawn_orbs"
]
# ... and the cycle itself keeps the old six moves (spawn is rule-only), so put it back at the end.
automaton["Actions"] = [{"value": value} for value in (
    "bronze_automaton.flail", "bronze_automaton.boost", "bronze_automaton.flail",
    "bronze_automaton.boost", "bronze_automaton.hyper_beam", "bronze_automaton.stunned",
)]
automaton["AiNote"] = (
    "§194/§195.5/§195.6：wiki 数值（HP 300/320；Artifact 3；Flail 7×2→A4 8×2；Boost 3 Str + 9 Block，"
    "A4 Str 4、A9 Block 12；HYPER BEAM 45→A4 50；Stunned；A19 用 Boost 顶替 Stunned）。"
    "第 1 回合 **Spawn Orbs 真召唤两只 Bronze Orb**（`Spawn: false` 让它们只作为招式表存在），"
    "之后走 wiki 的 6 招循环。⚠️ 偏差：Orb 的 `Stasis` 未实现（偷牌需要卡选择器，而它已由 §195.4 的"
    "`selectCards` 提供 —— 见 bronze_orb 的备注）。")

collector = monsters["the_collector"]
def names(rule):
    """Every action id a rule can produce (single `Action` or weighted `Choice`)."""
    found = []
    if rule.get("Action"):
        found.append(rule["Action"]["value"])
    for option in rule.get("Choice") or []:
        found.append(option["Action"]["value"])
    return found


collector["IntentRules"] = [
    {"Condition": {"kind": "intent.round", "value": {"Op": "Equal", "Round": 1}},
     "Action": {"value": "the_collector.spawn"}, "Priority": 65},
] + [rule for rule in collector["IntentRules"] if "the_collector.spawn" not in names(rule)]
collector["AiNote"] = collector["AiNote"].replace(
    "③ 两只 Torch Head 开局在场上，Spawn 被去掉（§194）。",
    "③ 第 1 回合 **Spawn 真召唤两只 Torch Head**（§195.6：`Spawn: false`）。")

# ---------------------------------------------------------------- 3. the roster flags
SPAWN_FALSE = {"bronze_orb", "torch_head"}
for monster in monsters.values():
    monster["Spawn"] = monster["Id"] not in SPAWN_FALSE
for encounter in document["Encounters"]:
    for record in encounter["Enemies"]:
        record["Spawn"] = record["Id"] not in SPAWN_FALSE
        # ⚠️ The encounter carries an **inline copy** of the roster record and the kernel reads that
        # copy (third time this bit in this project: §194, §195.4). Re-sync *everything* the roster
        # owns, not just the new flag.
        source = monsters.get(record["Id"])
        if source is not None:
            record["IntentRules"] = json.loads(json.dumps(source["IntentRules"]))
            record["Actions"] = json.loads(json.dumps(source["Actions"]))
            record["StartingStatuses"] = json.loads(json.dumps(source["StartingStatuses"]))

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print("spawn:false on", sorted(SPAWN_FALSE), "/ spawn moves added for automaton + collector")
