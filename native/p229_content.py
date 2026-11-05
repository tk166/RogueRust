"""§229 (part 2): `Rip and Tear`（§228 的随机目标载体直接用）+ `Rampage`（每副本计数器）。

wiki（`native/wiki_cards/`）：
* `rip_and_tear` 1 费 Uncommon Attack —— "Deal (7;9) damage to a random enemy twice."
  ⇒ 用 §228 的 `node.dealDamageToRandomTarget{Times: 2}`，**内核一行没加**；
* `rampage` 1 费 Uncommon Attack —— "Deal 8 damage. Increase this card's damage by (5;8) this combat."
  ⇒ 伤害 = `8 + card.counter`，然后给**这份副本**的计数器加 5(8)。
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'native/sts_content_check.py'
INV = 'native/card_wiki_inventory.py'

RAM_COUNTER = "standard.rampage_bonus"

SEL_SOURCE = {
    "kind": "sel.source",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"},
}
SEL_ALL_ENEMIES = {
    "kind": "sel.allEnemies",
    "value": {"Cardinality": "Many", "RequiredContextCapabilities": "Source"},
}
SEL_EVENT_TARGET = {
    "kind": "sel.eventTarget",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"},
}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def card(cid, name, text, cost, rarity, root):
    return {
        "Id": cid,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": text,
        "Costs": [{"ResourceId": {"value": "standard.energy"}, "Amount": cost}],
        "Tags": [{"value": "attack"}],
        "Rarity": rarity,
        "Program": {"Id": {"Value": "(unnamed)"}, "Root": root,
                    "MaxNodeDepth": 64, "MaxProgramSteps": 1024},
        "LifecyclePrograms": {},
        "RetainInHandOnTurnEnd": False,
        "TurnEndHandDestinationZone": "DiscardPile",
        "PlayedCardDestinationZone": "DiscardPile",
    }


def rip_and_tear(damage):
    return node(
        "node.dealDamageToRandomTarget",
        TargetSelector=SEL_ALL_ENEMIES,
        Amount=const(damage),
        Times=2,
        IgnoresBlock=False,
        Element=None,
    )


def rampage(base, bonus):
    return node("node.sequence", Children=[
        # 伤害 = 8 + 这份副本已经涨过的量。`card.counter` 读的是**正在结算的那张牌**。
        node(
            "node.dealDamage",
            TargetSelector=SEL_EVENT_TARGET,
            Amount={
                "kind": "add",
                "value": {
                    "Left": const(base),
                    "Right": {"kind": "card.counter", "value": {"CounterId": {"value": RAM_COUNTER}}},
                },
            },
            IgnoresBlock=False,
            Element=None,
        ),
        # 然后才涨 —— 顺序反了就是"这一击已经算上了它自己的加成"。
        node(
            "node.addCardCounter",
            CardExpression={"kind": "cardInstance.resolving", "value": {}},
            OwnerSelector=SEL_SOURCE,
            CounterId={"value": RAM_COUNTER},
            Delta=const(bonus),
        ),
    ])


raw = io.open(CONTENT, encoding='utf-8').read()
data = json.loads(raw)
have = {row['Id'] for row in data['Cards']}
assert not (have & {'rip_and_tear', 'rampage'})

data['Cards'].append(card(
    'rip_and_tear', 'Rip and Tear',
    "Deal 7 damage to a random enemy twice.", 1, 'Uncommon', rip_and_tear(7)))
data['Cards'].append(card(
    'rip_and_tear+', 'Rip and Tear+',
    "Deal 9 damage to a random enemy twice.", 1, 'Uncommon', rip_and_tear(9)))
data['Cards'].append(card(
    'rampage', 'Rampage',
    "Deal 8 damage. Increase this card's damage by 5 this combat.", 1, 'Uncommon', rampage(8, 5)))
data['Cards'].append(card(
    'rampage+', 'Rampage+',
    "Deal 8 damage. Increase this card's damage by 8 this combat.", 1, 'Uncommon', rampage(8, 8)))

out = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
assert out != raw
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(out)

# ── 检查器：认识新节点 + `card.counter` 这种尺寸 ───────────────────────────────
src = io.open(CHECK, encoding='utf-8').read()

old = '''        elif kind == "node.dealDamageToRandomTarget":'''
new = '''        elif kind == "node.addCardCounter":
            # §229: "this card remembers something about itself" as a fact. The counter's **name** and
            # the delta are both part of it -- two cards that raise different counters must not compare
            # equal, or "Rampage got stronger" and "some other bookkeeping moved" would look the same.
            out.append(("cardCounter", body["CardExpression"]["kind"],
                        body["CounterId"]["value"], amount(body["Delta"])))
        elif kind == "node.dealDamageToRandomTarget":'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    if expr.get("kind") == "const":
        return expr["value"]["Value"]'''
new = '''    if expr.get("kind") == "const":
        return expr["value"]["Value"]
    if expr.get("kind") == "card.counter":
        # §229: a size that is **this copy's** counter ("increase this card's damage by 5").
        return ("cardCounter", expr["value"]["CounterId"]["value"])
    if expr.get("kind") == "add":
        return ("add", amount(expr["value"]["Left"]), amount(expr["value"]["Right"]))'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    # ---- §228：随机目标 / 按格挡打伤害 -------------------------------------------------------'''
new = '''    # ---- §229：随机双击（§228 载体的第二个用户）/ 每副本计数器 ------------------------------
    "rip_and_tear": {"Cost": 1, "Tags": ["attack"],
                     "Facts": [("damageRandom", 7, "allEnemies", 2)]},
    "rip_and_tear+": {"Cost": 1, "Tags": ["attack"],
                      "Facts": [("damageRandom", 9, "allEnemies", 2)]},
    # 伤害是 `8 + card.counter`，然后给这份副本加 5(8) —— 两件事都在事实里。
    "rampage": {"Cost": 1, "Tags": ["attack"],
                "Facts": [("damage", ("add", 8, ("cardCounter", "standard.rampage_bonus")), "event"),
                          ("cardCounter", "cardInstance.resolving", "standard.rampage_bonus", 5)]},
    "rampage+": {"Cost": 1, "Tags": ["attack"],
                 "Facts": [("damage", ("add", 8, ("cardCounter", "standard.rampage_bonus")), "event"),
                           ("cardCounter", "cardInstance.resolving", "standard.rampage_bonus", 8)]},
    # ---- §228：随机目标 / 按格挡打伤害 -------------------------------------------------------'''
assert src.count(old) == 1
src = src.replace(old, new)
io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src)

# ── wiki 清单 ────────────────────────────────────────────────────────────────
src = io.open(INV, encoding='utf-8').read()
old = """    # 没有数字的牌：纯关键字/状态牌。"""
new = """    # §229：`Deal (7;9) damage to a random enemy twice.` —— 升级改伤害，次数固定 2。
    'rip_and_tear': ([('damageRandom', 7, 'allEnemies', 2)],
                     [('damageRandom', 9, 'allEnemies', 2)]),
    # §229：`Deal 8 damage. Increase this card's damage by (5;8) this combat.`
    'rampage': ([('damage', ('add', 8, ('cardCounter', 'standard.rampage_bonus')), 'event'),
                 ('cardCounter', 'cardInstance.resolving', 'standard.rampage_bonus', 5)],
                [('damage', ('add', 8, ('cardCounter', 'standard.rampage_bonus')), 'event'),
                 ('cardCounter', 'cardInstance.resolving', 'standard.rampage_bonus', 8)]),
    # 没有数字的牌：纯关键字/状态牌。"""
assert src.count(old) == 1
io.open(INV, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new))
print('ok content')
