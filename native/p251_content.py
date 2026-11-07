"""§251（内容）：A 组 5 张 —— `bite` / `expunger` / `shiv` / `smite` / `beta`。

牌面（wiki 正文，两处来源核对过）：

| 牌 | 费 | 正文 | 升级 |
|---|---|---|---|
| `bite` | 1 | Deal 7 damage. Heal 2 HP. | 8 / 3 |
| `expunger` | 1 | Deal **9 damage X times**. | 15 damage X times |
| `shiv` | 0 | Deal 4 damage. Exhaust. | 6 |
| `smite` | 1 | **Retain.** Deal 12 damage. Exhaust. | 16 |
| `beta` | 2 | Shuffle an **Omega** into draw pile. Exhaust. | 费 2→1，其余不变 |

两处需要说明的取舍（都写进 `port-plan.md` §251）：

1. **`expunger` 的 X**。wiki 说得极明确：X **不是**"打出它时的能量"，而是"**造它的那张
   `Conjure Blade` 被打出时的能量**"，所以 X 是**每副本**的属性、从造出来那一刻就固定。
   本内核里"每副本数据"的唯一载体是 mark counter（`standard.card_cost_delta` 与
   `standard.ritual_dagger_bonus` 都在用），所以 X 读 `card.counter("standard.expunger_x")`。
   而 `Conjure Blade` 是**观者**牌、不在本项目范围 ⇒ 今天没有任何内容会把它写成非 0，
   于是 `Expunger` 打出 0 次伤害 —— 那正是 wiki 写明的 "If X is 0, this card does nothing"。
   **这条不是缺口，是"造它的牌还没做"**。
2. **`beta` 的 "shuffle into draw pile"**。我们没有"洗进牌堆的随机位置"这个动作：
   `node.createCardInstance{ToZone: DrawPile}` 是**追加**（= 堆底）。StS 是随机洗入。
   写明的偏差；等"洗副本进牌堆"有了真实需求（`Pride` 只要"顶"、`Necronomicurse` 只要"手牌"）
   再做那个动作，比现在发明一个 `Placement: "Random"` 更诚实 —— 假随机会让"抽不到"变成 bug。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

SELF = {"kind": "sel.source",
        "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
TARGET = {"kind": "sel.eventTarget",
          "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def seq(*children):
    return node("node.sequence", Children=list(children))


def deal_damage(amount, selector=TARGET):
    return node("node.dealDamage", TargetSelector=selector, Amount=amount,
                IgnoresBlock=False, Element=None)


def heal(amount):
    return node("node.heal", TargetSelector=SELF, Amount=amount)


def repeat(count, body):
    # `MaxCount` 是**内容**给的循环上限（与 `whirlwind`/`skewer` 同一条：X 费牌的 X 是运行期的值，
    # 但"最多 32 遍"是内容在说"这棵树不会跑出预算"）。
    return node("node.repeat", Count=count, Body=body, MaxCount=32)


def card_counter(key):
    return {"kind": "card.counter", "value": {"CounterId": {"value": key}}}


def create_card(definition, zone):
    # `CardDefinitionId` 是 `{"value": ...}` 包装（与镜像内容里 `anger` 那条逐字同形）；
    # `Count` 缺席时内核按 1（`EffectProgramNativeNodes.cs:911`），但镜像里写着 1 —— 照抄。
    return node("node.createCardInstance", CardDefinitionId={"value": definition},
                ToZone=zone, TargetSelector=SELF, Count=const(1))


CARDS = [
    # ---- bite：伤害 + 固定回血（不是 Reaper 那种"按掉血回"）----
    dict(id='bite', cost=1, rarity='Special', tags=['attack', 'colorless'],
                      text='Deal 7 damage. Heal 2 HP.',
                      root=seq(deal_damage(const(7)), heal(const(2)))),
    dict(id='bite+', cost=1, rarity='Special', tags=['attack', 'colorless'],
         text='Deal 8 damage. Heal 3 HP.',
         root=seq(deal_damage(const(8)), heal(const(3)))),
    # ---- expunger：X 次，X 是**每副本**的（见模块头第 1 条）----
    dict(id='expunger', cost=1, rarity='Special', tags=['attack', 'colorless'],
         text='Deal 9 damage X times.',
         root=repeat(card_counter('standard.expunger_x'), deal_damage(const(9)))),
    dict(id='expunger+', cost=1, rarity='Special', tags=['attack', 'colorless'],
         text='Deal 15 damage X times.',
         root=repeat(card_counter('standard.expunger_x'), deal_damage(const(15)))),
    # ---- shiv / smite：两张纯数字牌 ----
    dict(id='shiv', cost=0, rarity='Special', tags=['attack', 'colorless'],
         text='Deal 4 damage. Exhaust.', root=deal_damage(const(4)), exhaust=True),
    dict(id='shiv+', cost=0, rarity='Special', tags=['attack', 'colorless'],
         text='Deal 6 damage. Exhaust.', root=deal_damage(const(6)), exhaust=True),
    dict(id='smite', cost=1, rarity='Special', tags=['attack', 'colorless'],
         text='Retain. Deal 12 damage. Exhaust.', root=deal_damage(const(12)),
         exhaust=True, retain=True),
    dict(id='smite+', cost=1, rarity='Special', tags=['attack', 'colorless'],
         text='Retain. Deal 16 damage. Exhaust.', root=deal_damage(const(16)),
         exhaust=True, retain=True),
    # ---- beta：把 Omega 放进抽牌堆（§249 的那张 Omega 现在有"来源"了）----
    dict(id='beta', cost=2, rarity='Special', tags=['skill', 'colorless'],
         text='Shuffle an Omega into draw pile. Exhaust.',
         root=seq(create_card('omega', 'DrawPile')), exhaust=True),
    # 升级只改费用（2 → 1），正文一字不变。
    dict(id='beta+', cost=1, rarity='Special', tags=['skill', 'colorless'],
         text='Shuffle an Omega into draw pile. Exhaust.',
         root=seq(create_card('omega', 'DrawPile')), exhaust=True),
]


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in doc['Cards']}
    added = 0
    for spec in CARDS:
        if spec['id'] in have:
            continue
        doc['Cards'].append({
            'Id': spec['id'],
            'PackageId': 'sts',
            'NameKey': spec['id'],
            'DescriptionKey': spec['text'],
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': spec['cost']}],
            'Tags': [{'value': tag} for tag in spec['tags']],
            'Rarity': spec['rarity'],
            'Program': program(spec['root']),
            'LifecyclePrograms': {},
            'RetainInHandOnTurnEnd': bool(spec.get('retain')),
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'ExhaustPile' if spec.get('exhaust') else 'DiscardPile',
        })
        added += 1
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('added %d row(s); cards now %d' % (added, len(doc['Cards'])))


main()
