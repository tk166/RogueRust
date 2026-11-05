"""§225 B: `Second Wind` (exhaust every non-Attack card, block per card) and `Fiend Fire`.

Both are `forEachCardInZone(Hand)` + `moveCardToZone(iterated -> ExhaustPile)`; Second Wind wraps the
body in `conditional(not(event.bool card.hasTag.attack))`, which only works because §225 taught the
iteration to fill the card-tag bits (§225 A).

Exhausting through `moveCardToZone` is also the path the audit cares about: it goes through
`move_card_for`, the one place that runs `LifecyclePrograms[Exhausted]`.
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


def const(n):
    return {'kind': 'const', 'value': {'Value': n}}


def exhaust_iterated():
    """`moveCardToZone { CardExpression: cardInstance.iterated, ToZone: ExhaustPile }`。"""
    return {
        'kind': 'node.moveCardToZone',
        'value': {
            'CardExpression': {'kind': 'cardInstance.iterated', 'value': {}},
            'OwnerSelector': SOURCE,
            'ToZone': 'ExhaustPile',
            'Placement': 'Bottom',
            'ResultKey': None,
        },
    }


def gain_block(n):
    return {'kind': 'node.gainBlock', 'value': {'TargetSelector': SOURCE, 'Amount': const(n),
                                                'PoolId': {'value': 'standard.block'},
                                                'ResultKey': None}}


def damage(n):
    return {'kind': 'node.dealDamage', 'value': {'TargetSelector': EVENT, 'Amount': const(n),
                                                 'ResultKey': None, 'IgnoresBlock': False,
                                                 'Element': None}}


def for_each_hand(body):
    return {
        'kind': 'node.forEachCardInZone',
        'value': {
            'OwnerSelector': SOURCE,
            'Zone': 'Hand',
            'MaxIterations': 64,
            'Body': body,
        },
    }


def sequence(children):
    return {'kind': 'node.sequence', 'value': {'Children': children}}


def program(root):
    return {'Id': {'Value': '(unnamed)'}, 'Root': root, 'MaxNodeDepth': 64,
            'MaxProgramSteps': 1024}


def not_attack():
    return {'kind': 'not', 'value': {'Condition': {'kind': 'event.bool',
                                                   'value': {'FieldKey': 'card.hasTag.attack'}}}}


def second_wind_root(block_per_card):
    # 非攻击牌 ⇒ 先消耗它，再按"每张"给格挡；攻击牌 ⇒ 什么都不做（`Else` 缺席 = 空）。
    return for_each_hand({
        'kind': 'node.conditional',
        'value': {
            'Condition': not_attack(),
            'Then': sequence([exhaust_iterated(), gain_block(block_per_card)]),
            'Else': None,
        },
    })


def fiend_fire_root(per_card):
    # 整手牌逐张消耗，每张打一次伤害；牌自己的 `Exhaust` 由落区表达。
    return for_each_hand(sequence([exhaust_iterated(), damage(per_card)]))


NEW = [
    ('second_wind', 'Second Wind', 1, 'Uncommon', ['skill'],
     'Exhaust all non-Attack cards in your hand. Gain 5 Block for each card Exhausted.',
     {'PlayedCardDestinationZone': 'ExhaustPile'},
     second_wind_root(5), second_wind_root(7)),
    ('fiend_fire', 'Fiend Fire', 2, 'Rare', ['attack'],
     'Exhaust your hand. Deal 7 damage for each card Exhausted. Exhaust.',
     {'PlayedCardDestinationZone': 'ExhaustPile'},
     fiend_fire_root(7), fiend_fire_root(10)),
]

added = []
for card_id, name, cost, rarity, tags, description, extra, base_root, plus_root in NEW:
    assert card_id not in cards, card_id
    for variant, root in ((card_id, base_root), (card_id + '+', plus_root)):
        doc['Cards'].append({
            'Id': variant,
            'PackageId': 'sts',
            'NameKey': name + ('+' if variant.endswith('+') else ''),
            'DescriptionKey': description,
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': cost}],
            'Tags': [{'value': tag} for tag in tags],
            'Rarity': rarity,
            'Program': program(root),
            'PlayedCardDestinationZone': extra.get('PlayedCardDestinationZone', 'DiscardPile'),
            'TurnEndHandDestinationZone': 'Hand',
            'RetainInHandOnTurnEnd': False,
            'LifecyclePrograms': {},
        })
        added.append(variant)

json.dump(doc, io.open(SRC, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=2)
open(SRC, 'a', encoding='utf-8').write('\n')
print('cards added: %s' % ', '.join(added))
