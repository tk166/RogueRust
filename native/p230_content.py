"""§230 (part 2): `Flex` / `Limit Break` / `Perfected Strike` + `Inflame+` 的文字修正。

检索结论（先查再写）：
* `inflame` / `inflame+` **已经存在**，而且**程序是对的**（2 / 3 层力量）。撒谎的是 `inflame+` 的
  `DescriptionKey`（写着 "Gain 2 Strength."）—— 玩家看到的牌面信息是错的，这一节顺手改掉。
* `Flex`：`standard.lose_strength` 这条状态本来就在（回合末扣掉等于层数的力量并自摘），所以
  "临时力量"= 加力量 + 挂那个状态，**内核一行没加**。
* `Limit Break`：翻倍 = 把"当前层数"当增量再加一次（`Delta` 本来就是表达式）；基础版**自消耗**、
  `+` 版不消耗（wiki: `Double your Strength.(<br>Exhaust.;)` —— 括号里是「基础;升级」）。
* `Perfected Strike`：用 §230 的新节点。
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
SEL_EVENT_TARGET = {
    "kind": "sel.eventTarget",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"},
}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def status(name, stacks):
    return node("node.applyStatus", TargetSelector=SEL_SOURCE,
                StatusDefinitionId={"value": name}, Stacks=const(stacks),
                DurationTurns=0, Charges=0)


def card(cid, name, text, cost, rarity, tags, root, played_zone):
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
        "TurnEndHandDestinationZone": "DiscardPile",
        "PlayedCardDestinationZone": played_zone,
    }


def flex(amount):
    # 先加力量，再挂"回合末扣掉同样多"—— 两条请求的顺序就是结算顺序。
    return node("node.sequence", Children=[
        status("standard.strength", amount),
        status("standard.lose_strength", amount),
    ])


def limit_break():
    # 翻倍 = 增量取"当前层数"。`combatantStatusStacks` 读的就是**此刻**的层数，
    # 而 `modifyStatusStacks` 的 `Delta` 是表达式 ⇒ 12 层会变成 24 层。
    return node("node.modifyStatusStacks", TargetSelector=SEL_SOURCE,
                StatusDefinitionId={"value": "standard.strength"},
                Delta={"kind": "combatantStatusStacks",
                       "value": {"Selector": SEL_SOURCE,
                                 "StatusId": {"value": "standard.strength"}}})


def perfected(base, bonus):
    return node("node.dealDamageWithTagBonus", TargetSelector=SEL_EVENT_TARGET,
                Amount=const(base), Bonus=const(bonus), Tag="strike",
                IgnoresBlock=False, Element=None)


raw = io.open(CONTENT, encoding='utf-8').read()
data = json.loads(raw)
have = {row['Id'] for row in data['Cards']}
assert not (have & {'flex', 'limit_break', 'perfected_strike'})

data['Cards'].append(card(
    'flex', 'Flex', "Gain 2 Strength. At the end of this turn, lose 2 Strength.",
    0, 'Common', ['skill'], flex(2), 'DiscardPile'))
data['Cards'].append(card(
    'flex+', 'Flex+', "Gain 4 Strength. At the end of this turn, lose 4 Strength.",
    0, 'Common', ['skill'], flex(4), 'DiscardPile'))
data['Cards'].append(card(
    'limit_break', 'Limit Break', "Double your Strength. Exhaust.",
    1, 'Rare', ['skill'], limit_break(), 'ExhaustPile'))
data['Cards'].append(card(
    'limit_break+', 'Limit Break+', "Double your Strength.",
    1, 'Rare', ['skill'], limit_break(), 'DiscardPile'))
data['Cards'].append(card(
    'perfected_strike', 'Perfected Strike',
    'Deal 6 damage. Deals 2 additional damage for ALL your cards containing "Strike".',
    # 它自己的名字里就有 "Strike" ⇒ StS 会把它自己也数进去（wiki: "also of itself"）。
    2, 'Common', ['attack', 'strike'], perfected(6, 2), 'DiscardPile'))
data['Cards'].append(card(
    'perfected_strike+', 'Perfected Strike+',
    'Deal 6 damage. Deals 3 additional damage for ALL your cards containing "Strike".',
    2, 'Common', ['attack', 'strike'], perfected(6, 3), 'DiscardPile'))

# `inflame+` 的文字修正（程序本来是 3 层，写的是 2 层）
for row in data['Cards']:
    if row['Id'] == 'inflame+':
        assert row['DescriptionKey'] == 'Gain 2 Strength.', row['DescriptionKey']
        row['DescriptionKey'] = 'Gain 3 Strength.'

out = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
assert out != raw
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(out)

# ── 检查器 ───────────────────────────────────────────────────────────────────
src = io.open(CHECK, encoding='utf-8').read()

old = '''        elif kind == "node.addCardCounter":'''
new = '''        elif kind == "node.dealDamageWithTagBonus":
            # §230: "6 damage, +2 per card with this tag" as one fact. The tag and the per-card bonus
            # are both part of it -- that is the whole identity of Perfected Strike.
            out.append(("damagePerTag", amount(body["Amount"]), amount(body["Bonus"]),
                        body["Tag"], tgt(body["TargetSelector"])))
        elif kind == "node.addCardCounter":'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    # ---- §229：可无限升级（内容把行写够） ---------------------------------------------------'''
new = '''    # ---- §230：临时力量 / 力量翻倍 / 按 tag 数牌加伤 ------------------------------------------
    # `Flex`：加 2(4) 层力量，**同时**挂 2(4) 层 `standard.lose_strength`（回合末扣掉并自摘）。
    "flex": {"Cost": 0, "Tags": ["skill"],
             "Facts": [("status", "standard.strength", 2, "source"),
                       ("status", "standard.lose_strength", 2, "source")]},
    "flex+": {"Cost": 0, "Tags": ["skill"],
              "Facts": [("status", "standard.strength", 4, "source"),
                        ("status", "standard.lose_strength", 4, "source")]},
    # `Limit Break`：增量 = 当前层数 ⇒ 翻倍。基础版**自消耗**，`+` 版不消耗（wiki 的括号是
    # 「基础;升级」：`Double your Strength.(<br>Exhaust.;)`）。
    "limit_break": {"Cost": 1, "Tags": ["skill"],
                    "Facts": [("modify", "standard.strength", ("expr", "combatantStatusStacks"),
                               "source")],
                    "PlayedCardDestinationZone": "ExhaustPile"},
    "limit_break+": {"Cost": 1, "Tags": ["skill"],
                     "Facts": [("modify", "standard.strength", ("expr", "combatantStatusStacks"),
                                "source")],
                     "PlayedCardDestinationZone": "DiscardPile"},
    # `Perfected Strike`：6 + 2(3) × 手牌+抽牌堆+弃牌堆里带 `strike` tag 的牌数。
    "perfected_strike": {"Cost": 2, "Tags": ["attack"],
                         "Facts": [("damagePerTag", 6, 2, "strike", "event")]},
    "perfected_strike+": {"Cost": 2, "Tags": ["attack"],
                          "Facts": [("damagePerTag", 6, 3, "strike", "event")]},
    # ---- §229：可无限升级（内容把行写够） ---------------------------------------------------'''
assert src.count(old) == 1
src = src.replace(old, new)
io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src)

# ── wiki 清单 ────────────────────────────────────────────────────────────────
src = io.open(INV, encoding='utf-8').read()
old = """    # 没有数字的牌：纯关键字/状态牌。"""
new = """    # §230：`Gain (2;4) Strength. At the end of this turn, lose (2;4) Strength.`
    'flex': ([('status', 'standard.strength', 2, 'source'),
              ('status', 'standard.lose_strength', 2, 'source')],
             [('status', 'standard.strength', 4, 'source'),
              ('status', 'standard.lose_strength', 4, 'source')]),
    # §230：`Double your Strength.`（基础版 Exhaust，`+` 不消耗 —— 升级**去掉** Exhaust）
    'limit_break': ([('modify', 'standard.strength', ('expr', 'combatantStatusStacks'), 'source')],
                    [('modify', 'standard.strength', ('expr', 'combatantStatusStacks'), 'source')]),
    # §230：`Deal 6 damage. Deals (2;3) additional damage for ALL your cards containing "Strike".`
    'perfected_strike': ([('damagePerTag', 6, 2, 'strike', 'event')],
                         [('damagePerTag', 6, 3, 'strike', 'event')]),
    # 没有数字的牌：纯关键字/状态牌。"""
assert src.count(old) == 1
io.open(INV, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new))
print('ok content')
