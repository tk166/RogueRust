"""§236 (part 2): 5 张"失去生命"的牌 + 两条状态。

wiki（`native/wiki_cards/*.txt` 原文）：
* `bloodletting` 0 费 Skill —— `Lose 3 HP. Gain (2;3) Energy.`
* `hemokinesis` 1 费 Uncommon Attack —— `Lose 2 HP. Deal (15;20) damage.`
* `offering` 0 费 Rare Skill —— `Lose 6 HP. Gain 2 Energy. Draw (3;5) cards. Exhaust.`
* `brutality` 0 费 Rare Power —— `(Innate on upgrade) At the start of your turn, lose 1 HP and draw 1 card.`
  ⇒ 新状态 `standard.brutality`（`TurnStarted` → `loseHp` + `draw`）
* `rupture` 1 费 Uncommon Power —— `Whenever you lose HP from a card, gain (1;2) Strength.`
  ⇒ 新状态 `standard.rupture`（`HpLost` 触发器 + `hpLoss.fromCard` 过滤）
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'

SEL_SELF = {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
SEL_TARGET = {"kind": "sel.eventTarget",
              "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def sequence(*children):
    return node("node.sequence", Children=list(children))


def lose_hp(amount, target=SEL_SELF):
    return node("node.loseHp", TargetSelector=target, Amount=const(amount))


def damage(amount, target=SEL_TARGET):
    return node("node.dealDamage", TargetSelector=target, Amount=const(amount),
                IgnoresBlock=False, Element=None)


def energy(amount):
    return node("node.gainResource", Amount=const(amount),
                ResourceId="standard.energy", TargetSelector=SEL_SELF)


def draw(count):
    return node("node.drawCards", TargetSelector=SEL_SELF, Count=const(count))


def apply_status(status, stacks, target=SEL_SELF):
    return node("node.applyStatus", TargetSelector=target,
                StatusDefinitionId={"value": status}, Stacks=const(stacks),
                DurationTurns=0, Charges=0)


CARDS = [
    dict(id='bloodletting', name='Bloodletting',
         text='Lose 3 HP. Gain 2 Energy.', cost=0, rarity='Uncommon', tags=['skill'],
         root=sequence(lose_hp(3), energy(2))),
    dict(id='bloodletting+', name='Bloodletting+',
         text='Lose 3 HP. Gain 3 Energy.', cost=0, rarity='Uncommon', tags=['skill'],
         root=sequence(lose_hp(3), energy(3))),
    dict(id='hemokinesis', name='Hemokinesis',
         text='Lose 2 HP. Deal 15 damage.', cost=1, rarity='Uncommon', tags=['attack'],
         root=sequence(lose_hp(2), damage(15))),
    dict(id='hemokinesis+', name='Hemokinesis+',
         text='Lose 2 HP. Deal 20 damage.', cost=1, rarity='Uncommon', tags=['attack'],
         root=sequence(lose_hp(2), damage(20))),
    dict(id='offering', name='Offering',
         text='Lose 6 HP. Gain 2 Energy. Draw 3 cards. Exhaust.',
         cost=0, rarity='Rare', tags=['skill'],
         root=sequence(lose_hp(6), energy(2), draw(3)), exhaust=True),
    dict(id='offering+', name='Offering+',
         text='Lose 6 HP. Gain 2 Energy. Draw 5 cards. Exhaust.',
         cost=0, rarity='Rare', tags=['skill'],
         root=sequence(lose_hp(6), energy(2), draw(5)), exhaust=True),
    dict(id='brutality', name='Brutality',
         text='At the start of your turn, lose 1 HP and draw 1 card.',
         cost=0, rarity='Rare', tags=['power'],
         root=apply_status('standard.brutality', 1)),
    dict(id='brutality+', name='Brutality+',
         text='Innate. At the start of your turn, lose 1 HP and draw 1 card.',
         cost=0, rarity='Rare', tags=['power', 'innate'],
         root=apply_status('standard.brutality', 1)),
    dict(id='rupture', name='Rupture',
         text='Whenever you lose HP from a card, gain 1 Strength.',
         cost=1, rarity='Uncommon', tags=['power'],
         root=apply_status('standard.rupture', 1)),
    dict(id='rupture+', name='Rupture+',
         text='Whenever you lose HP from a card, gain 2 Strength.',
         cost=1, rarity='Uncommon', tags=['power'],
         root=apply_status('standard.rupture', 2)),
]

BRUTALITY = {
    "Id": "standard.brutality",
    "PackageId": "sts",
    "NameKey": "Brutality",
    "DescriptionKey": "At the start of your turn, lose 1 HP and draw a card.",
    "Polarity": "Buff",
    "UsesStacks": True,
    "UsesDuration": False,
    "UsesCharges": False,
    "StackingBehavior": "MergeWithExistingInstance",
    "Tags": ["buff"],
    "PassiveModifiers": [],
    "Triggers": [{
        "Event": "TurnStarted",
        "Program": {
            "Id": {"Value": "(unnamed)"},
            "Root": sequence(lose_hp(1), draw(1)),
            "MaxNodeDepth": 64,
            "MaxProgramSteps": 1024,
        },
    }],
}

RUPTURE = {
    "Id": "standard.rupture",
    "PackageId": "sts",
    "NameKey": "Rupture",
    "DescriptionKey": "Whenever you lose HP from a card, gain Strength equal to its stacks.",
    "Polarity": "Buff",
    "UsesStacks": True,
    "UsesDuration": False,
    "UsesCharges": False,
    "StackingBehavior": "MergeWithExistingInstance",
    "Tags": ["buff"],
    "PassiveModifiers": [],
    "Triggers": [{
        "Event": "HpLost",
        "Program": {
            "Id": {"Value": "(unnamed)"},
            "Root": node(
                "node.conditional",
                Condition={"kind": "event.bool",
                           "value": {"FieldKey": "hpLoss.fromCard"}},
                Then=node(
                    "node.applyStatus",
                    TargetSelector=SEL_SELF,
                    StatusDefinitionId={"value": "standard.strength"},
                    Stacks={"kind": "combatantStatusStacks",
                            "value": {"Selector": SEL_SELF,
                                      "StatusId": {"value": "standard.rupture"}}},
                    DurationTurns=0,
                    Charges=0),
                Else=None),
            "MaxNodeDepth": 64,
            "MaxProgramSteps": 1024,
        },
    }],
}

CONTENT_PATH = CONTENT
raw = io.open(CONTENT_PATH, encoding='utf-8').read()
data = json.loads(raw)
have = {row['Id'] for row in data['Cards']}
assert not (have & {card['id'] for card in CARDS})

for card in CARDS:
    data['Cards'].append({
        'Id': card['id'],
        'PackageId': 'sts',
        'NameKey': card['name'],
        'DescriptionKey': card['text'],
        'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': card['cost']}],
        'Tags': [{'value': tag} for tag in card['tags']],
        'Rarity': card['rarity'],
        'Program': {'Id': {'Value': '(unnamed)'}, 'Root': card['root'],
                    'MaxNodeDepth': 64, 'MaxProgramSteps': 1024},
        'LifecyclePrograms': {},
        'RetainInHandOnTurnEnd': False,
        'TurnEndHandDestinationZone': 'DiscardPile',
        'PlayedCardDestinationZone': 'ExhaustPile' if card.get('exhaust') else 'DiscardPile',
    })
statuses = {row['Id'] for row in data['Statuses']}
assert 'standard.brutality' not in statuses and 'standard.rupture' not in statuses
data['Statuses'].append(BRUTALITY)
data['Statuses'].append(RUPTURE)
io.open(CONTENT_PATH, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(data, ensure_ascii=False, indent=2) + '\n')
print('cards', len(data['Cards']), 'statuses', len(data['Statuses']))
