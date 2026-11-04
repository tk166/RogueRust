"""§213: rewrite the Chosen per the wiki (`native/wiki_asc/chosen.txt`).

HP 48 -> 95 (A7: 98), and the moves were two of five: Poke (5x2 / A2 6x2), Debilitate (10 + 2
Vulnerable / A2 12), plus the missing Hex (the Hex debuff: non-Attack cards shuffle a Dazed into the
draw pile), Drain (3 Weak + 3 Strength to itself) and Zap (18 / A2 21). The AI is the wiki's sentence:
Poke then Hex (A17 swaps the opener), then (Debilitate 50 / Drain 50) and (Poke 60 / Zap 40) forever.
"""
import io
import json
import copy

SRC = 'tools/contentc/packages/sts/sts.roguedeck.json'
SOURCE = {"kind": "sel.source", "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
EVENT = {"kind": "sel.eventTarget", "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}

d = json.load(io.open(SRC, encoding='utf-8'))


def program(children):
    root = children[0] if len(children) == 1 else {
        "kind": "node.sequence", "value": {"Children": children}}
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def history(k):
    """`prev_move = last_move; last_move = k` -- the §195.5 discipline every AI rule reads."""
    return [
        {"kind": "node.setCombatantCounter", "value": {
            "TargetSelector": SOURCE, "CounterId": {"value": "prev_move"},
            "Amount": {"kind": "combatantCounter",
                       "value": {"Selector": SOURCE, "CounterId": "last_move"}},
            "Relative": False}},
        {"kind": "node.setCombatantCounter", "value": {
            "TargetSelector": SOURCE, "CounterId": {"value": "last_move"},
            "Amount": {"kind": "const", "value": {"Value": k}}, "Relative": False}},
    ]


def dmg(n):
    return {"kind": "node.dealDamage", "value": {
        "TargetSelector": EVENT, "Amount": {"kind": "const", "value": {"Value": n}},
        "ResultKey": None, "IgnoresBlock": False, "Element": None}}


def status(target, name, stacks):
    return {"kind": "node.applyStatus", "value": {
        "TargetSelector": target, "StatusDefinitionId": {"value": name},
        "Stacks": {"kind": "const", "value": {"Value": stacks}},
        "DurationTurns": 0, "Charges": 0, "ResultKey": None}}


# ---- `standard.hex` -----------------------------------------------------------------------------
hex_status = {
    "Id": "standard.hex", "PackageId": "sts", "NameKey": "Hex",
    "DescriptionKey": "Whenever you play a non-Attack card, shuffle a Dazed into your draw pile.",
    "Polarity": "Debuff", "UsesStacks": True, "UsesDuration": False, "UsesCharges": False,
    "StackingBehavior": "MergeWithExistingInstance", "Tags": ["debuff"],
    "PassiveModifiers": None,
    "Triggers": [{
        "Event": "CardPlayed",
        "Program": {
            "Id": {"Value": "(unnamed)"},
            "Root": {"kind": "node.conditional", "value": {
                "Condition": {"kind": "not", "value": {"Operand": {
                    "kind": "event.bool", "value": {"FieldKey": "card.hasTag.attack"}}}},
                "Then": {"kind": "node.createCardInstance", "value": {
                    "CardDefinitionId": {"value": "dazed"},
                    "Count": {"kind": "combatantStatusStacks", "value": {
                        "Selector": SOURCE, "StatusId": "standard.hex"}},
                    "TargetSelector": EVENT, "ToZone": "DrawPile", "ResultKey": None}},
                "Else": None}},
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024,
        },
    }],
}
if not any(s['Id'] == 'standard.hex' for s in d['Statuses']):
    d['Statuses'].append(hex_status)

acts = {a['Id']: a for a in d['EnemyActions']}


def poke(hit):
    return program([dmg(hit), dmg(hit), *history(1)])


acts['chosen.poke']['Program'] = poke(5)
acts['chosen.poke']['ProgramAsc'] = [{"AscensionMin": 2, "Program": poke(6)}]
acts['chosen.poke']['DescriptionKey'] = "Poke - 5x2 damage"
acts['chosen.poke']['Intent'] = {"Kind": "Attack", "Label": "Poke - 5x2"}


def debilitate(hit):
    return program([dmg(hit), status(EVENT, "standard.vulnerable", 2), *history(2)])


acts['chosen.debilitate']['Program'] = debilitate(10)
acts['chosen.debilitate']['ProgramAsc'] = [{"AscensionMin": 2, "Program": debilitate(12)}]

if 'chosen.hex' not in acts:
    d['EnemyActions'].append({
        "Id": "chosen.hex", "PackageId": "sts", "NameKey": "Hex",
        "DescriptionKey": "Hex - applies Hex",
        "Intent": {"Kind": "Debuff", "Label": "Hex"},
        "Program": program([status(EVENT, "standard.hex", 1), *history(3)])})

if 'chosen.drain' not in acts:
    d['EnemyActions'].append({
        "Id": "chosen.drain", "PackageId": "sts", "NameKey": "Drain",
        "DescriptionKey": "Drain - 3 Weak, gains 3 Strength",
        "Intent": {"Kind": "Debuff", "Label": "Drain - 3 Weak"},
        "Program": program([status(EVENT, "standard.weak", 3),
                            status(SOURCE, "standard.strength", 3), *history(4)])})

if 'chosen.zap' not in acts:
    def zap(hit):
        return program([dmg(hit), *history(5)])
    d['EnemyActions'].append({
        "Id": "chosen.zap", "PackageId": "sts", "NameKey": "Zap",
        "DescriptionKey": "Zap - 18 damage",
        "Intent": {"Kind": "Attack", "Label": "Zap - 18 damage"},
        "Program": zap(18),
        "ProgramAsc": [{"AscensionMin": 2, "Program": zap(21)}]})


# ---- AI ----------------------------------------------------------------------------------------
def rule(conditions, priority, action=None, choice=None):
    body = {"Condition": {"kind": "intent.allOf", "value": {"Conditions": conditions}},
            "Priority": priority}
    if action:
        body["Action"] = {"value": action}
    if choice:
        body["Choice"] = choice
    return body


def last_is(value):
    return [{"kind": "intent.selfHasCounter",
             "value": {"Counter": {"value": "last_move"}, "Op": "Equal", "Value": value}}]


def round_eq(value):
    return [{"kind": "intent.round", "value": {"Op": "Equal", "Round": value}}]


asc17 = [{"kind": "intent.ascensionAtLeast", "value": {"Value": 17}}]
step_two = [{"Action": {"value": "chosen.poke"}, "Weight": 60},
            {"Action": {"value": "chosen.zap"}, "Weight": 40}]
step_one = [{"Action": {"value": "chosen.debilitate"}, "Weight": 50},
            {"Action": {"value": "chosen.drain"}, "Weight": 50}]

RULES = [
    # "On A17, Chosen always starts with Hex instead of Poke."
    rule(asc17 + round_eq(1), 96, action="chosen.hex"),
    rule(asc17 + round_eq(2), 95, action="chosen.poke"),
    # "Always starts with Poke followed by Hex."
    rule(round_eq(1), 94, action="chosen.poke"),
    rule(round_eq(2), 93, action="chosen.hex"),
    # Then the two-step cycle: (Debilitate/Drain) then (Poke/Zap). `last_move` says which step is
    # next: 3 = Hex, 4 = Drain, 5 = Zap, 1/2 = Poke/Debilitate.
    rule(last_is(4), 80, choice=step_two),
    rule(last_is(5), 80, choice=step_two),
    rule([], 60, choice=step_one),
]

for holder in (d['Monsters'] + [en for e in d['Encounters'] for en in (e.get('Enemies') or [])]):
    if holder.get('Id') != 'chosen':
        continue
    holder['HpMin'] = 95
    holder['HpMax'] = 99
    holder['MaxHealth'] = 95
    holder['MaxHealthAsc'] = [{"AscensionMin": 7, "MaxHealth": 98}]
    holder['Actions'] = [{"value": "chosen.poke"}, {"value": "chosen.hex"},
                         {"value": "chosen.debilitate"}, {"value": "chosen.drain"},
                         {"value": "chosen.zap"}]
    holder['StartingStatuses'] = []
    holder['IntentRules'] = copy.deepcopy(RULES)
    if 'AiNote' in holder:
        holder['AiNote'] = (
            "§213：wiki `Chosen`（Act 2 普通怪）—— HP 95-99（A7 98-103）、Poke 5×2（A2 6×2）、"
            "Hex（非攻击牌 → 抽牌堆塞 Dazed）、Debilitate 10 + 2 Vulnerable（A2 12）、"
            "Drain 3 Weak + 自己 +3 Strength、Zap 18（A2 21）。模式：开局 Poke→Hex"
            "（A17 改成 Hex→Poke）；之后 Debilitate/Drain 50-50，然后 Poke 60/Zap 40。")

json.dump(d, io.open(SRC, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=2)
open(SRC, 'a', encoding='utf-8').write('\n')
print("chosen rewritten + standard.hex")
