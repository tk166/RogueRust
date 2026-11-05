"""§231 (part 2): `True Grit` / `Reaper` + **修** `Battle Trance`。

检索结论：
* `battle_trance` / `battle_trance+` **已存在**（抽 3/4），但它第二半挂的是
  `standard.draw_reduction` —— 那条状态的语义是"**下回合**起手少抽 1 张"（`Pipeline: TurnStartDraw`
  + `TurnEnded` 衰减），而 wiki 说的是 "You cannot draw additional cards **this turn**"。两处都错
  （时机错、幅度错），这一节修：挂 `standard.no_draw`，内核在 `draw_cards_node` 里认它。
* `true_grit` / `reaper` 缺。
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'native/sts_content_check.py'
INV = 'native/card_wiki_inventory.py'

NO_DRAW = "standard.no_draw"

SEL_SOURCE = {
    "kind": "sel.source",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"},
}
SEL_ALL_ENEMIES = {
    "kind": "sel.allEnemies",
    "value": {"Cardinality": "Many", "RequiredContextCapabilities": "Source"},
}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def card(cid, name, text, cost, rarity, tags, root, played_zone, turn_end="DiscardPile"):
    return {
        "Id": cid,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": text,
        "Costs": [{"ResourceId": {"value": "standard.energy"}, "Amount": cost}],
        "Tags": [{"value": tag} for tag in tags],
        "Rarity": rarity,
        "Program": {"Id": {"Value": "(unnamed)"}, "Root": root,
                    "MaxNodeDepth": 64, "MaxProgramSteps": 1024},
        "LifecyclePrograms": {},
        "RetainInHandOnTurnEnd": False,
        "TurnEndHandDestinationZone": turn_end,
        "PlayedCardDestinationZone": played_zone,
    }


def block(amount):
    return node("node.gainBlock", TargetSelector=SEL_SOURCE, Amount=const(amount),
                PoolId={"value": "standard.block"})


def exhaust_random_one():
    # "Exhaust a random card in your hand" == §195.4 的 `selectCards`（内核挑，按 Random 序）。
    return node("node.selectCards", OwnerSelector=SEL_SOURCE, FromZone="Hand",
                Order="Random", Count=1, ToZone="ExhaustPile", Placement="Bottom")


def true_grit(amount):
    return node("node.sequence", Children=[block(amount), exhaust_random_one()])


def reaper(damage):
    return node("node.dealDamageAndHealByLoss", TargetSelector=SEL_ALL_ENEMIES,
                Amount=const(damage), IgnoresBlock=False, Element=None)


raw = io.open(CONTENT, encoding='utf-8').read()
data = json.loads(raw)
have = {row['Id'] for row in data['Cards']}
assert not (have & {'true_grit', 'reaper'})

data['Cards'].append(card(
    'true_grit', 'True Grit', "Gain 7 Block. Exhaust a random card in your hand.",
    1, 'Common', ['skill'], true_grit(7), 'ExhaustPile'))
data['Cards'].append(card(
    'true_grit+', 'True Grit+', "Gain 9 Block. Exhaust a random card in your hand.",
    1, 'Common', ['skill'], true_grit(9), 'ExhaustPile'))
data['Cards'].append(card(
    'reaper', 'Reaper', "Deal 4 damage to ALL enemies. Heal unblocked damage dealt.",
    2, 'Rare', ['attack'], reaper(4), 'ExhaustPile'))
data['Cards'].append(card(
    'reaper+', 'Reaper+', "Deal 5 damage to ALL enemies. Heal unblocked damage dealt.",
    2, 'Rare', ['attack'], reaper(5), 'ExhaustPile'))

# ── 修 `Battle Trance`：把"下回合少抽 1 张"换成"本回合不能再抽" ─────────────────
fixed = 0
for row in data['Cards']:
    if not row['Id'].startswith('battle_trance'):
        continue
    children = row['Program']['Root']['value']['Children']
    status = children[1]
    assert status['value']['StatusDefinitionId']['value'] == 'standard.draw_reduction'
    status['value']['StatusDefinitionId']['value'] = NO_DRAW
    fixed += 1
assert fixed == 2, fixed

# `standard.no_draw`：回合末自摘（内容触发器），所以它只活**这个**回合。
STATUS = {
    "Id": NO_DRAW,
    "PackageId": "sts",
    "NameKey": "No Draw",
    "DescriptionKey": "You cannot draw additional cards this turn.",
    "Polarity": "Debuff",
    "UsesStacks": True,
    "UsesDuration": False,
    "UsesCharges": False,
    "StackingBehavior": "MergeWithExistingInstance",
    "Tags": ["debuff"],
    "PassiveModifiers": [],
    "Triggers": [{
        "Event": "TurnEnded",
        "Program": {
            "Id": {"Value": "(unnamed)"},
            "Root": node("node.modifyStatusStacks", TargetSelector=SEL_SOURCE,
                         StatusDefinitionId={"value": NO_DRAW}, Delta=const(-99)),
            "MaxNodeDepth": 64,
            "MaxProgramSteps": 1024,
        },
    }],
}
assert NO_DRAW not in {s['Id'] for s in data['Statuses']}
data['Statuses'].append(STATUS)

out = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
assert out != raw
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(out)

# ── 检查器 ───────────────────────────────────────────────────────────────────
src = io.open(CHECK, encoding='utf-8').read()

old = '''        elif kind == "node.dealDamageWithTagBonus":'''
new = '''        elif kind == "node.dealDamageAndHealByLoss":
            # §231: "heal what you actually dealt" -- the `HealByLoss` half is part of the fact, or
            # "4 damage to all" and "4 damage to all, healing what it dealt" would compare equal.
            out.append(("damageHealLoss", amount(body["Amount"]), tgt(body["TargetSelector"])))
        elif kind == "node.dealDamageWithTagBonus":'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    # ---- §230：临时力量 / 力量翻倍 / 按 tag 数牌加伤 ------------------------------------------'''
new = '''    # ---- §231：True Grit（格挡 + 随机消耗一张）/ Reaper（打全体 + 按掉血回血） -----------------
    # `True Grit`：数值只有格挡那一半；"随机消耗一张手牌"是 §195.4 的 `selectCards` 事实。
    "true_grit": {"Cost": 1, "Tags": ["skill"],
                  "Facts": [("block", 7, "source"),
                            ("select", "source", "Hand", None, "Random", 1, "ExhaustPile")],
                  "PlayedCardDestinationZone": "ExhaustPile"},
    "true_grit+": {"Cost": 1, "Tags": ["skill"],
                   "Facts": [("block", 9, "source"),
                             ("select", "source", "Hand", None, "Random", 1, "ExhaustPile")],
                   "PlayedCardDestinationZone": "ExhaustPile"},
    "reaper": {"Cost": 2, "Tags": ["attack"],
               "Facts": [("damageHealLoss", 4, "allEnemies")],
               "PlayedCardDestinationZone": "ExhaustPile"},
    "reaper+": {"Cost": 2, "Tags": ["attack"],
                "Facts": [("damageHealLoss", 5, "allEnemies")],
                "PlayedCardDestinationZone": "ExhaustPile"},
    # ---- §230：临时力量 / 力量翻倍 / 按 tag 数牌加伤 ------------------------------------------'''
assert src.count(old) == 1
src = src.replace(old, new)

# `battle_trance` 的事实里那条状态改了 id；状态总数的清单也要 +1
src = src.replace('"standard.draw_reduction", 1, "source"', '"standard.no_draw", 1, "source"')
old = '''    # §227: +1 (`standard.nightmare_pending`, Nightmare 的"下一回合"载体).
    "statuses": 45,'''
new = '''    # §227: +1 (`standard.nightmare_pending`, Nightmare 的"下一回合"载体).
    # §231: +1 (`standard.no_draw`, Battle Trance 的"本回合不能再抽").
    "statuses": 46,'''
assert src.count(old) == 1
src = src.replace(old, new)
io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src)

# ── wiki 清单 ────────────────────────────────────────────────────────────────
src = io.open(INV, encoding='utf-8').read()
old = """    # 没有数字的牌：纯关键字/状态牌。"""
new = """    # §231：`Gain (7;9) Block. Exhaust a random card in your hand.`
    'true_grit': ([('block', 7, 'source'),
                   ('select', 'source', 'Hand', None, 'Random', 1, 'ExhaustPile')],
                  [('block', 9, 'source'),
                   ('select', 'source', 'Hand', None, 'Random', 1, 'ExhaustPile')]),
    # §231：`Deal (4;5) damage to ALL enemies. Heal unblocked damage dealt.`
    'reaper': ([('damageHealLoss', 4, 'allEnemies')],
               [('damageHealLoss', 5, 'allEnemies')]),
    # 没有数字的牌：纯关键字/状态牌。"""
assert src.count(old) == 1
io.open(INV, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new))
print('ok content')
