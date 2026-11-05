"""§232 (part 1): `Skewer` / `Malaise` —— 两张 **X 费**牌，载体全部已有。

检索结论：
* `skewer` / `malaise` / `entrench` 都不在内容里；
* `Skewer` = `Whirlwind` 的单体版（`repeat{Count: x.cost}` + `dealDamage`），**内核零改动**；
* `Malaise` = `modifyStatusStacks(strength, Delta = 0 - x.cost)` + `applyStatus(weak, x.cost)`
  （负**增量**是合法的：`-99` 一直被用来摘状态；被禁止的是 `applyStatus` 的**负层数**）；
* `Entrench`（"Double your Block"）**没有载体**：内核只有 `GainBlock`（加法），没有"把防御池设成
  某个值"的节点 —— 而 `combatantDefensivePool`（§228）已经能读出当前值。所以它还差一个
  `node.setDefensivePool`，留成下一节第一件事（不在这一节里凑一个半成品）。
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'native/sts_content_check.py'
INV = 'native/card_wiki_inventory.py'

SEL_EVENT_TARGET = {
    "kind": "sel.eventTarget",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"},
}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def card(cid, name, text, tags, root, played_zone):
    return {
        "Id": cid,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": text,
        # X 费：`Costs` 写 0，`x_cost` tag 让内核按"付出全部能量"结算（§146）。
        "Costs": [{"ResourceId": {"value": "standard.energy"}, "Amount": 0}],
        "Tags": [{"value": tag} for tag in tags],
        "Rarity": "Uncommon",
        "Program": {"Id": {"Value": "(unnamed)"}, "Root": root,
                    "MaxNodeDepth": 64, "MaxProgramSteps": 1024},
        "LifecyclePrograms": {},
        "RetainInHandOnTurnEnd": False,
        "TurnEndHandDestinationZone": "DiscardPile",
        "PlayedCardDestinationZone": played_zone,
    }


def skewer(damage):
    return node("node.repeat", Count={"kind": "x.cost", "value": {}},
                Body=node("node.dealDamage", TargetSelector=SEL_EVENT_TARGET,
                          Amount=const(damage), IgnoresBlock=False, Element=None),
                MaxCount=32)


def malaise():
    return node("node.sequence", Children=[
        # 敌人失去 X 层力量：**减量**是合法的（`-99` 一直被用来摘状态）。
        node("node.modifyStatusStacks", TargetSelector=SEL_EVENT_TARGET,
             StatusDefinitionId={"value": "standard.strength"},
             Delta={"kind": "subtract", "value": {"Left": const(0), "Right": {"kind": "x.cost", "value": {}}}}),
        node("node.applyStatus", TargetSelector=SEL_EVENT_TARGET,
             StatusDefinitionId={"value": "standard.weak"},
             Stacks={"kind": "x.cost", "value": {}}, DurationTurns=0, Charges=0),
    ])


raw = io.open(CONTENT, encoding='utf-8').read()
data = json.loads(raw)
have = {row['Id'] for row in data['Cards']}
assert not (have & {'skewer', 'malaise'})

data['Cards'].append(card(
    'skewer', 'Skewer', "Deal 7 damage X times.", ['attack', 'x_cost'], skewer(7), 'DiscardPile'))
data['Cards'].append(card(
    'skewer+', 'Skewer+', "Deal 10 damage X times.", ['attack', 'x_cost'], skewer(10), 'DiscardPile'))
data['Cards'].append(card(
    'malaise', 'Malaise', "Enemy loses X Strength and gains X Weak. Exhaust.",
    ['skill', 'x_cost'], malaise(), 'ExhaustPile'))
data['Cards'].append(card(
    'malaise+', 'Malaise+', "Enemy loses X Strength and gains X Weak. Exhaust.",
    ['skill', 'x_cost'], malaise(), 'ExhaustPile'))

out = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
assert out != raw
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(out)

# ── 检查器 + wiki 清单 ──────────────────────────────────────────────────────
src = io.open(CHECK, encoding='utf-8').read()
old = '''    # ---- §231：True Grit（格挡 + 随机消耗一张）/ Reaper（打全体 + 按掉血回血） -----------------'''
new = '''    # ---- §232：两张 X 费牌（载体全在：`repeat` + `x.cost`） -----------------------------------
    "skewer": {"Cost": 0, "Tags": ["attack", "x_cost"],
               "Facts": [("repeat", ("expr", "x.cost"),
                          ("damage", 7, "event"))]},
    "skewer+": {"Cost": 0, "Tags": ["attack", "x_cost"],
                "Facts": [("repeat", ("expr", "x.cost"),
                           ("damage", 10, "event"))]},
    "malaise": {"Cost": 0, "Tags": ["skill", "x_cost"],
                "Facts": [("modify", "standard.strength", ("expr", "subtract"), "event"),
                          ("status", "standard.weak", ("expr", "x.cost"), "event")],
                "PlayedCardDestinationZone": "ExhaustPile"},
    "malaise+": {"Cost": 0, "Tags": ["skill", "x_cost"],
                 "Facts": [("modify", "standard.strength", ("expr", "subtract"), "event"),
                           ("status", "standard.weak", ("expr", "x.cost"), "event")],
                 "PlayedCardDestinationZone": "ExhaustPile"},
    # ---- §231：True Grit（格挡 + 随机消耗一张）/ Reaper（打全体 + 按掉血回血） -----------------'''
assert src.count(old) == 1
io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new))

src = io.open(INV, encoding='utf-8').read()
old = """    # 没有数字的牌：纯关键字/状态牌。"""
new = """    # §232：`Deal (7;10) damage X times.`（X 费）
    'skewer': ([('repeat', ('expr', 'x.cost'), ('damage', 7, 'event'))],
               [('repeat', ('expr', 'x.cost'), ('damage', 10, 'event'))]),
    # §232：`Enemy loses X Strength and gains X Weak. Exhaust.`（`+` 只降费 —— 两行事实相同）
    'malaise': ([('modify', 'standard.strength', ('expr', 'subtract'), 'event'),
                 ('status', 'standard.weak', ('expr', 'x.cost'), 'event')],
                [('modify', 'standard.strength', ('expr', 'subtract'), 'event'),
                 ('status', 'standard.weak', ('expr', 'x.cost'), 'event')]),
    # 没有数字的牌：纯关键字/状态牌。"""
assert src.count(old) == 1
io.open(INV, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new))
print('ok content')
