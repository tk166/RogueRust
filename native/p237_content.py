"""§237（内容）：5 张"每当…"Power + 5 条触发器状态。

wiki（`native/wiki_cards/*.txt`）：
* `juggernaut`  2 费 Rare     —— `Whenever you gain Block, deal (5;7) damage to a random enemy.`
* `evolve`      1 费 Uncommon —— `Whenever you draw a Status card, draw (1;2) card(s).`
* `fire_breathing` 1 费 Uncommon —— `Whenever you draw a Status or Curse card, deal (6;10) damage to ALL enemies.`
* `dark_embrace` 2 费 Uncommon (`CostPlus = 1`) —— `Whenever a card is Exhausted, draw 1 card.`
  ⇒ **升级改的是费用（2→1），不是抽牌数** —— 这是 wiki 的 `CostPlus` 字段说的，不是猜的。
* `feel_no_pain` 1 费 Uncommon —— `Whenever a card is Exhausted, gain (3;4) Block.`

一次解锁 5 张红卡，内核侧只加了三个触发器钩子（`BlockGained` / `CardsDrawn` / `CardExhausted`）。
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'

SEL_SELF = {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
SEL_ALL_ENEMIES = {"kind": "sel.allEnemies",
                   "value": {"Cardinality": "Any", "RequiredContextCapabilities": "Source"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def my_stacks(status):
    return {"kind": "combatantStatusStacks",
            "value": {"Selector": SEL_SELF, "StatusId": {"value": status}}}


def sequence(*children):
    return node("node.sequence", Children=list(children))


def draw(count):
    return node("node.drawCards", TargetSelector=SEL_SELF, Count=count)


def gain_block(amount):
    return node("node.gainBlock", TargetSelector=SEL_SELF, Amount=amount)


def damage_all(amount):
    return node("node.dealDamage", TargetSelector=SEL_ALL_ENEMIES, Amount=amount,
                IgnoresBlock=False, Element=None)


def damage_random_enemy(amount):
    return node("node.dealDamageToRandomTarget", TargetSelector=SEL_ALL_ENEMIES,
                Amount=amount, IgnoresBlock=False, Times=1)


def apply_status(status, stacks=1):
    return node("node.applyStatus", TargetSelector=SEL_SELF,
                StatusDefinitionId={"value": status}, Stacks=const(stacks),
                DurationTurns=0, Charges=0)


def fact(key):
    return {"kind": "event.bool", "value": {"FieldKey": key}}


def conditional(condition, then, otherwise=None):
    return node("node.conditional", Condition=condition, Then=then, Else=otherwise)


def trigger(event, root):
    return {"Event": event,
            "Program": {"Id": {"Value": "(unnamed)"}, "Root": root,
                        "MaxNodeDepth": 64, "MaxProgramSteps": 1024}}


def status(definition_id, name, text, triggers, stacks_based=True):
    return {
        "Id": definition_id,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": text,
        "Polarity": "Buff",
        "UsesStacks": stacks_based,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["buff"],
        "PassiveModifiers": [],
        "Triggers": triggers,
    }


CARDS = [
    dict(id='juggernaut', name='Juggernaut',
         text='Whenever you gain Block, deal 5 damage to a random enemy.',
         cost=2, rarity='Rare', tags=['power', 'block'], status=5),
    dict(id='juggernaut+', name='Juggernaut+',
         text='Whenever you gain Block, deal 7 damage to a random enemy.',
         cost=2, rarity='Rare', tags=['power', 'block'], status=7),
    dict(id='evolve', name='Evolve',
         text='Whenever you draw a Status card, draw 1 card.',
         cost=1, rarity='Uncommon', tags=['power'], status=1),
    dict(id='evolve+', name='Evolve+',
         text='Whenever you draw a Status card, draw 2 cards.',
         cost=1, rarity='Uncommon', tags=['power'], status=2),
    dict(id='fire_breathing', name='Fire Breathing',
         text='Whenever you draw a Status or Curse card, deal 6 damage to ALL enemies.',
         cost=1, rarity='Uncommon', tags=['power'], status=6),
    dict(id='fire_breathing+', name='Fire Breathing+',
         text='Whenever you draw a Status or Curse card, deal 10 damage to ALL enemies.',
         cost=1, rarity='Uncommon', tags=['power'], status=10),
    dict(id='dark_embrace', name='Dark Embrace',
         text='Whenever a card is Exhausted, draw 1 card.',
         cost=2, rarity='Uncommon', tags=['power'], status=1),
    dict(id='dark_embrace+', name='Dark Embrace+',
         text='Whenever a card is Exhausted, draw 1 card.',
         cost=1, rarity='Uncommon', tags=['power'], status=1),
    dict(id='feel_no_pain', name='Feel No Pain',
         text='Whenever a card is Exhausted, gain 3 Block.',
         cost=1, rarity='Uncommon', tags=['power'], status=3),
    dict(id='feel_no_pain+', name='Feel No Pain+',
         text='Whenever a card is Exhausted, gain 4 Block.',
         cost=1, rarity='Uncommon', tags=['power'], status=4),
]

# 每张牌挂的那条状态：id → (触发器, wiki 描述)
STATUSES = {
    'standard.juggernaut': status(
        'standard.juggernaut', 'Juggernaut',
        'Whenever you gain Block, deal damage equal to its stacks to a random enemy.',
        [trigger('BlockGained', damage_random_enemy(my_stacks('standard.juggernaut')))]),
    'standard.evolve': status(
        'standard.evolve', 'Evolve',
        'Whenever you draw a Status card, draw cards equal to its stacks.',
        [trigger('CardsDrawn', conditional(fact('card.hasTag.status'),
                                           draw(my_stacks('standard.evolve'))))]),
    'standard.fire_breathing': status(
        'standard.fire_breathing', 'Fire Breathing',
        'Whenever you draw a Status or Curse card, deal damage equal to its stacks to ALL enemies.',
        [trigger('CardsDrawn',
                 conditional({"kind": "or",
                              "value": {"Left": fact('card.hasTag.status'),
                                        "Right": fact('card.hasTag.curse')}},
                             damage_all(my_stacks('standard.fire_breathing'))))]),
    'standard.dark_embrace': status(
        'standard.dark_embrace', 'Dark Embrace',
        'Whenever a card is Exhausted, draw cards equal to its stacks.',
        [trigger('CardExhausted', draw(my_stacks('standard.dark_embrace')))]),
    'standard.feel_no_pain': status(
        'standard.feel_no_pain', 'Feel No Pain',
        'Whenever a card is Exhausted, gain Block equal to its stacks.',
        [trigger('CardExhausted', gain_block(my_stacks('standard.feel_no_pain')))]),
}

CARD_STATUS = {
    'juggernaut': 'standard.juggernaut',
    'evolve': 'standard.evolve',
    'fire_breathing': 'standard.fire_breathing',
    'dark_embrace': 'standard.dark_embrace',
    'feel_no_pain': 'standard.feel_no_pain',
}


def main():
    data = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in data['Cards']}
    assert not (have & {card['id'] for card in CARDS}), 'already patched'
    for card in CARDS:
        definition = CARD_STATUS[card['id'].rstrip('+')]
        data['Cards'].append({
            'Id': card['id'],
            'PackageId': 'sts',
            'NameKey': card['name'],
            'DescriptionKey': card['text'],
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': card['cost']}],
            'Tags': [{'value': tag} for tag in card['tags']],
            'Rarity': card['rarity'],
            'Program': {'Id': {'Value': '(unnamed)'},
                        'Root': apply_status(definition, card['status']),
                        'MaxNodeDepth': 64, 'MaxProgramSteps': 1024},
            'LifecyclePrograms': {},
            'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'DiscardPile',
        })
    statuses = {row['Id'] for row in data['Statuses']}
    assert not (statuses & set(STATUSES))
    for row in STATUSES.values():
        data['Statuses'].append(row)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards', len(data['Cards']), 'statuses', len(data['Statuses']))


main()
