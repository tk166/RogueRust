"""§241（内容）：`havoc` —— 打出抽牌堆顶那张并消耗（升级只是费用 1 → 0）。"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'


def main():
    data = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in data['Cards']}
    root = {"kind": "node.playTopCardOfDrawPile", "value": {"ResultKey": None}}
    for cid, name, cost in (('havoc', 'Havoc', 1), ('havoc+', 'Havoc+', 0)):
        if cid in have:
            continue
        data['Cards'].append({
            'Id': cid, 'PackageId': 'sts', 'NameKey': name,
            'DescriptionKey': 'Play the top card of your draw pile and Exhaust it.',
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': cost}],
            'Tags': [{'value': 'skill'}], 'Rarity': 'Common',
            'Program': {'Id': {'Value': '(unnamed)'}, 'Root': root,
                        'MaxNodeDepth': 64, 'MaxProgramSteps': 1024},
            'LifecyclePrograms': {}, 'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile', 'PlayedCardDestinationZone': 'DiscardPile',
        })
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards', len(data['Cards']))


main()
