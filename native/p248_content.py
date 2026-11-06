"""§248（内容）：`Enlightenment`（min(cost,1)）+ `Madness`（随机一张 → 0）。

原文（数据模块）：
* `enlightenment` 0 费 Uncommon Skill —— `Reduce the cost of all cards in your hand to 1 this
  (turn;combat).`
  ⇒ `forEachCardInZone{Hand}` + `addCardCounter{Mode: "SetMin", Delta: 1}`
  （**`SetMin` 不是 `Set`**：0 费牌不该被抬成 1）
* `madness` 1/0 费 Uncommon Skill —— `Reduce the cost of a random card in your hand to 0 this
  combat. Exhaust.`
  ⇒ `forEachCardInZone{Hand, Order: "Random", TakeFirst: 1}` + `addCardCounter{Mode: "Set", Delta: 0}`

「this turn / this combat」的差别这一版**没有分开**：两条都写的是"每副本绝对价"，而那个价在出牌
付款后就被清掉（§161.4 的承诺）。⇒ 两者都等价于"这张牌下一次被打出时免费"。⚠️ 记在这里，
别假装已经区分了 —— 真区分需要一个"回合末清空"的清除时机（`standard.card_cost_override` 目前
只有"付款后清"这一条）。
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
SEL_SELF = {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def apply_cap(n):
    """§248：`Enlightenment` 挂"费用至多 N"的状态（规则在 `CostStage::CapCostAt`）。
    """
    return node("node.applyStatus", TargetSelector=SEL_SELF,
                StatusDefinitionId={"value": "standard.cap_cost_at"},
                Stacks=const(n), DurationTurns=0, Charges=0)


def raise_or_lower_hand_cost(mode, value, random_one):
    # `SkipResolving`：打出的牌在终态回调之前仍留在手牌里（§225），而 `Madness` 是"手里随机**一张**"
  # —— 不排除自己的话，随机可能落到自己身上（它随后进消耗堆，玩家会觉得"这牌什么都没做"）。
    inner = {"OwnerSelector": SEL_SELF, "Zone": "Hand", "MaxIterations": 96,
             "SkipResolving": True}
    if random_one:
        inner["Order"] = "Random"
        inner["TakeFirst"] = 1
    counter = node("node.addCardCounter",
                   CardExpression={"kind": "cardInstance.iterated", "value": {}},
                   CounterId={"value": "standard.card_cost_override"},
                   Mode=mode, Delta=const(value), OwnerSelector=SEL_SELF)
    # ⚠️ §248：**跳过正在结算的那张牌**。打出的牌在终态回调之前仍留在手牌里（§225 的既有事实），
    # 而 `Madness` 是"手里随机**一张**"—— 不排除自己的话，随机有可能落到自己身上：
    # 那张牌随后进消耗堆，玩家会觉得"这牌什么都没做"。Second Wind / Fiend Fire 用的是同一个条件。
    body = counter
    return node("node.forEachCardInZone", Body=body, **inner)


CARDS = [
    dict(id='enlightenment', name='Enlightenment', cost=0, rarity='Uncommon', tags=['skill'],
         text='Reduce the cost of all cards in your hand to 1 this turn.',
         root=apply_cap(1)),
    dict(id='enlightenment+', name='Enlightenment+', cost=0, rarity='Uncommon', tags=['skill'],
         text='Reduce the cost of all cards in your hand to 1 this combat.',
         root=apply_cap(1)),
    dict(id='madness', name='Madness', cost=1, rarity='Uncommon', tags=['skill'],
         text='Reduce the cost of a random card in your hand to 0 this combat. Exhaust.',
         root=raise_or_lower_hand_cost("Set", 0, random_one=True), exhaust=True),
    dict(id='madness+', name='Madness+', cost=0, rarity='Uncommon', tags=['skill'],
         text='Reduce the cost of a random card in your hand to 0 this combat. Exhaust.',
         root=raise_or_lower_hand_cost("Set", 0, random_one=True), exhaust=True),
]


CAP = {
    "Id": "standard.cap_cost_at",
    "PackageId": "sts",
    "NameKey": "Cost Cap",
    "DescriptionKey": "Cards cost at most N (N = stacks).",
    "Polarity": "Buff",
    "UsesStacks": True,
    "UsesDuration": False,
    "UsesCharges": False,
    "StackingBehavior": "MergeWithExistingInstance",
    "Tags": ["buff"],
    "PassiveModifiers": [],
    "Triggers": [],
}


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
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'ExhaustPile' if card.get('exhaust') else 'DiscardPile',
        })
    statuses = {row['Id'] for row in data['Statuses']}
    if 'standard.cap_cost_at' not in statuses:
        data['Statuses'].append(CAP)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards', len(data['Cards']))


main()
