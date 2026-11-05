"""§228 (part 2): `Sword Boomerang` / `Body Slam` 两张牌 + 检查器事实。

wiki（`native/wiki_cards/`）：
* `sword_boomerang` 1 费 Common Attack —— "Deal 3 damage to a random enemy (3;4) times."
  （伤害固定 3，**次数** 3/4 —— 所以升级改的是 `Times`，不是 `Amount`）；
* `body_slam` 1 费（`+` 0 费）Common Attack —— "Deal damage equal to your Block."
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'native/sts_content_check.py'
INV = 'native/card_wiki_inventory.py'

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


def card(cid, name, text, cost, rarity, root, **extra):
    row = {
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
    row.update(extra)
    return row


def boomerang(times, text):
    return node(
        "node.dealDamageToRandomTarget",
        TargetSelector=SEL_ALL_ENEMIES,
        Amount={"kind": "const", "value": {"Value": 3}},
        Times=times,
        IgnoresBlock=False,
        Element=None,
    )


def body_slam():
    return node(
        "node.dealDamage",
        TargetSelector=SEL_EVENT_TARGET,
        # "Deal damage equal to your Block" —— 伤害在**派发那一刻**求值，而格挡在这一刻就是玩家的
        # 当前格挡（`dealDamage` 的 `Amount` 就是派发期求出来的，见 exec 的求值顺序）。
        Amount={
            "kind": "combatantDefensivePool",
            "value": {"Selector": SEL_SOURCE, "PoolId": {"value": "standard.block"}},
        },
        IgnoresBlock=False,
        Element=None,
    )


raw = io.open(CONTENT, encoding='utf-8').read()
data = json.loads(raw)
have = {row['Id'] for row in data['Cards']}
assert not (have & {'sword_boomerang', 'body_slam'})

data['Cards'].append(card(
    'sword_boomerang', 'Sword Boomerang',
    "Deal 3 damage to a random enemy 3 times.",
    1, 'Common', boomerang(3, None)))
data['Cards'].append(card(
    'sword_boomerang+', 'Sword Boomerang+',
    "Deal 3 damage to a random enemy 4 times.",
    1, 'Common', boomerang(4, None)))
data['Cards'].append(card(
    'body_slam', 'Body Slam',
    "Deal damage equal to your Block.",
    1, 'Common', body_slam()))
data['Cards'].append(card(
    'body_slam+', 'Body Slam+',
    "Deal damage equal to your Block.",
    0, 'Common', body_slam()))

out = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
assert out != raw
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(out)

# ── 检查器：认识新节点 + 新表达式 ─────────────────────────────────────────────
src = io.open(CHECK, encoding='utf-8').read()

old = '''        elif kind == "node.gainBlock":'''
new = '''        elif kind == "node.dealDamageToRandomTarget":
            # §228: "each hit re-rolls a target" as a fact -- the **count** and the pool are part of
            # it, because "3 hits to random enemies" and "3 hits to all enemies" differ only here.
            out.append(("damageRandom", amount(body["Amount"]), tgt(body["TargetSelector"]),
                        body["Times"]))
        elif kind == "node.gainBlock":'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    if expr.get("kind") == "combatantCounter":'''
new = '''    if expr.get("kind") == "combatantDefensivePool":
        # §228: a size that is a **defensive pool** ("equal to your Block"). Spelled with the pool key
        # *and* the selector, so "your Block" and "their Block" cannot compare equal.
        return ("pool", expr["value"]["PoolId"]["value"], tgt(expr["value"]["Selector"]))
    if expr.get("kind") == "combatantCounter":'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    "nightmare": {"Cost": 3, "Tags": ["skill"],'''
new = '''    # ---- §228：随机目标 / 按格挡打伤害 -------------------------------------------------------
    # 升级改的是**次数**（wiki: "(3;4) times"），不是伤害 —— 所以两行只差最后一个字段。
    "sword_boomerang": {"Cost": 1, "Tags": ["attack"],
                        "Facts": [("damageRandom", 3, "allEnemies", 3)]},
    "sword_boomerang+": {"Cost": 1, "Tags": ["attack"],
                         "Facts": [("damageRandom", 3, "allEnemies", 4)]},
    "body_slam": {"Cost": 1, "Tags": ["attack"],
                  "Facts": [("damage", ("pool", "standard.block", "source"), "event")]},
    "body_slam+": {"Cost": 0, "Tags": ["attack"],
                   "Facts": [("damage", ("pool", "standard.block", "source"), "event")]},
    "nightmare": {"Cost": 3, "Tags": ["skill"],'''
assert src.count(old) == 1
src = src.replace(old, new)
io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src)

# ── wiki 清单 ────────────────────────────────────────────────────────────────
src = io.open(INV, encoding='utf-8').read()
old = """    # 没有数字的牌：纯关键字/状态牌。"""
new = """    # §228：`Deal 3 damage to a random enemy (3;4) times.` —— 升级改次数。
    'sword_boomerang': ([('damageRandom', 3, 'allEnemies', 3)],
                        [('damageRandom', 3, 'allEnemies', 4)]),
    # §228：`Deal damage equal to your Block.` —— `+` 只降费。
    'body_slam': ([('damage', ('pool', 'standard.block', 'source'), 'event')],
                  [('damage', ('pool', 'standard.block', 'source'), 'event')]),
    # 没有数字的牌：纯关键字/状态牌。"""
assert src.count(old) == 1
io.open(INV, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new))
print('ok content')
