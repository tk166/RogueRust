"""§240（内容）：`infernal_blade` —— 造一张随机 Attack、本回合 0 费、自消耗。

wiki：`Add a random Attack into your hand. It costs 0 this turn. Exhaust.`
费用 1（`CostPlus = 0` ⇒ 升级后 0 费）。类型是 **Skill**（不是 Attack）。
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
SEL_SELF = {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def root():
    return node("node.createRandomCardInstance", Tag="attack", ToZone="Hand",
                Count={"kind": "const", "value": {"Value": 1}}, CostZero=True)


CARDS = [
    dict(id='infernal_blade', name='Infernal Blade', cost=1,
         text='Add a random Attack into your hand. It costs 0 this turn. Exhaust.'),
    dict(id='infernal_blade+', name='Infernal Blade+', cost=0,
         text='Add a random Attack into your hand. It costs 0 this turn. Exhaust.'),
]


def main():
    data = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in data['Cards']}
    for card in CARDS:
        if card['id'] in have:
            continue
        data['Cards'].append({
            'Id': card['id'], 'PackageId': 'sts', 'NameKey': card['name'],
            'DescriptionKey': card['text'],
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': card['cost']}],
            'Tags': [{'value': 'skill'}], 'Rarity': 'Uncommon',
            'Program': {'Id': {'Value': '(unnamed)'}, 'Root': root(),
                        'MaxNodeDepth': 64, 'MaxProgramSteps': 1024},
            'LifecyclePrograms': {}, 'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'ExhaustPile',
        })
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards', len(data['Cards']))


main()
