"""§250：把内容门的四件套补上（**一次写完**，避免逐行编辑把条目切坏）。

四件事：
1. `program_facts` 认识四个新节点（`dealDamageAndIfFatal` / `gainGold` / `createCardCopy` /
   `offerRandomCards`）—— 它是**穷尽**走查，不认识就 `AssertionError`（那是它的职责）；
2. `CARD_LIFECYCLE_EVENTS` 加上 `CardPlayedInHand`（`pain`）；
3. `_tuples` 归一化：`INV_CARDS` 的字面量是 `list[list]`，`program_facts` 给 `list[tuple]`；
4. `INV_CARDS` 的 18 行 + 卡数 267。

⚠️ 第 4 步**必须在第 1 步之后**：facts 要用新的 `program_facts` 算出来，不能手抄。
"""
import io
import json
import re
import sys

ROOT = 'D:/Vibe/sts-tui/'
CHECK = ROOT + 'native/sts_content_check.py'

NEW_KINDS = '''        elif kind == "node.dealDamageAndIfFatal":
            # §250: "deal N damage, and if that killed, do X". The fatal branch is a **sub-program**,
            # so its facts are tagged `fatal` -- "deal 15 and grow" vs "deal 15" must never compare
            # equal (that is exactly the Ritual Dagger / Hand of Greed shape).
            before = len(facts)
            walk(body["Program"])
            fatal_facts = facts[before:]
            del facts[before:]
            if body.get("IgnoresBlock"):
                out.append(("damageIgnoresBlock", tgt(body["TargetSelector"]),
                            amount(body["Amount"])))
            else:
                out.append(("damage", amount(body["Amount"]), tgt(body["TargetSelector"])))
            facts.extend(("fatal",) + f for f in fatal_facts)
        elif kind == "node.gainGold":
            # §250: gold **inside** a fight (`Hand of Greed`). A fact of its own: the run's gold is
            # not a combat resource, so it must not be folded into `gain`.
            out.append(("gold", amount(body["Amount"])))
        elif kind == "node.createCardCopy":
            # §250: "a copy of **this** card" (Pride / Necronomicurse). `CardDefinitionId` is part of
            # the fact because it is the **only** thing that decides *which* card is copied --
            # leaving it out lets two different cards read as the same content (§250's first gate).
            out.append(("copySelf", body.get("CardDefinitionId"), body["ToZone"],
                        body.get("Placement", "Bottom"), body.get("Count", 1)))
        elif kind == "node.offerRandomCards":
            # §250: "offer N of the class pool, pick one, it arrives free" (`Discovery`). The `then`
            # is fixed by the node (`ToHandFree`), so it is spelled out in the fact -- a second
            # consumer with a different `then` would have to change this line too.
            out.append(("offer", body.get("Count", 3), body.get("Min", 1),
                        body.get("Max", 1), "ToHandFree"))
'''

TUPLES_HELPER = '''def _tuples(value):
    """把 `INV_CARDS` 的字面量转成 `program_facts` 的**形状**：`list[tuple]`。

    `program_facts` 返回 `[('damage', 2, 'source')]`（外层 list、内层 tuple），而字面量写成了
    `[['damage', 2, 'source']]`。两者打印出来几乎一样，但 `list != tuple` —— 不统一就会让每一条
    生命周期节目都报"事实不符"，而那看起来像内容错（§250 第一版就是这么红的）。
    """
    if not isinstance(value, list):
        return value
    out = []
    for item in value:
        if isinstance(item, list):
            out.append(tuple(_deep_tuple(sub) for sub in item))
        else:
            out.append(item)
    return out


def _deep_tuple(value):
    """嵌套的 list 一律变 tuple（`('loseHp', ['expr', ...], ...)` 那种内层）。"""
    if isinstance(value, list):
        return tuple(_deep_tuple(item) for item in value)
    return value


'''


