"""§249.3 复现：把当初失败的那一版内容**原样**再拼一遍（四张牌 + 四条状态）。

与 `p249_matrix.py` 的差别：这里是**卡牌 + 状态**一起上（矩阵只上了状态），
而卡牌节目里用了 `node.sequence`（`the_bomb` 挂两条状态）—— 这是矩阵没覆盖的形状。
"""
import io
import json
import sys

ROOT = 'D:/Vibe/sts-tui/'
CONTENT = ROOT + 'tools/contentc/packages/sts/sts.roguedeck.json'

SELF = {"kind": "sel.source",
        "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
ALL_ENEMIES = {"kind": "sel.allEnemies",
               "value": {"Cardinality": "Any", "RequiredContextCapabilities": "Source"}}
TARGET = {"kind": "sel.eventTarget",
          "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def seq(*children):
    return node("node.sequence", Children=list(children))


def stacks_of(status_id):
    return {"kind": "combatantStatusStacks",
            "value": {"Selector": SELF, "StatusId": {"value": status_id}}}


def damage_all(amount):
    return node("node.dealDamage", TargetSelector=ALL_ENEMIES, Amount=amount,
                IgnoresBlock=False, Element=None)


def apply_status(status_id, stacks):
    return node("node.applyStatus", TargetSelector=SELF,
                StatusDefinitionId={"value": status_id}, Stacks=const(stacks),
                DurationTurns=0, Charges=0)


def compare(left, right, op):
    return {"kind": "compare", "value": {"Left": left, "Right": right, "Op": op}}


def conditional(condition, then, otherwise=None):
    return node("node.conditional", Condition=condition, Then=then, Else=otherwise)


def fact(key):
    return {"kind": "event.bool", "value": {"FieldKey": key}}


def program(root):
    return {'Id': {'Value': '(unnamed)'}, 'Root': root,
            'MaxNodeDepth': 64, 'MaxProgramSteps': 1024}


PANACHE = conditional(
    {"kind": "and", "value": {
        "Left": compare({"kind": "remainder",
                         "value": {"Left": {"kind": "cardsPlayedThisTurn", "value": {}},
                                   "Right": const(5)}}, const(0), "Equal"),
        "Right": compare({"kind": "cardsPlayedThisTurn", "value": {}}, const(0), "Greater")}},
    damage_all(stacks_of('standard.panache')))

SADISTIC = conditional(
    {"kind": "and", "value": {"Left": fact('status.isDebuff'),
                              "Right": fact('status.appliedToOther')}},
    node("node.dealDamage", TargetSelector=TARGET,
         Amount=stacks_of('standard.sadistic_nature'), IgnoresBlock=False, Element=None))

BOMB = seq(
    conditional(compare(stacks_of('standard.the_bomb'), const(1), 'LessOrEqual'),
                damage_all(stacks_of('standard.the_bomb_damage'))),
    node("node.modifyStatusStacks", TargetSelector=SELF,
         StatusDefinitionId={"value": "standard.the_bomb"}, Delta=const(-1)))

CARDS = [
    ('omega', 3, 'Special', 'power', 'At the end of your turn, deal 50 damage to ALL enemies.',
     apply_status('standard.omega', 50)),
    ('omega+', 3, 'Special', 'power', 'At the end of your turn, deal 60 damage to ALL enemies.',
     apply_status('standard.omega', 60)),
    ('panache', 0, 'Rare', 'power',
     'Every time you play 5 cards in a single turn, deal 10 damage to ALL enemies.',
     apply_status('standard.panache', 10)),
    ('panache+', 0, 'Rare', 'power',
     'Every time you play 5 cards in a single turn, deal 14 damage to ALL enemies.',
     apply_status('standard.panache', 14)),
    ('sadistic_nature', 0, 'Rare', 'power',
     'Whenever you apply a debuff to an enemy, they take 5 damage.',
     apply_status('standard.sadistic_nature', 5)),
    ('sadistic_nature+', 0, 'Rare', 'power',
     'Whenever you apply a debuff to an enemy, they take 7 damage.',
     apply_status('standard.sadistic_nature', 7)),
    ('the_bomb', 2, 'Rare', 'skill',
     'At the end of 3 turns, deal 40 damage to ALL enemies.',
     seq(apply_status('standard.the_bomb_damage', 40), apply_status('standard.the_bomb', 3))),
    ('the_bomb+', 2, 'Rare', 'skill',
     'At the end of 3 turns, deal 50 damage to ALL enemies.',
     seq(apply_status('standard.the_bomb_damage', 50), apply_status('standard.the_bomb', 3))),
]

STATUSES = [
    ('standard.omega', 'Omega',
     'At the end of your turn, deal damage equal to its stacks to ALL enemies.',
     [('TurnEnded', damage_all(stacks_of('standard.omega')))]),
    ('standard.panache', 'Panache',
     'Every time you play 5 cards in a single turn, deal damage equal to its stacks.',
     [('CardPlayed', PANACHE)]),
    ('standard.sadistic_nature', 'Sadistic Nature',
     'Whenever you apply a debuff to an enemy, they take damage equal to its stacks.',
     [('StatusApplied', SADISTIC)]),
    ('standard.the_bomb', 'The Bomb',
     'At the end of N turns, deal The Bomb Damage to ALL enemies.',
     [('TurnEnded', BOMB)]),
    ('standard.the_bomb_damage', 'The Bomb (damage)',
     'Bookkeeping twin: its stacks are the explosion damage.', []),
]


def main():
    data = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have_cards = {row['Id'] for row in data['Cards']}
    have_statuses = {row['Id'] for row in data['Statuses']}
    for card_id, cost, rarity, tag, text, root in CARDS:
        if card_id in have_cards:
            continue
        data['Cards'].append({
            'Id': card_id, 'PackageId': 'sts', 'NameKey': card_id,
            'DescriptionKey': text,
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': cost}],
            'Tags': [{'value': tag}, {'value': 'colorless'}],
            'Rarity': rarity, 'Program': program(root),
            'LifecyclePrograms': {}, 'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'DiscardPile'})
    for status_id, name, text, triggers in STATUSES:
        if status_id in have_statuses:
            continue
        data['Statuses'].append({
            'Id': status_id, 'PackageId': 'sts', 'NameKey': name,
            'DescriptionKey': text, 'Polarity': 'Buff', 'UsesStacks': True,
            'UsesDuration': False, 'UsesCharges': False,
            'StackingBehavior': 'MergeWithExistingInstance', 'Tags': ['buff'],
            'PassiveModifiers': [],
            'Triggers': [{'Event': event, 'Program': program(root)}
                         for event, root in triggers]})
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards %d, statuses %d' % (len(data['Cards']), len(data['Statuses'])))


main()
