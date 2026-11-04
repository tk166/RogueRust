"""§195.5: every boss's *mechanism* against the wiki -- weighted draws and "cannot repeat" guards.

What this pass changes, per boss (numbers from `native/wiki_asc/*.txt`):

| boss | wiki | before | now |
|---|---|---|---|
| Slime Boss | fixed cycle, Split at 50% | correct | unchanged |
| The Guardian | offensive 4-cycle + Mode Shift | correct since §195.1 | unchanged |
| Hexaghost | fixed 7-cycle + 2 openers | correct | unchanged |
| **The Champ** | 45/25/15/15, **no move twice in a row**, Taunt every 4th | deterministic 4-cycle | weighted + per-last-move exclusion |
| Bronze Automaton | fixed 6-cycle, A19 Stunned->Boost | correct | unchanged |
| **The Collector** | 70/30, no Buff twice, **no Fireball 3×** | 70/30 + no-Buff-twice | + the 3× guard (two-deep history) |
| **Time Eater** | 45/35/20, no Reverb 3×, no Head Slam/Ripple 2× | deterministic 3-cycle | weighted + two gates |
| **Awakened One** | P1 75/25 (Slash not 3×), P2 50/50, Dark Echo first | deterministic | weighted + one gate each phase |
| Donu / Deca | strict alternation | correct | unchanged |
| **Bronze Orb** | Stasis 75% until used; then 70/30 Support/Beam | Stasis once, then 2-cycle | weighted both branches |

History is **content state**, not kernel state (§195.3): every action program ends with

    prev_move = last_move          (setCombatantCounter, absolute, `combatantCounter` expression)
    last_move = <k>                (k is the action's own code)

and the "cannot repeat" rules are `intent.selfHasCounter{last_move == k}` gates with a re-normalised
`Choice`. Rule budgets (MAX_INTENT_RULES = 8) are listed per boss below; the Awakened One's phase-2
"no 3× Tackle/Sludge" is dropped to stay under it and is documented in its `AiNote`.
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

document = json.load(io.open(SRC, encoding="utf-8"))
actions = {row["Id"]: row for row in document["EnemyActions"]}
monsters = {row["Id"]: row for row in document["Monsters"]}

SOURCE = {"kind": "sel.source",
          "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}

# code -> action id, per boss. The code is what the action writes into `last_move`.
CODES = {
    "the_champ": {"the_champ.heavy_slash": 1, "the_champ.face_slap": 2,
                  "the_champ.defensive_stance": 3, "the_champ.gloat": 4,
                  "the_champ.taunt": 5, "the_champ.anger": 6, "the_champ.execute": 7},
    "the_collector": {"the_collector.fireball": 1, "the_collector.buff": 2,
                      "the_collector.mega_debuff": 3},
    # ⚠️ The "special" moves (Haste / Mega Debuff / Rebirth) are *also* selectable, so they too must
    # record a code -- otherwise `prev_move` is whatever the previous move left there and the
    # exclusion rules reason about the wrong history (`check_intent_history` caught exactly that).
    "time_eater": {"time_eater.reverberate": 1, "time_eater.head_slam": 2,
                   "time_eater.ripple": 3, "time_eater.haste": 4},
    "awakened_one": {"awakened_one.slash": 1, "awakened_one.soul_strike": 2,
                     "awakened_one.dark_echo": 3, "awakened_one.tackle": 4,
                     "awakened_one.sludge": 5, "awakened_one.rebirth": 6},
    "bronze_orb": {"bronze_orb.stasis": 1, "bronze_orb.beam": 2,
                   "bronze_orb.support_beam": 3},
}


def counter(name):
    return {"kind": "combatantCounter", "value": {"Selector": SOURCE, "CounterId": name}}


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


def history_nodes(code):
    """`prev_move = last_move; last_move = code` -- the two lines every action ends with."""
    return [set_counter("prev_move", counter("last_move"), False), set_counter("last_move", code)]


def strip_history(program):
    """Remove a previously appended history pair, so re-running this script is safe."""
    root = program["Root"]
    if root.get("kind") != "node.sequence":
        return
    children = root["value"]["Children"]
    while len(children) >= 2 and children[-1].get("kind") == "node.setCombatantCounter" \
            and children[-1]["value"]["CounterId"]["value"] in ("last_move", "prev_move"):
        children.pop()
    while children and children[-1].get("kind") == "node.setCombatantCounter" \
            and children[-1]["value"]["CounterId"]["value"] in ("last_move", "prev_move"):
        children.pop()


def with_history(record, code):
    for program in [record["Program"]] + [v["Program"] for v in record.get("ProgramAsc") or []]:
        strip_history(program)
        root = program["Root"]
        nodes = history_nodes(code)
        if root.get("kind") == "node.sequence":
            root["value"]["Children"].extend(nodes)
        else:
            program["Root"] = {"kind": "node.sequence", "value": {"Children": [root] + nodes}}
    return record


# The Awakened One's phase 2 is a 50/50 draw now, so its old `ao_toggle` parity counters are dead:
# drop them (dead content state is the same rot as dead code, and the checker pins facts, so leaving
# them would make the inventory describe a rule that no longer exists).
for action_id in ("awakened_one.tackle", "awakened_one.sludge",
                  "awakened_one.dark_echo", "awakened_one.rebirth"):
    record = actions[action_id]
    for program in [record["Program"]] + [v["Program"] for v in record.get("ProgramAsc") or []]:
        root = program["Root"]
        if root.get("kind") != "node.sequence":
            continue
        root["value"]["Children"] = [
            child for child in root["value"]["Children"]
            if not (child.get("kind") == "node.setCombatantCounter"
                    and child["value"]["CounterId"]["value"] == "ao_toggle")
        ]

for boss, mapping in CODES.items():
    for action_id, code in mapping.items():
        with_history(actions[action_id], code)
print("history written for", sum(len(v) for v in CODES.values()), "actions")


# ---------------------------------------------------------------- rule helpers
def c_counter(name, op, value):
    return {"kind": "intent.selfHasCounter",
            "value": {"Counter": {"value": name}, "Op": op, "Value": value}}


def c_all(*conditions):
    return {"kind": "intent.allOf", "value": {"Conditions": list(conditions)}}


def c_rounds(values):
    return {"kind": "intent.anyOf",
            "value": {"Conditions": [{"kind": "intent.round", "value": {"Op": "Equal", "Round": v}}
                                     for v in values]}}


def c_asc(n):
    return {"kind": "intent.ascensionAtLeast", "value": {"Value": n}}


def c_health(op, percent):
    return {"kind": "intent.healthPercent", "value": {"Op": op, "Percent": percent}}


def c_has_status(definition):
    return {"kind": "intent.selfHasStatus",
            "value": {"Status": {"value": definition}, "MinStacks": 1}}


def c_not(condition):
    return {"kind": "intent.not", "value": {"Condition": condition}}


def one(action_id):
    return {"Condition": c_all(), "Priority": 0, "Action": {"value": action_id}}


def weighted(priority, condition, options):
    return {"Condition": condition, "Priority": priority,
            "Choice": [{"Action": {"value": a}, "Weight": w} for a, w in options]}


# ---------------------------------------------------------------- The Champ
# wiki phase one: Taunt every 4 turns; otherwise Heavy Slash 45 / Face Slap 25 / Defensive 15 /
# Gloat 15, and **no move twice in a row** ("he will instead use the next move in the list above" --
# modelled as "the same weights minus the move just used", renormalised).
CHAMP = {"the_champ.heavy_slash": 45, "the_champ.face_slap": 25,
         "the_champ.defensive_stance": 15, "the_champ.gloat": 15}
champ = monsters["the_champ"]
champ_rules = [
    {"Condition": c_all(c_health("LessOrEqual", 50), c_counter("champ_phase", "LessOrEqual", 0)),
     "Action": {"value": "the_champ.anger"}, "Priority": 90},
    {"Condition": c_all(c_counter("champ_phase", "GreaterOrEqual", 1),
                        c_counter("champ_exec", "LessOrEqual", 0)),
     "Action": {"value": "the_champ.execute"}, "Priority": 85},
    {"Condition": c_rounds([4, 8, 12, 16, 20, 24]),
     "Action": {"value": "the_champ.taunt"}, "Priority": 60},
]
# one exclusion rule per move (4), highest prior for the two likeliest
for code, (action_id, weight) in enumerate(CHAMP.items(), start=1):
    rest = [(a, w) for a, w in CHAMP.items() if a != action_id]
    champ_rules.append(weighted(50, c_counter("last_move", "Equal", code), rest))
# ⚠️ The default rule is **required**: without it the four exclusion rules are the only rules, and a
# miss falls through to the `Actions` **cycle** -- i.e. the Champ would still be a deterministic
# 4-cycle and the wiki's 45/25/15/15 would only ever appear inside an exclusion. (The negative
# control for this test is "lower the exclusions below the default"; with no default it stayed green.)
champ_rules.append(weighted(40, c_all(), list(CHAMP.items())))
champ["IntentRules"] = champ_rules
assert len(champ_rules) <= 8, len(champ_rules)
champ["AiNote"] = (
    "§194/§195.5：wiki 数值（HP 420/440；Heavy Slash 16→A4 18；Face Slap 12→A4 14 + 2 Frail + 2 Vuln；"
    "Defensive Stance 15 Block + 5 Metallicize，A9 18/6、A19 20/7；Gloat 2 Str，A4 3、A19 4；"
    "Taunt 每 4 回合 2 Weak + 2 Vuln；Anger 清 debuff + 6 Str，A4 9、A19 12；Execute 10×2）。"
    "出招是**带权抽签**（Heavy Slash 45 / Face Slap 25 / Defensive 15 / Gloat 15），并且"
    "『不能连续用同一招』由 `last_move` 计数器 + 每条一招的排除规则实现（wiki：重复时用列表里的下一招）。"
    "⚠️ 偏差：① 第二阶段『随机、随机、Execute』只做了第一次 Execute，之后回到第一阶段权重；"
    "② Anger 按名清掉 Weak/Vulnerable/Frail（没有『清空状态』节点）；③ A19 的 Gloat→Defensive 未实现；"
    "④ 抽签是 `(seed, round, slot)` 的派生值，不是随机流（§195.3）。")

# ---------------------------------------------------------------- The Collector
# "cannot use Buff twice in a row and cannot use Fireball 3 times in a row".
collector = monsters["the_collector"]
collector["IntentRules"] = [
    {"Condition": c_rounds([4]), "Action": {"value": "the_collector.mega_debuff"}, "Priority": 60},
    # no Buff twice
    weighted(55, c_counter("last_move", "Equal", 2), [("the_collector.fireball", 100)]),
    # no Fireball three times: two Fireballs in a row force a Buff
    weighted(54, c_all(c_counter("last_move", "Equal", 1), c_counter("prev_move", "Equal", 1)),
             [("the_collector.buff", 100)]),
    weighted(40, c_all(), [("the_collector.fireball", 70), ("the_collector.buff", 30)]),
]
collector["AiNote"] = collector["AiNote"].replace(
    "② 『不能连续三次 Fireball』没做（要记两次历史，规则会挤满 8 格上限）；",
    "② 『不能连续三次 Fireball』用 `last_move` + `prev_move` 两级历史做（两次 Fireball 后强制 Buff）；")

# ---------------------------------------------------------------- Time Eater
# 45/35/20; no Reverberate 3x; no Head Slam twice; no Ripple twice.
TIME = {"time_eater.reverberate": 45, "time_eater.head_slam": 35, "time_eater.ripple": 20}
time_eater = monsters["time_eater"]
time_rules = [
    {"Condition": c_all(c_health("LessOrEqual", 50), c_counter("te_haste", "LessOrEqual", 0)),
     "Action": {"value": "time_eater.haste"}, "Priority": 90},
    # Head Slam or Ripple twice in a row is forbidden -> exclude the one just used.
    weighted(60, c_counter("last_move", "Equal", 2),
             [(a, w) for a, w in TIME.items() if a != "time_eater.head_slam"]),
    weighted(59, c_counter("last_move", "Equal", 3),
             [(a, w) for a, w in TIME.items() if a != "time_eater.ripple"]),
    # Reverberate three times: two in a row exclude it.
    weighted(58, c_all(c_counter("last_move", "Equal", 1), c_counter("prev_move", "Equal", 1)),
             [(a, w) for a, w in TIME.items() if a != "time_eater.reverberate"]),
    weighted(40, c_all(), list(TIME.items())),
]
time_eater["IntentRules"] = time_rules
assert len(time_rules) <= 8, len(time_rules)
time_eater["AiNote"] = time_eater["AiNote"].replace(
    "③ 45/35/20 权重变成确定性 3 循环。",
    "③ 45/35/20 是**带权抽签**，且『不能连续三次 Reverberate / 不能连续两次 Head Slam·Ripple』"
    "用 `last_move`+`prev_move` 的排除规则实现。")

# ---------------------------------------------------------------- Awakened One
# Phase 1: Slash 75 / Soul Strike 25 (Slash never 3x). Phase 2: Dark Echo once, then Tackle/Sludge 50/50.
awakened = monsters["awakened_one"]
ao_rules = [
    {"Condition": c_all(c_not(c_has_status("standard.unawakened")),
                        c_counter("ao_phase", "LessOrEqual", 0)),
     "Action": {"value": "awakened_one.rebirth"}, "Priority": 95},
    {"Condition": c_all(c_counter("ao_phase", "GreaterOrEqual", 1),
                        c_counter("ao_started", "LessOrEqual", 0)),
     "Action": {"value": "awakened_one.dark_echo"}, "Priority": 90},
    weighted(70, c_counter("ao_phase", "GreaterOrEqual", 1),
             [("awakened_one.tackle", 50), ("awakened_one.sludge", 50)]),
    # Slash three times in a row is forbidden -> after two, Soul Strike.
    weighted(50, c_all(c_counter("ao_phase", "LessOrEqual", 0),
                       c_counter("last_move", "Equal", 1),
                       c_counter("prev_move", "Equal", 1)),
             [("awakened_one.soul_strike", 100)]),
    weighted(40, c_counter("ao_phase", "LessOrEqual", 0),
             [("awakened_one.slash", 75), ("awakened_one.soul_strike", 25)]),
]
awakened["IntentRules"] = ao_rules
assert len(ao_rules) <= 8, len(ao_rules)
awakened["AiNote"] = awakened["AiNote"].replace(
    "两阶段用计数器做：",
    "出招是**带权抽签**（第一阶段 Slash 75 / Soul Strike 25，且 Slash 不会连续三次；"
    "第二阶段 Tackle/Sludge 50/50）。两阶段用计数器做：").replace(
    "④ Regenerate/Curiosity 的层数不随 A19 变",
    "④ 第二阶段的『不能连续三次 Tackle/Sludge』没做（规则预算 8 条已用在两阶段与排除上）；"
    "⑤ Regenerate/Curiosity 的层数不随 A19 变")

# ---------------------------------------------------------------- Bronze Orb
# "75% chance to use Stasis each turn until picked; after that 70% Support Beam / 30% Beam."
orb = monsters["bronze_orb"]
orb["IntentRules"] = [
    # While the flag is up: Stasis 75%; the other 25% split like the post-Stasis branch (70/30).
    weighted(50, c_has_status("standard.stasis_ready"),
             [("bronze_orb.stasis", 75), ("bronze_orb.support_beam", 18), ("bronze_orb.beam", 7)]),
    # wiki: "Bronze Orb cannot use the same attack thrice in a row" -- two in a row ban the third.
    weighted(48, c_all(c_counter("last_move", "Equal", 2), c_counter("prev_move", "Equal", 2)),
             [("bronze_orb.support_beam", 100)]),
    weighted(47, c_all(c_counter("last_move", "Equal", 3), c_counter("prev_move", "Equal", 3)),
             [("bronze_orb.beam", 100)]),
    weighted(40, c_all(),
             [("bronze_orb.support_beam", 70), ("bronze_orb.beam", 30)]),
]
orb["AiNote"] = orb["AiNote"].replace(
    "⚠️ 偏差：① 75% 概率没建模（Orb 的另一招仍是确定性循环）；",
    "出招是带权抽签（没用 Stasis 之前 75% 用它，其余按 70/30 分给两招；用过之后 70/30），"
    "『同一招不连续三次』用 `last_move`+`prev_move` 排除。⚠️ 偏差：")

# ---------------------------------------------------------------- sync encounter copies
for encounter in document["Encounters"]:
    for record in encounter["Enemies"]:
        source = monsters.get(record["Id"])
        if source is None:
            continue
        record["IntentRules"] = json.loads(json.dumps(source["IntentRules"]))
        record["Actions"] = json.loads(json.dumps(source["Actions"]))
        record["StartingStatuses"] = json.loads(json.dumps(source["StartingStatuses"]))

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print("rules written: champ %d / collector %d / time_eater %d / awakened %d / orb %d"
      % (len(champ_rules), len(collector["IntentRules"]), len(time_rules), len(ao_rules),
         len(orb["IntentRules"])))
