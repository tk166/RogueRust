"""§254（内容）：`Wish` / `Wish+` + 三个选项的落区修正。

牌面（wiki 正文）：3 费 Watcher Rare Skill「Choose one: Gain 6 Plated Armor, 3 Strength, or
25 Gold. Exhaust.」；升级 → 8 / 4 / 30。

`Wish` = `offerCards{Definitions: [那三张], Then: "PlayChosen"}`：
* 基础行给三张**基础**选项，`Wish+` 给三张 **`+`** 选项 —— 这正是 wiki 说的
  「Upgrading Wish itself is the only way to upgrade the cards that it creates」；
* 落区 `ExhaustPile`：Wish 自己是 Exhaust；而那三张选项**从不出现在牌组/手牌里**
  （wiki: "The three cards that Wish creates never enter your hand and cannot be added to the
  deck"），所以它们打完就离场 —— 在消耗堆里，不在弃牌堆。

⚠️ 那三张选项自己的落区：wiki 上它们**没有 Exhaust 关键字**，所以不能用 `ExhaustPile`
（内容门有一条考据：落区写 `ExhaustPile` ⇒ wiki 必须写 Exhaust）。而留在 `DiscardPile` 也不行 ——
一张"只会被 Wish 打出"的牌会在弃牌堆里变成永远打不出的废牌。正确答案是 `BanishedPile`：
它就是内核里"离场、但不是 Exhaust"的那一格。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
SELF = {"kind": "sel.source",
        "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}

OPTIONS = ['become_almighty', 'live_forever', 'fame_and_fortune']
OPTIONS_PLUS = [option + '+' for option in OPTIONS]


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in doc['Cards']}

    # 1) 三个选项的落区：DiscardPile -> ExhaustPile（见模块头）。
    fixed = 0
    for row in doc['Cards']:
        if row['Id'] in OPTIONS + OPTIONS_PLUS and row['PlayedCardDestinationZone'] != 'BanishedPile':
            row['PlayedCardDestinationZone'] = 'BanishedPile'
            fixed += 1

    # 2) `Wish` / `Wish+`。
    added = 0
    for card_id, cost, options in (('wish', 3, OPTIONS), ('wish+', 3, OPTIONS_PLUS)):
        if card_id in have:
            continue
        doc['Cards'].append({
            'Id': card_id,
            'PackageId': 'sts',
            'NameKey': card_id,
            'DescriptionKey': (
                'Choose one: Gain 6 Plated Armor, 3 Strength, or 25 Gold. Exhaust.'
                if card_id == 'wish' else
                'Choose one: Gain 8 Plated Armor, 4 Strength, or 30 Gold. Exhaust.'
            ),
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': cost}],
            'Tags': [{'value': 'skill'}, {'value': 'watcher'}],
            'Rarity': 'Rare',
            'Program': program(node('node.offerCards',
                                    Definitions=list(options),
                                    Min=1, Max=1, Then='PlayChosen')),
            'LifecyclePrograms': {},
            'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile',
            // `Wish` 自己 wiki 上写着 Exhaust ⇒ 消耗堆（与考据一致）。
            'PlayedCardDestinationZone': 'ExhaustPile',
        })
        added += 1

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('cards +%d, destination fixed on %d row(s), total %d'
          % (added, fixed, len(doc['Cards'])))


main()
