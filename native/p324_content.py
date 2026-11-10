"""§324 `augmenter`（Act 2）—— 三个选项，wiki 原文：

| 选项 | 效果 |
|---|---|
| `[Test J.A.X.]` | 牌组加一张 **J.A.X.**（0 费无色特殊技能：失 3 血、+2 力量；`+` 行 +3） |
| `[Become Test Subject]` | **选** 2 张，各**改造**一次（`transform_choose:2`） |
| `[Ingest Mutagens]` | 得 **Mutagenic Strength**（开战 +3 力量；第一回合末失 3 力量） |

⚠️ 旧笔记把这条写成"两张**随机**变形"，那是**错的**：wiki 的更新记录明写
*"Augmenter event transform option now allows choosing 2 cards to Transform instead of
selecting 3 at random"* —— 所以是"选两张"，用的是拾取欠账通道。
"""

import io
import json

PATH = 'tools/contentc/packages/sts/sts.roguedeck.json'


def sel_source():
    return {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne",
                      "RequiredContextCapabilities": "Source"}}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def lose_hp(n):
    return {"kind": "node.loseHp",
            "value": {"TargetSelector": sel_source(), "Amount": const(n), "ResultKey": None}}


def gain_strength(n):
    return {"kind": "node.applyStatus",
            "value": {"TargetSelector": sel_source(),
                      "StatusDefinitionId": {"value": "standard.strength"},
                      "Stacks": const(n), "DurationTurns": 0, "Charges": 0, "ResultKey": None}}


def seq(children):
    return {"kind": "node.sequence", "value": {"Children": children, "ResultKey": None}}


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def jax(card_id, name, strength, description):
    return {
        "Id": card_id,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": description,
        "Costs": [{"ResourceId": {"value": "standard.energy"}, "Amount": 0}],
        "Tags": [{"value": "skill"}, {"value": "colorless"}],
        "Program": program(seq([lose_hp(3), gain_strength(strength)])),
    }


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    ids = {c["Id"] for c in doc["Cards"]}
    assert "jax" not in ids and "augmenter" not in {n["Id"] for n in doc["EventNodes"]}, \
        'already patched'

    cards = [
        jax("jax", "J.A.X.", 2, "Lose 3 HP. Gain 2 Strength."),
        jax("jax+", "J.A.X.+", 3, "Lose 3 HP. Gain 3 Strength."),
    ]

    # 遗物：`Rarity` 是 `Event`（不可掉落，只由事件给）。
    relic = {
        "Id": "mutagenic_strength",
        "NameKey": "Mutagenic Strength",
        "Rarity": "Event",
        "DescriptionKey": ("Start each combat with 3 Strength. At the end of your first turn, "
                           "lose 3 Strength."),
    }

    event = [
        {
            'Id': 'augmenter',
            'TextKey': ('A man with an eyepatch and a devilish grin strides up. "Interested in '
                        'advancing science? I can make you stronger than any training."'),
            'Options': [
                {
                    'Label': 'Test J.A.X.',
                    'Effects': [{'Effect': 'card:jax', 'Amount': 1}],
                    'Next': '',
                },
                {
                    'Label': 'Become Test Subject (transform 2)',
                    # wiki：*"Choose and Transform 2 cards"* —— 选出来的两张各改造一次。
                    'Effects': [{'Effect': 'transform_choose:2', 'Amount': 2}],
                    'Next': '',
                },
                {
                    'Label': 'Ingest Mutagens (relic)',
                    'Effects': [{'Effect': 'relic:mutagenic_strength', 'Amount': 0}],
                    'Next': '',
                },
            ],
        },
    ]

    doc['Cards'].extend(cards)
    doc['Relics'].append(relic)
    doc['EventNodes'].extend(event)
    doc['EventTables']['Events2'].append({'Id': 'augmenter'})
    doc['UnknownRooms'].append({'Id': 'augmenter', 'NameKey': 'Augmenter',
                                'Entry': 'augmenter'})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('cards %d relics %d events %d'
          % (len(doc['Cards']), len(doc['Relics']), len(doc['EventNodes'])))


main()
