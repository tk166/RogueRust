"""§214: the two remaining Act-3 strays -- Spiker and Spire Growth -- per the wiki.

Spiker (`native/wiki_asc/shapes.txt` -> "Spiker" section):
  HP 42-56 (A7: 44), Thorns 3 (A2 4 | A17 7 -- already done in §207),
  moves: `Attack` 7 (A2: 9) and `Buff Thorns` (+2 Thorns).
  AI: 50/50 each turn; `Attack` never twice in a row; `Buff Thorns` at most **6 times**, after which
  it only uses `Attack`.

Spire Growth (`native/wiki_asc/spire_growth.txt`):
  HP 170 (A7: 190),
  moves: `Constrict` (10; A2: 12 Constricted), `Quick Tackle` 16 (A2: 18), `Smash` 22 (A2: 25).
  AI: 50/50 Quick Tackle / Constrict, but `Smash` if the last move was Constrict **or** the player is
  already Constricted; neither attack can be used three times in a row.
"""
import io
import json
import copy

SRC = 'tools/contentc/packages/sts/sts.roguedeck.json'
SOURCE = {"kind": "sel.source", "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
EVENT = {"kind": "sel.eventTarget", "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}

d = json.load(io.open(SRC, encoding='utf-8'))


def program(children):
    root = children[0] if len(children) == 1 else {"kind": "node.sequence", "value": {"Children": children}}
    return {"Id": {"Value": "(unnamed)"}, "Root": root, "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def history(k):
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


def status(name, stacks, target=EVENT):
    return {"kind": "node.applyStatus", "value": {
        "TargetSelector": target, "StatusDefinitionId": {"value": name},
        "Stacks": {"kind": "const", "value": {"Value": stacks}},
        "DurationTurns": 0, "Charges": 0, "ResultKey": None}}


def counter_read(key):
    return {"kind": "combatantCounter", "value": {"Selector": SOURCE, "CounterId": key}}


acts = {a['Id']: a for a in d['EnemyActions']}

# ---- Spiker -----------------------------------------------------------------------------------
# `spiker.cut` keeps its id (it is the wiki's `Attack`) but gets the wiki's numbers; `spiker.spike`
# becomes `Buff Thorns` -- the id stays as well, so the encounter rosters do not have to change.
acts['spiker.cut']['Program'] = program([dmg(7), *history(1)])
acts['spiker.cut']['ProgramAsc'] = [{"AscensionMin": 2, "Program": program([dmg(9), *history(1)])}]
acts['spiker.cut']['DescriptionKey'] = "Attack - 7 damage"
acts['spiker.cut']['Intent'] = {"Kind": "Attack", "Label": "Attack - 7 damage"}

# "Cannot use Buff Thorns once it has been used 6 times" -- a counter the move itself increments.
acts['spiker.spike']['Program'] = program([
    status('standard.thorns', 2, SOURCE),
    {"kind": "node.setCombatantCounter", "value": {
        "TargetSelector": SOURCE, "CounterId": {"value": "thorns_buffs"},
        "Amount": {"kind": "const", "value": {"Value": 1}}, "Relative": True}},
    *history(2)])
acts['spiker.spike'].pop('ProgramAsc', None)
acts['spiker.spike']['DescriptionKey'] = "Buff Thorns - gains 2 Thorns"
acts['spiker.spike']['Intent'] = {"Kind": "Buff", "Label": "Buff Thorns +2"}


# ---- Spire Growth -----------------------------------------------------------------------------
def constrict(stacks):
    return program([status('standard.constricted', stacks), *history(1)])


def tackle(hit):
    return program([dmg(hit), *history(2)])


def smash(hit):
    return program([dmg(hit), *history(3)])


acts['spire_growth.strategic']['Program'] = constrict(10)
acts['spire_growth.strategic']['ProgramAsc'] = [{"AscensionMin": 2, "Program": constrict(12)}]
acts['spire_growth.strategic']['DescriptionKey'] = "Constrict - 10 Constricted"
acts['spire_growth.strategic']['Intent'] = {"Kind": "Debuff", "Label": "Constrict 10"}

acts['spire_growth.aggressive']['Program'] = tackle(16)
acts['spire_growth.aggressive']['ProgramAsc'] = [{"AscensionMin": 2, "Program": tackle(18)}]
acts['spire_growth.aggressive']['DescriptionKey'] = "Quick Tackle - 16 damage"
acts['spire_growth.aggressive']['Intent'] = {"Kind": "Attack", "Label": "Quick Tackle - 16"}

acts['spire_growth.aggressive_heavy']['Program'] = smash(22)
acts['spire_growth.aggressive_heavy']['ProgramAsc'] = [{"AscensionMin": 2, "Program": smash(25)}]
acts['spire_growth.aggressive_heavy']['DescriptionKey'] = "Smash - 22 damage"
acts['spire_growth.aggressive_heavy']['Intent'] = {"Kind": "Attack", "Label": "Smash - 22"}


# ---- AI ---------------------------------------------------------------------------------------
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


def last_and_prev(value):
    return last_is(value) + [{"kind": "intent.selfHasCounter",
                              "value": {"Counter": {"value": "prev_move"}, "Op": "Equal",
                                        "Value": value}}]


SPIKER_RULES = [
    # "Cannot use Buff Thorns once it has been used 6 times and will instead use Attack."
    rule([{"kind": "intent.selfHasCounter",
           "value": {"Counter": {"value": "thorns_buffs"}, "Op": "GreaterOrEqual", "Value": 6}}],
         90, action="spiker.cut"),
    # "Cannot use Attack twice in a row."
    rule(last_is(1), 80, action="spiker.spike"),
    # "On every turn, 50/50 Attack or Buff Thorns."
    rule([], 60, choice=[{"Action": {"value": "spiker.cut"}, "Weight": 50},
                         {"Action": {"value": "spiker.spike"}, "Weight": 50}]),
]

SPIRE_RULES = [
    # "If Constrict was used last turn **or** the player already has Constricted, it uses Smash."
    rule(last_is(1) + [{"kind": "intent.opponentHasStatus",
                        "value": {"Status": {"value": "standard.constricted"}, "MinStacks": 1}}],
         92, action="spire_growth.aggressive_heavy"),
    rule(last_is(1), 90, action="spire_growth.aggressive_heavy"),
    rule([{"kind": "intent.opponentHasStatus",
           "value": {"Status": {"value": "standard.constricted"}, "MinStacks": 1}}],
         89, action="spire_growth.aggressive_heavy"),
    # "Cannot use either attack three times in a row."
    rule(last_and_prev(2), 80, action="spire_growth.strategic"),
    rule(last_and_prev(3), 80, choice=[{"Action": {"value": "spire_growth.aggressive"}, "Weight": 50},
                                       {"Action": {"value": "spire_growth.strategic"}, "Weight": 50}]),
    # "Each turn, 50/50 Quick Tackle or Constrict."
    rule([], 60, choice=[{"Action": {"value": "spire_growth.aggressive"}, "Weight": 50},
                         {"Action": {"value": "spire_growth.strategic"}, "Weight": 50}]),
]

for holder in (d['Monsters'] + [en for e in d['Encounters'] for en in (e.get('Enemies') or [])]):
    mid = holder.get('Id')
    if mid == 'spiker':
        holder['HpMin'] = 42
        holder['HpMax'] = 56
        holder['MaxHealth'] = 42
        holder['MaxHealthAsc'] = [{"AscensionMin": 7, "MaxHealth": 44}]
        holder['Actions'] = [{"value": "spiker.cut"}, {"value": "spiker.spike"}]
        holder['IntentRules'] = copy.deepcopy(SPIKER_RULES)
        if 'AiNote' in holder:
            holder['AiNote'] = (
                "§214：wiki `Shapes#Spiker` —— HP 42-56（A7 44-60）、Thorns 3（A2 4 / A17 7，§207）、"
                "Attack 7（A2 9）、Buff Thorns +2（最多 6 次，之后只能 Attack）。每回合 50-50；"
                "Attack 不能连两次。")
    elif mid == 'spire_growth':
        holder['HpMin'] = 170
        holder['HpMax'] = 170
        holder['MaxHealth'] = 170
        holder['MaxHealthAsc'] = [{"AscensionMin": 7, "MaxHealth": 190}]
        holder['Actions'] = [{"value": "spire_growth.strategic"},
                             {"value": "spire_growth.aggressive"},
                             {"value": "spire_growth.aggressive_heavy"}]
        holder['IntentRules'] = copy.deepcopy(SPIRE_RULES)
        if 'AiNote' in holder:
            holder['AiNote'] = (
                "§214：wiki `Spire Growth` —— HP 170（A7 190）、Constrict 10（A2 12）、Quick Tackle 16"
                "（A2 18）、Smash 22（A2 25）。每回合 50-50 Quick Tackle/Constrict；若上回合 Constrict "
                "或玩家已 Constricted ⇒ Smash；两招都不能连三次。")

json.dump(d, io.open(SRC, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=2)
open(SRC, 'a', encoding='utf-8').write('\n')
print("spiker + spire growth rewritten")
