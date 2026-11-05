"""§221: ten Ironclad cards that the existing node vocabulary can already express, plus two relics.

Every number comes from `native/wiki_cards/<id>.txt` (fetched by `fetch_wiki_cards.py`), and the
program shapes are copied from nodes already in this content (`node.drawCards` takes
`Count` + `TargetSelector`; `node.createCardInstance` takes `CardDefinitionId`/`Count`/`ToZone`).

No kernel work: `cleave`/`thunderclap` use the `allEnemies` selector, `pummel` uses `node.repeat`,
`battle_trance` applies the existing `standard.draw_reduction`, and the exhaust-on-play cards use
`PlayedCardDestinationZone` (§219).
"""
import io
import json

SRC = 'tools/contentc/packages/sts/sts.roguedeck.json'
doc = json.load(io.open(SRC, encoding='utf-8'))
cards = {card['Id']: card for card in doc['Cards']}

SOURCE = {'kind': 'sel.source', 'value': {'Cardinality': 'ZeroOrOne',
                                          'RequiredContextCapabilities': 'Source'}}
EVENT = {'kind': 'sel.eventTarget', 'value': {'Cardinality': 'ZeroOrOne',
                                              'RequiredContextCapabilities': 'EventTarget'}}
ALL_ENEMIES = {'kind': 'sel.allEnemies', 'value': {'Cardinality': 'Any',
                                                   'RequiredContextCapabilities': 'Source'}}
ENERGY = {'value': 'standard.energy'}


def const(n):
    return {'kind': 'const', 'value': {'Value': n}}


def damage(n, target=EVENT):
    return {'kind': 'node.dealDamage', 'value': {'TargetSelector': target, 'Amount': const(n),
                                                 'ResultKey': None, 'IgnoresBlock': False,
                                                 'Element': None}}


def block(n):
    return {'kind': 'node.gainBlock', 'value': {'TargetSelector': SOURCE, 'Amount': const(n),
                                                'PoolId': {'value': 'standard.block'},
                                                'ResultKey': None}}


def status(name, stacks, target=EVENT):
    return {'kind': 'node.applyStatus', 'value': {'TargetSelector': target,
                                                  'StatusDefinitionId': {'value': name},
                                                  'Stacks': const(stacks),
                                                  'DurationTurns': 0, 'Charges': 0,
                                                  'ResultKey': None}}


def draw(count):
    return {'kind': 'node.drawCards', 'value': {'TargetSelector': SOURCE, 'Count': const(count),
                                                'ResultKey': None}}


def add_card(card_id, count, zone):
    return {'kind': 'node.createCardInstance',
            'value': {'CardDefinitionId': {'value': card_id}, 'Count': const(count),
                      'TargetSelector': SOURCE, 'ToZone': zone, 'ResultKey': None}}


def repeat(times, body):
    return {'kind': 'node.repeat', 'value': {'Count': const(times), 'Body': body}}


def program(children):
    root = children[0] if len(children) == 1 else {'kind': 'node.sequence',
                                                   'value': {'Children': children}}
    return {'Id': {'Value': '(unnamed)'}, 'Root': root, 'MaxNodeDepth': 64,
            'MaxProgramSteps': 1024}


