"""§300 内容：`nilrys_codex` / `warped_tongs` / `mummified_hand`（各用一个新原子）。

| 遗物 | 原子 | 程序要点 |
|---|---|---|
| `nilrys_codex` | `offerRandomCards{Then: ToDrawPileTop}` | `TurnEnded` → 三选一 → 进抽牌堆顶 |
| `warped_tongs` | `upgradeCards{Random: true}` | `TurnStarted` → 手牌随机一张原地升级 |
| `mummified_hand` | `setCardCostOverride{Random: true}` | `CardPlayed`（牌带 `power`）→ 手牌随机一张变 0 费 |

⚠️ 两条已记录的偏差写进 gap F.20：
1. `nilrys_codex`：wiki 是"**洗入**抽牌堆"，而牌区只有 Top/Bottom 两个插入点 ⇒ 用**顶**
   （含义是"下一张就抽它"）；
2. `mummified_hand`：0 费写在那**一份副本**上、由出牌消费（与 §161.4 的 `ToHandFree`
   同一条已记录偏差），而不是"回合结束过期"。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def sel_source():
    return {'kind': 'sel.source',
            'value': {'Cardinality': 'ZeroOrOne',
                      'RequiredContextCapabilities': 'Source'}}


def const(v):
    return {'kind': 'const', 'value': {'Value': v}}


def counter(c):
    return {'kind': 'combatantCounter',
            'value': {'Selector': sel_source(), 'CounterId': c}}


def compare(l, r, op='Equal'):
    return {'kind': 'compare', 'value': {'Left': l, 'Right': r, 'Op': op}}


def has_tag(tag):
    return {'kind': 'event.bool', 'value': {'FieldKey': 'card.hasTag.' + tag}}


def bump(c):
    return {'kind': 'node.setCombatantCounter',
            'value': {'TargetSelector': sel_source(), 'CounterId': {'value': c},
                      'Amount': const(1), 'Relative': True}}


def conditional(condition, then, otherwise=None):
    return {'kind': 'node.conditional',
            'value': {'Condition': condition, 'Then': then, 'Else': otherwise}}


def sequence(children):
    return {'kind': 'node.sequence', 'value': {'Children': children}}


def program(root, event):
    return [{'Event': event,
             'Program': {'Id': {'Value': '(unnamed)'}, 'Root': root}}]


def status(status_id, name, description, triggers):
    return {
        'Id': status_id,
        'PackageId': 'sts',
        'NameKey': name,
        'DescriptionKey': description,
        'Polarity': 'Buff',
        'UsesStacks': True,
        'UsesDuration': False,
        'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': ['buff'],
        'PassiveModifiers': [],
        'Triggers': triggers,
    }


def nilrys_codex():
    # "At the end of each turn, you may shuffle 1 of 3 random cards into your draw pile."
    # `offerRandomCards` 自带"三选一"的问句；`Then: ToDrawPileTop` 决定看完之后把它放哪。
    offer = {'kind': 'node.offerRandomCards',
             'value': {'Count': const(3), 'Min': 0, 'Max': 1,
                       'Then': 'ToDrawPileTop'}}
    return status('standard.nilrys_codex', "Nilry's Codex",
                  'At the end of each turn, you may shuffle 1 of 3 random cards into your '
                  'draw pile.',
                  program(offer, 'TurnEnded'))


def warped_tongs():
    # "At the start of your turn, Upgrade a random card in your hand for the rest of combat."
    #
    # ⚠️ `Random: true` 是新原子。没有它的话 `upgradeCards` 取的是**牌区顺序的前一张**
    # （`Armaments` 的老行为）—— 玩家会看到"永远升级第一张"。
    upgrade = {'kind': 'node.upgradeCards',
               'value': {'OwnerSelector': sel_source(), 'FromZone': 'Hand',
                         'Count': 1, 'Random': True}}
    return status('standard.warped_tongs', 'Warped Tongs',
                  'At the start of your turn, Upgrade a random card in your hand for the rest '
                  'of combat.',
                  program(upgrade, 'TurnStarted'))


def mummified_hand():
    # "Whenever you play a Power card, a random card in your hand costs 0 that turn."
    free = {'kind': 'node.setCardCostOverride',
            'value': {'OwnerSelector': sel_source(), 'FromZone': 'Hand',
                      'Count': 1, 'Random': True, 'Amount': const(0)}}
    return status('standard.mummified_hand', 'Mummified Hand',
                  'Whenever you play a Power card, a random card in your hand costs 0 that turn.',
                  program(conditional(has_tag('power'), free), 'CardPlayed'))


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    have = {row['Id'] for row in doc['Statuses']}
    for row in (nilrys_codex(), warped_tongs(), mummified_hand()):
        if row['Id'] in have:
            continue
        doc['Statuses'].append(row)
    relics = {row['Id'] for row in doc['Relics']}
    for rid, name, rarity in (
        ('nilrys_codex', "Nilry's Codex", 'Event'),
        ('warped_tongs', 'Warped Tongs', 'Event'),
        ('mummified_hand', 'Mummified Hand', 'Uncommon'),
    ):
        if rid in relics:
            continue
        doc['Relics'].append({'Id': rid, 'DisplayName': name, 'RunPrograms': None,
                              'CombatRules': None, 'Rarity': rarity})
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('statuses', len(doc['Statuses']), 'relics', len(doc['Relics']))


main()
