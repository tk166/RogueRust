"""§247（内容）：`Mind Blast`（zoneCount）+ `Enlightenment`（Mode: Set）。

原文（数据模块 / dump）：
* `mind_blast` 2/1 费 Uncommon Attack —— `Innate. Deal damage equal to the number of cards in
  your draw pile.`
  ⇒ `dealDamage(combatantZoneCount{Selector: sel.source, Zone: "DrawPile"})`
  （升级只改**费用** 2→1，伤害是"按张数"没有数字可改）
* `enlightenment` 0 费 Uncommon Skill —— `Reduce the cost of all cards in your hand to 1 this
  (turn;combat).`
  ⇒ `forEachCardInZone{Hand}` + `addCardCounter{CardExpression: cardInstance.iterated,
  CounterId: "standard.card_cost_override", Mode: "Set", Delta: 1}`

⚠️ `Madness`（"把手里**随机一张**的价格设成 0"）这一批做不了：`forEachCardInZone` 只有
`TakeFirst`（按牌堆序），没有随机取一张。留成下一批。
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


def damage_zone_count():
    return node("node.dealDamage", TargetSelector=SEL_TARGET,
                Amount={"kind": "combatantZoneCount",
                        "value": {"Selector": SEL_SELF, "Zone": "DrawPile"}},
                IgnoresBlock=False, Element=None)


def set_hand_cost_to(value):
    # 形状照 Second Wind（`second_wind` 的 JSON）：`MaxIterations` 是**裸 int**，
    # 而 `TagFilter` / `MarkFilter` 是**省略**（写 `null` 会让序列化器写出一个 F_JSON 格）。
    body = node("node.forEachCardInZone", OwnerSelector=SEL_SELF, Zone="Hand",
                MaxIterations=96,
                Body=node("node.addCardCounter",
                          CardExpression={"kind": "cardInstance.iterated", "value": {}},
                          CounterId={"value": "standard.card_cost_override"},
                          Mode="Set", Delta=const(value),
                          OwnerSelector=SEL_SELF))


CARDS = [
    dict(id='mind_blast', name='Mind Blast', cost=2, rarity='Uncommon',
         tags=['attack', 'innate'],
         text='Innate. Deal damage equal to the number of cards in your draw pile.',
         root=damage_zone_count()),
    dict(id='mind_blast+', name='Mind Blast+', cost=1, rarity='Uncommon',
         tags=['attack', 'innate'],
         text='Innate. Deal damage equal to the number of cards in your draw pile.',
         root=damage_zone_count()),
    dict(id='enlightenment', name='Enlightenment', cost=0, rarity='Uncommon', tags=['skill'],
         text='Reduce the cost of all cards in your hand to 1 this turn.',
         root=set_hand_cost_to(1)),
    dict(id='enlightenment+', name='Enlightenment+', cost=0, rarity='Uncommon', tags=['skill'],
         text='Reduce the cost of all cards in your hand to 1 this combat.',
         root=set_hand_cost_to(1)),
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
            'Tags': [{'value': tag} for tag in card['tags'] + ['colorless']],
            'Rarity': card['rarity'],
            'Program': {'Id': {'Value': '(unnamed)'}, 'Root': card['root'],
                        'MaxNodeDepth': 64, 'MaxProgramSteps': 1024},
            'LifecyclePrograms': {}, 'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile', 'PlayedCardDestinationZone': 'DiscardPile',
        })
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards', len(data['Cards']))


main()
