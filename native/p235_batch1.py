"""§235 第一批：14 张红卡（纯内容，内核零改动）。

数据全部来自 `native/wiki_cards/<id>.txt`（本轮为 35 张红卡抓的 dump，`Description` 字段原文）：

| 牌 | wiki | 载体 |
|---|---|---|
| carnage | Ethereal. Deal (20;28) | `ethereal` tag + `dealDamage` |
| disarm | Enemy loses (2;3) Strength. Exhaust. | `modifyStatusStacks` 负增量 |
| immolate | (21;28) to ALL + add a Burn to discard | `dealDamage(allEnemies)` + `createCardInstance` |
| intimidate | Apply (1;2) Weak to ALL. Exhaust. | `applyStatus(allEnemies)` |
| seeing_red | Gain 2 Energy. Exhaust. | `gainResource` |
| shockwave | Apply (3;5) Weak **and** Vulnerable to ALL. Exhaust. | 两条 `applyStatus` |
| flame_barrier | Gain (12;16) Block. Whenever you are attacked **this turn**, deal (4;6) back. | `standard.flame_barrier` 的层数就是反伤值 |
| rage | Whenever you play an Attack this turn, gain (3;5) Block. | `standard.rage` 同理 |
| power_through | Add 2 Wounds into your hand. Gain (15;20) Block. | `createCardInstance` ×2 |
| reckless_charge | Deal (7;10). Shuffle a Dazed into your draw pile. | `createCardInstance` → DrawPile |
| sever_soul | Exhaust all non-Attack cards in your hand. Deal (16;22). | `forEachCardInZone`（Second Wind 的形状） |
| dropkick | Deal (5;8). If the enemy has Vulnerable, gain 1 Energy and draw 1. | `conditional` + `combatantStatusStacks` |
| headbutt | Deal (9;12). Put a card from your discard pile on top of your draw pile. | `chooseCards{FromZone: DiscardPile, Then: ToDrawPileTop}` |
| demon_form | At the start of your turn, gain (2;3) Strength. | 新状态 `standard.demon_form`（`TurnStarted` 触发器，`ritual` 的兄弟） |
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'native/sts_content_check.py'
INV = 'native/card_wiki_inventory.py'

SEL_SELF = {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
SEL_TARGET = {"kind": "sel.eventTarget",
              "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}
SEL_ENEMIES = {"kind": "sel.allEnemies",
               "value": {"Cardinality": "Many", "RequiredContextCapabilities": "Source"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def damage(amount, target=SEL_TARGET):
    return node("node.dealDamage", TargetSelector=target, Amount=const(amount),
                IgnoresBlock=False, Element=None)


def gain_block(amount, target=SEL_SELF):
    return node("node.gainBlock", TargetSelector=target, Amount=const(amount),
                PoolId={"value": "standard.block"})


def apply_status(status, stacks, target=SEL_SELF):
    return node("node.applyStatus", TargetSelector=target,
                StatusDefinitionId={"value": status}, Stacks=const(stacks),
                DurationTurns=0, Charges=0)


def modify(status, delta, target=SEL_TARGET):
    return node("node.modifyStatusStacks", TargetSelector=target,
                StatusDefinitionId={"value": status}, Delta=const(delta))


def create(definition, count, zone, target=SEL_TARGET):
    return node("node.createCardInstance", CardDefinitionId={"value": definition},
                Count=const(count), TargetSelector=target, ToZone=zone)


def draw(count):
    return node("node.drawCards", TargetSelector=SEL_SELF, Count=const(count))


def energy(amount):
    # ⚠️ `ResourceId` 是**裸字符串**（`gain_resource_node` 用 `str_field` 读），
    # 写成 `{"value": ...}` term 会在派发期报 `WrongKind("F_TERM")`。
    return node("node.gainResource", Amount=const(amount),
                ResourceId="standard.energy", TargetSelector=SEL_SELF)


def sequence(*children):
    return node("node.sequence", Children=list(children))


def exhaust_non_attacks():
    """`Exhaust all non-Attack cards in your hand`（Second Wind 的循环体，§225）。"""
    return node("node.forEachCardInZone", OwnerSelector=SEL_SELF, Zone="Hand", MaxIterations=64,
                Body=node("node.conditional", Condition={
                    "kind": "not",
                    "value": {"Condition": {"kind": "event.bool",
                                            "value": {"FieldKey": "card.hasTag.attack"}}}},
                    Then=node("node.moveCardToZone",
                              CardExpression={"kind": "cardInstance.iterated", "value": {}},
                              OwnerSelector=SEL_SELF, ToZone="ExhaustPile", Placement="Bottom"),
                    Else=None))


def has_vulnerable():
    # ⚠️ 表达式的 kind 是 `compare`（没有 `node.` 前缀 —— 那个前缀是**节点**的）。
    return {"kind": "compare", "value": {"Op": "Greater", "Left": {
        "kind": "combatantStatusStacks",
        "value": {"Selector": SEL_TARGET, "StatusId": {"value": "standard.vulnerable"}}},
        "Right": const(0)}}


CARDS = [
    # ── carnage：Ethereal 只是 tag，程序就是一条伤害 ──────────────────────────
    dict(id='carnage', name='Carnage',
         text='Ethereal. Deal 20 damage.', cost=2, rarity='Uncommon', tags=['attack', 'ethereal'],
         root=damage(20)),
    dict(id='carnage+', name='Carnage+',
         text='Ethereal. Deal 28 damage.', cost=2, rarity='Uncommon', tags=['attack', 'ethereal'],
         root=damage(28)),
    # ── disarm：负增量摘力量，自消耗 ─────────────────────────────────────────
    dict(id='disarm', name='Disarm',
         text='Enemy loses 2 Strength. Exhaust.', cost=1, rarity='Uncommon', tags=['skill'],
         root=modify('standard.strength', -2), exhaust=True),
    dict(id='disarm+', name='Disarm+',
         text='Enemy loses 3 Strength. Exhaust.', cost=1, rarity='Uncommon', tags=['skill'],
         root=modify('standard.strength', -3), exhaust=True),
    # ── immolate：全体伤害 + 塞一张 Burn 进弃牌堆 ───────────────────────────
    dict(id='immolate', name='Immolate',
         text='Deal 21 damage to ALL enemies. Add a Burn into your discard pile.',
         cost=2, rarity='Rare', tags=['attack'],
         root=sequence(damage(21, SEL_ENEMIES), create('burn', 1, 'DiscardPile'))),
    dict(id='immolate+', name='Immolate+',
         text='Deal 28 damage to ALL enemies. Add a Burn into your discard pile.',
         cost=2, rarity='Rare', tags=['attack'],
         root=sequence(damage(28, SEL_ENEMIES), create('burn', 1, 'DiscardPile'))),
    # ── intimidate / shockwave：全体上状态 ──────────────────────────────────
    dict(id='intimidate', name='Intimidate',
         text='Apply 1 Weak to ALL enemies. Exhaust.', cost=0, rarity='Uncommon', tags=['skill'],
         root=apply_status('standard.weak', 1, SEL_ENEMIES), exhaust=True),
    dict(id='intimidate+', name='Intimidate+',
         text='Apply 2 Weak to ALL enemies. Exhaust.', cost=0, rarity='Uncommon', tags=['skill'],
         root=apply_status('standard.weak', 2, SEL_ENEMIES), exhaust=True),
    dict(id='shockwave', name='Shockwave',
         text='Apply 3 Weak and Vulnerable to ALL enemies. Exhaust.',
         cost=2, rarity='Uncommon', tags=['skill'],
         root=sequence(apply_status('standard.weak', 3, SEL_ENEMIES),
                       apply_status('standard.vulnerable', 3, SEL_ENEMIES)), exhaust=True),
    dict(id='shockwave+', name='Shockwave+',
         text='Apply 5 Weak and Vulnerable to ALL enemies. Exhaust.',
         cost=2, rarity='Uncommon', tags=['skill'],
         root=sequence(apply_status('standard.weak', 5, SEL_ENEMIES),
                       apply_status('standard.vulnerable', 5, SEL_ENEMIES)), exhaust=True),
    # ── seeing_red：2 能量，自消耗 ──────────────────────────────────────────
    dict(id='seeing_red', name='Seeing Red',
         text='Gain 2 Energy. Exhaust.', cost=1, rarity='Uncommon', tags=['skill'],
         root=energy(2), exhaust=True),
    dict(id='seeing_red+', name='Seeing Red+',
         text='Gain 2 Energy. Exhaust.', cost=0, rarity='Uncommon', tags=['skill'],
         root=energy(2), exhaust=True),
    # ── flame_barrier / rage：两张"本回合每当…"的状态牌 ──────────────────────
    dict(id='flame_barrier', name='Flame Barrier',
         text='Gain 12 Block. Whenever you are attacked this turn, deal 4 damage back.',
         cost=2, rarity='Uncommon', tags=['skill', 'block'],
         root=sequence(gain_block(12), apply_status('standard.flame_barrier', 4))),
    dict(id='flame_barrier+', name='Flame Barrier+',
         text='Gain 16 Block. Whenever you are attacked this turn, deal 6 damage back.',
         cost=2, rarity='Uncommon', tags=['skill', 'block'],
         root=sequence(gain_block(16), apply_status('standard.flame_barrier', 6))),
    dict(id='rage', name='Rage',
         text='Whenever you play an Attack this turn, gain 3 Block.',
         cost=0, rarity='Uncommon', tags=['skill'],
         root=apply_status('standard.rage', 3)),
    dict(id='rage+', name='Rage+',
         text='Whenever you play an Attack this turn, gain 5 Block.',
         cost=0, rarity='Uncommon', tags=['skill'],
         root=apply_status('standard.rage', 5)),
    # ── power_through：两张 Wound 进手牌 + 格挡 ─────────────────────────────
    dict(id='power_through', name='Power Through',
         text='Add 2 Wounds into your hand. Gain 15 Block.',
         cost=1, rarity='Uncommon', tags=['skill', 'block'],
         root=sequence(create('wound', 2, 'Hand', SEL_SELF), gain_block(15))),
    dict(id='power_through+', name='Power Through+',
         text='Add 2 Wounds into your hand. Gain 20 Block.',
         cost=1, rarity='Uncommon', tags=['skill', 'block'],
         root=sequence(create('wound', 2, 'Hand', SEL_SELF), gain_block(20))),
    # ── reckless_charge：伤害 + 一张 Dazed 洗进抽牌堆 ───────────────────────
    dict(id='reckless_charge', name='Reckless Charge',
         text='Deal 7 damage. Shuffle a Dazed into your draw pile.',
         cost=0, rarity='Uncommon', tags=['attack'],
         root=sequence(damage(7), create('dazed', 1, 'DrawPile'))),
    dict(id='reckless_charge+', name='Reckless Charge+',
         text='Deal 10 damage. Shuffle a Dazed into your draw pile.',
         cost=0, rarity='Uncommon', tags=['attack'],
         root=sequence(damage(10), create('dazed', 1, 'DrawPile'))),
    # ── sever_soul：先消耗非攻击牌，再打一次 ────────────────────────────────
    dict(id='sever_soul', name='Sever Soul',
         text='Exhaust all non-Attack cards in your hand. Deal 16 damage.',
         cost=2, rarity='Uncommon', tags=['attack'],
         root=sequence(exhaust_non_attacks(), damage(16))),
    dict(id='sever_soul+', name='Sever Soul+',
         text='Exhaust all non-Attack cards in your hand. Deal 22 damage.',
         cost=2, rarity='Uncommon', tags=['attack'],
         root=sequence(exhaust_non_attacks(), damage(22))),
    # ── dropkick：打了再问"它是不是易伤" ────────────────────────────────────
    dict(id='dropkick', name='Dropkick',
         text='Deal 5 damage. If the enemy has Vulnerable, gain 1 Energy and draw 1 card.',
         cost=1, rarity='Uncommon', tags=['attack'],
         root=sequence(damage(5), node("node.conditional", Condition=has_vulnerable(),
                                       Then=sequence(energy(1), draw(1)), Else=None))),
    dict(id='dropkick+', name='Dropkick+',
         text='Deal 8 damage. If the enemy has Vulnerable, gain 1 Energy and draw 1 card.',
         cost=1, rarity='Uncommon', tags=['attack'],
         root=sequence(damage(8), node("node.conditional", Condition=has_vulnerable(),
                                       Then=sequence(energy(1), draw(1)), Else=None))),
    # ── headbutt：从弃牌堆挑一张放回抽牌堆顶（问句载体 §227 已有） ───────────
    dict(id='headbutt', name='Headbutt',
         text='Deal 9 damage. Put a card from your discard pile on top of your draw pile.',
         cost=1, rarity='Common', tags=['attack'],
         root=sequence(damage(9), node("node.chooseCards", OwnerSelector=SEL_SELF,
                                       FromZone="DiscardPile", Min=1, Max=1,
                                       Then="ToDrawPileTop"))),
    dict(id='headbutt+', name='Headbutt+',
         text='Deal 12 damage. Put a card from your discard pile on top of your draw pile.',
         cost=1, rarity='Common', tags=['attack'],
         root=sequence(damage(12), node("node.chooseCards", OwnerSelector=SEL_SELF,
                                        FromZone="DiscardPile", Min=1, Max=1,
                                        Then="ToDrawPileTop"))),
    # ── demon_form：每回合开始加力量（`ritual` 的 TurnStarted 兄弟） ─────────
    dict(id='demon_form', name='Demon Form',
         text='At the start of your turn, gain 2 Strength.',
         cost=3, rarity='Rare', tags=['power'],
         root=apply_status('standard.demon_form', 2)),
    dict(id='demon_form+', name='Demon Form+',
         text='At the start of your turn, gain 3 Strength.',
         cost=3, rarity='Rare', tags=['power'],
         root=apply_status('standard.demon_form', 3)),
]

DEMON_FORM_STATUS = {
    "Id": "standard.demon_form",
    "PackageId": "sts",
    "NameKey": "Demon Form",
    "DescriptionKey": "At the start of your turn, gain Strength equal to this status's stacks.",
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
            "Root": node("node.applyStatus", TargetSelector=SEL_SELF,
                         StatusDefinitionId={"value": "standard.strength"},
                         Stacks={"kind": "combatantStatusStacks",
                                 "value": {"Selector": SEL_SELF,
                                           "StatusId": {"value": "standard.demon_form"}}},
                         DurationTurns=0, Charges=0),
            "MaxNodeDepth": 64,
            "MaxProgramSteps": 1024,
        },
    }],
}

raw = io.open(CONTENT, encoding='utf-8').read()
data = json.loads(raw)
have = {row['Id'] for row in data['Cards']}
assert not (have & {card['id'] for card in CARDS}), 'already there'

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
assert 'standard.demon_form' not in {row['Id'] for row in data['Statuses']}
data['Statuses'].append(DEMON_FORM_STATUS)

io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(data, ensure_ascii=False, indent=2) + '\n')
print('cards now', len(data['Cards']), 'statuses', len(data['Statuses']))