def literal(value):
    """一层 list of facts → **Python** 源码字面量（交给 `_tuples` 归一化）。

    用 `json.dumps` 再换三个 JSON 字面量：`true/false/null` 在 Python 里不存在，直接抄进去就是
    `NameError`（§250 第一版踩过）。字符串里含 `true` 之类也不会被误换 —— 引号内的部分
    由 `repr` 保证原样（这里的事实只有数字/布尔/字符串 id，没有那个风险，但仍然显式写明）。
    """
    return (json.dumps(value, ensure_ascii=False)
            .replace('true', 'True')
            .replace('false', 'False')
            .replace('null', 'None'))


def main():
    src = io.open(CHECK, encoding='utf-8').read()
    assert '"ritual_dagger": {"Cost"' not in src, 'already patched'

    # 1) program_facts：四个新 kind
    anchor = '        elif kind == "node.repeat":'
    assert src.count(anchor) == 1
    src = src.replace(anchor, NEW_KINDS + anchor)

    # 2) 生命周期事件表
    old_events = 'CARD_LIFECYCLE_EVENTS = ("TurnEndInHand", "Drawn", "Exhausted")'
    new_events = ('CARD_LIFECYCLE_EVENTS = ("TurnEndInHand", "Drawn", "Exhausted",\n'
                  '                         # §250：`pain` —— "这张牌在手上、别人打出牌时"。\n'
                  '                         "CardPlayedInHand")')
    assert src.count(old_events) == 1
    src = src.replace(old_events, new_events)

    # 3) `_tuples` 助手 + 两处比较归一化
    anchor_check = 'def check_card_lifecycle(doc):'
    assert src.count(anchor_check) == 1
    src = src.replace(anchor_check, TUPLES_HELPER + anchor_check)

    old_cmp = '        if got != spec["Facts"]:'
    assert src.count(old_cmp) == 1
    src = src.replace(old_cmp, '        if got != _tuples(spec["Facts"]):')

    old_life = '''            facts = program_facts(programs[key]["Root"])
            if facts != expected[key]:'''
    assert src.count(old_life) == 1
    src = src.replace(old_life, '''            facts = program_facts(programs[key]["Root"])
            if facts != _tuples(expected[key]):''')

    # 4) 卡数
    src = src.replace('    "cards": 249,', '    # §250: +18 rows.\n    "cards": 267,')

    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src)
    print('checker: kinds + events + _tuples + count patched')

    # 5) 用**新的** program_facts 算 facts，再写 INV_CARDS
    sys.path.insert(0, ROOT + 'native')
    for name in [m for m in list(sys.modules) if m == 'sts_content_check']:
        del sys.modules[name]
    import sts_content_check as C

    doc = json.loads(io.open(ROOT + 'tools/contentc/packages/sts/sts.roguedeck.json',
                             encoding='utf-8').read())
    cards = {row['Id']: row for row in doc['Cards']}
    ids = ['ritual_dagger', 'ritual_dagger+', 'hand_of_greed', 'hand_of_greed+',
           'discovery', 'discovery+', 'forethought', 'forethought+',
           'clumsy', 'curse_of_the_bell', 'decay', 'necronomicurse', 'normality',
           'pain', 'parasite', 'pride', 'regret', 'shame']
    block = ['    # ---- §250：B/C/D/F 四组（14 张牌 / 18 行）-----------------------------']
    for cid in ids:
        row = cards[cid]
        facts = C.program_facts(row['Program']['Root'])
        parts = ['    "%s": {"Cost": %d' % (cid, row['Costs'][0]['Amount']),
                 '"Tags": %s' % json.dumps([t['value'] for t in row['Tags']]),
                 '"Facts": %s' % literal(facts)]
        life = row.get('LifecyclePrograms') or {}
        if life:
            mapping = {key: literal(C.program_facts(value['Root']))
                       for key, value in life.items()}
            parts.append('"Lifecycle": {%s}' % ', '.join(
                '%s: %s' % (json.dumps(key), text) for key, text in mapping.items()))
        block.append('%s},' % ', '.join(parts))
    src = io.open(CHECK, encoding='utf-8').read()
    anchor_inv = 'INV_CARDS = {\n'
    assert src.count(anchor_inv) == 1
    src = src.replace(anchor_inv, anchor_inv + '\n'.join(block) + '\n', 1)
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src)
    print('INV_CARDS: %d rows written' % len(ids))


main()
