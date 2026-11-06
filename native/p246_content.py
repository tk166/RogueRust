"""§246（内容）：`Warcry` 用 `DrawFirst` 归正；`Thinking Ahead` 上车。

原文（`native/wiki_cards/*.txt` / 数据模块）：
* `warcry` 0 费 Common Skill —— `Draw 1 card. Put a card from your hand on top of your draw pile.`
* `thinking_ahead` 0 费 Rare Skill —— `Draw 2 cards. Put a card from your hand on top of your
  draw pile. Exhaust.`（升级去掉 Exhaust）

⚠️ Warcry 原来是 `sequence[drawCards(1), chooseCards]` —— 那是**错的形状**：抽牌只是入队，
而候选快照在派发时发生 ⇒ **抽到的那张永远不在候选里**（手牌本来就空时连问句都不出现）。
现在改成 `chooseCards{DrawFirst: 1}`，抽牌在**问句节点内部同步**完成。
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
SEL_SELF = {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def put_one_on_top(draw_first):
    return node("node.chooseCards", OwnerSelector=SEL_SELF, FromZone="Hand",
                Min=1, Max=1, Then="ToDrawPileTop", ToZone="Hand", DrawFirst=draw_first)


NEW = [
    dict(id='thinking_ahead', name='Thinking Ahead', cost=0, rarity='Rare', tags=['skill'],
         text='Draw 2 cards. Put a card from your hand on top of your draw pile. Exhaust.',
         root=put_one_on_top(2), exhaust=True),
    dict(id='thinking_ahead+', name='Thinking Ahead+', cost=0, rarity='Rare', tags=['skill'],
         text='Draw 2 cards. Put a card from your hand on top of your draw pile.',
         root=put_one_on_top(2)),
]


def main():
    data = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in data['Cards']}

    # ① Warcry 归正：把 `sequence[drawCards(1), chooseCards]` 换成 `chooseCards{DrawFirst:1}`
    fixed = 0
    for row in data['Cards']:
        if row['Id'] not in ('warcry', 'warcry+'):
            continue
        root = row['Program']['Root']
        assert root['kind'] == 'node.sequence', root['kind']
        children = root['value']['Children']
        assert len(children) == 2, len(children)
        draw, choose = children
        assert draw['kind'] == 'node.drawCards', draw['kind']
        assert choose['kind'] == 'node.chooseCards', choose['kind']
        count = draw['value']['Count']['value']['Value']
        choose['value']['DrawFirst'] = count
        row['Program']['Root'] = choose
        fixed += 1

    # ② Thinking Ahead 上车
    for card in NEW:
        if card['id'] in have:
            continue
        data['Cards'].append({
            'Id': card['id'], 'PackageId': 'sts', 'NameKey': card['name'],
            'DescriptionKey': card['text'],
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': card['cost']}],
            'Tags': [{'value': tag} for tag in card['tags'] + ['colorless']],
            'Rarity': card['rarity'],
            'Program': {'Id': {'Value': '(unnamed)'}, 'Root': card['root'],
                        'MaxNodeDepth': 64, 'MaxProgramSteps': 1024},
            'LifecyclePrograms': {}, 'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'ExhaustPile' if card.get('exhaust') else 'DiscardPile',
        })
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('warcry fixed %d, cards %d' % (fixed, len(data['Cards'])))


main()