# id, name, cost, rarity, tags, description, [extra keys], program(children), plus_program|None
NEW = [
    ('cleave', 'Cleave', 1, 'Common', ['attack'],
     'Deal 8 damage to ALL enemies.',
     {}, [damage(8, ALL_ENEMIES)],
     [damage(11, ALL_ENEMIES)]),
    ('pommel_strike', 'Pommel Strike', 1, 'Common', ['attack', 'strike'],
     'Deal 9 damage. Draw 1 card.',
     {}, [damage(9), draw(1)],
     [damage(10), draw(2)]),
    ('shrug_it_off', 'Shrug It Off', 1, 'Common', ['skill', 'block'],
     'Gain 8 Block. Draw 1 card.',
     {}, [block(8), draw(1)],
     [block(11), draw(1)]),
    ('thunderclap', 'Thunderclap', 1, 'Common', ['attack'],
     'Deal 4 damage and apply 1 Vulnerable to ALL enemies.',
     {}, [damage(4, ALL_ENEMIES), status('standard.vulnerable', 1, ALL_ENEMIES)],
     [damage(7, ALL_ENEMIES), status('standard.vulnerable', 1, ALL_ENEMIES)]),
    ('bludgeon', 'Bludgeon', 3, 'Rare', ['attack'],
     'Deal 32 damage.',
     {}, [damage(32)],
     [damage(42)]),
    ('impervious', 'Impervious', 2, 'Rare', ['skill', 'block'],
     'Gain 30 Block. Exhaust.',
     {'PlayedCardDestinationZone': 'ExhaustPile'}, [block(30)],
     [block(40)]),
    ('pummel', 'Pummel', 1, 'Uncommon', ['attack'],
     'Deal 2 damage 4 times. Exhaust.',
     {'PlayedCardDestinationZone': 'ExhaustPile'}, [repeat(4, damage(2))],
     [repeat(5, damage(2))]),
    ('wild_strike', 'Wild Strike', 1, 'Common', ['attack', 'strike'],
     'Deal 12 damage. Shuffle a Wound into your draw pile.',
     {}, [damage(12), add_card('wound', 1, 'DrawPile')],
     [damage(17), add_card('wound', 1, 'DrawPile')]),
    ('ghostly_armor', 'Ghostly Armor', 1, 'Uncommon', ['skill', 'block', 'ethereal'],
     'Ethereal. Gain 10 Block.',
     {'TurnEndHandDestinationZone': 'ExhaustPile'}, [block(10)],
     [block(13)]),
    ('battle_trance', 'Battle Trance', 0, 'Uncommon', ['skill'],
     'Draw 3 cards. You cannot draw additional cards this turn.',
     {}, [draw(3), status('standard.draw_reduction', 1, SOURCE)],
     [draw(4), status('standard.draw_reduction', 1, SOURCE)]),
]

added = []
for card_id, name, cost, rarity, tags, description, extra, base_children, plus_children in NEW:
    assert card_id not in cards, '%s already exists' % card_id
    for variant, children in ((card_id, base_children), (card_id + '+', plus_children)):
        if variant.endswith('+') and plus_children is None:
            continue
        card = {
            'Id': variant,
            'PackageId': 'sts',
            'NameKey': name + ('+' if variant.endswith('+') else ''),
            'DescriptionKey': description,
            'Costs': [{'ResourceId': ENERGY, 'Amount': cost}],
            'Tags': [{'value': tag} for tag in tags],
            'DescriptionKeyPlus': description,
            'Rarity': rarity,
            'Program': program(children),
            'PlayedCardDestinationZone': extra.get('PlayedCardDestinationZone', 'DiscardPile'),
            'TurnEndHandDestinationZone': extra.get('TurnEndHandDestinationZone', 'Hand'),
            'RetainInHandOnTurnEnd': False,
            'LifecyclePrograms': {},
        }
        doc['Cards'].append(card)
        added.append(variant)

# 两张遗物：都落在既有的 `StartCombatStatus` 上（`bag_of_marbles` = 1 Vulnerable，wiki；`oddly_smooth_stone` = 1 Dexterity）。
relics = {relic['Id']: relic for relic in doc['Relics']}
for relic_id, display, rarity in [('bag_of_marbles', 'Bag of Marbles', 'Common'),
                                  ('oddly_smooth_stone', 'Oddly Smooth Stone', 'Common')]:
    assert relic_id not in relics, relic_id
    doc['Relics'].append({'Id': relic_id, 'DisplayName': display, 'RunPrograms': None,
                          'CombatRules': None, 'Rarity': rarity})
    print('relic %s added' % relic_id)

json.dump(doc, io.open(SRC, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=2)
open(SRC, 'a', encoding='utf-8').write('\n')
print('cards added (%d rows): %s' % (len(added), ', '.join(added)))
