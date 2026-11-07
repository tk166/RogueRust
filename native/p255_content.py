"""§255（内容）：`Conjure Blade` / `Conjure Blade+`。

wiki 正文：
* 基础：`Shuffle an Expunger into your draw pile. Exhaust.`
* 升级：`Shuffle an Expunger **with X+1** into your draw pile. Exhaust.`
* 正文补一句关键的：「which deals 9 (15 if upgraded) damage **X (X+1 if Conjure Blade was
  upgraded)** times」⇒ 升级 **Conjure Blade** 加的是"次数 +1"，而 Expunger 自己那 9→15 是
  **它自己的升级**（靠 Master Reality，不是这张牌）。
* 还有一句：「This means it is possible to generate an Expunger that deals damage 0 times.」
  ⇒ X 可以是 0，而 `Expunger` 的 §251 实现正是"计数器缺席 ⇒ 0 次"。

X 费：与 `whirlwind` / `skewer` 同一套（`x_cost` tag + Cost 0）。X 的读法就是 `x.cost`。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
SELF = {"kind": "sel.source",
        "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def x_cost():
    return {"kind": "x.cost", "value": {}}


def add(left, right):
    return {"kind": "add", "value": {"Left": left, "Right": right}}


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def make(x_plus_one):
    """造一张 `Expunger`，把 X 写进**它自己的**每副本计数器。"""
    value = add(x_cost(), const(1)) if x_plus_one else x_cost()
    return node("node.createCardInstance",
                CardDefinitionId={"value": "expunger"},
                ToZone="DrawPile",
                TargetSelector=SELF,
                Count=const(1),
                MarkCounterId="standard.expunger_x",
                MarkValue=value)


CARDS = [
    ('conjure_blade', 'Shuffle an Expunger into your draw pile. Exhaust.', make(False)),
    ('conjure_blade+', 'Shuffle an Expunger with X+1 into your draw pile. Exhaust.',
     make(True)),
]


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in doc['Cards']}
    added = 0
    for card_id, text, root in CARDS:
        if card_id in have:
            continue
        doc['Cards'].append({
            'Id': card_id,
            'PackageId': 'sts',
            'NameKey': card_id,
            'DescriptionKey': text,
            # X 费：与 `whirlwind`/`skewer` 同一套（Cost 0 + `x_cost` tag）。
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': 0}],
            'Tags': [{'value': 'skill'}, {'value': 'x_cost'}, {'value': 'watcher'}],
            'Rarity': 'Rare',
            'Program': program(root),
            'LifecyclePrograms': {},
            'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile',
            # wiki 写明 Exhaust。
            'PlayedCardDestinationZone': 'ExhaustPile',
        })
        added += 1
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('added %d row(s); cards now %d' % (added, len(doc['Cards'])))


main()
