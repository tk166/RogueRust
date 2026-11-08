"""§299 C 类：`enchiridion` / `orange_pellets` / `dead_branch`（三件**内容程序**）。

## 三件的规则各是什么

| 遗物 | 触发器 | 程序 |
|---|---|---|
| `enchiridion` | `TurnStarted`（首回合，计数器门） | `createRandomCardInstance{Tag: power, ToZone: Hand, CostZero: true}` |
| `orange_pellets` | `CardPlayed` | 三个计数器各按牌的种类 +1；三个都 ≥1 ⇒ +3 力量、+3 敏捷，然后清零 |
| `dead_branch` | `CardExhausted` | `createRandomCardInstance{Tag: *, ToZone: Hand}` |

## `dead_branch` 需要内核的**一个小扩展**：通配 tag `*`

`createRandomCardInstance` 的池子是**按 tag 过滤**的（`in_random_pool`），而"任意牌"
没有这样的 tag —— 一张牌要么 attack / skill / power，要么都不是。所以给 `in_random_pool`
加一条：tag 是 `"*"` ⇒ 不过滤（`+` 行与 `x_cost` 仍然排除，那两条是池子的**规矩**）。

⚠️ **已知偏差**：wiki 的 Dead Branch 是"**你的职业牌池**"里随机一张，而通配会带进
**无色牌**（本内容有 51 张）。内容没有"ironclad"这样的 tag，而"不是 colorless"这种否定
语法内核不支持 —— 记在 `docs/sts-wiki-gap.md` F.19，不假装没发生。

## 另外三件为什么**没有**做

| 遗物 | 缺什么 | 具体缺在哪 |
|---|---|---|
| `nilrys_codex` | `offerRandomCards` 的收尾**写死**成"进手牌且免费"（`ChoiceThen::ToHandFree`） | 需要这个节点支持 `Then` 字段（或一个新的 `offerRandomCardsToZone`） |
| `warped_tongs` | 没有"手牌里**随机**一张"的选择器 | `upgradeCards` 按牌区顺序取前 N 张；`sel.random` 只针对**战斗员** |
| `mummified_hand` | 没有内容原子写 `standard.card_cost_override` | 只有 `createRandomCardInstance{CostZero}` 与内核的 `playTopCardOfDrawPile` 会写它 |

这三件不是"抄一条程序"能解决的，所以这一节只做上面三件 —— 剩下的写进 F.19。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
GATE = 'D:/Vibe/sts-tui/native/sts_content_check.py'
RUNSTATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CATALOG = 'D:/Vibe/sts-tui/kernel/rd-core/src/status_catalog.rs'


def sel_source():
    return {'kind': 'sel.source',
            'value': {'Cardinality': 'ZeroOrOne',
                      'RequiredContextCapabilities': 'Source'}}


def const(value):
    return {'kind': 'const', 'value': {'Value': value}}


def counter(counter_id):
    return {'kind': 'combatantCounter',
            'value': {'Selector': sel_source(), 'CounterId': counter_id}}


def compare(left, right, op='Equal'):
    return {'kind': 'compare', 'value': {'Left': left, 'Right': right, 'Op': op}}


def has_tag(tag):
    return {'kind': 'event.bool', 'value': {'FieldKey': 'card.hasTag.' + tag}}


def and_(left, right):
    return {'kind': 'and', 'value': {'Left': left, 'Right': right}}


def bump(counter_id):
    return {'kind': 'node.setCombatantCounter',
            'value': {'TargetSelector': sel_source(),
                      'CounterId': {'value': counter_id},
                      'Amount': const(1), 'Relative': True}}


def reset(counter_id):
    return {'kind': 'node.setCombatantCounter',
            'value': {'TargetSelector': sel_source(),
                      'CounterId': {'value': counter_id},
                      'Amount': const(0), 'Relative': False}}


def conditional(condition, then, otherwise=None):
    return {'kind': 'node.conditional',
            'value': {'Condition': condition, 'Then': then, 'Else': otherwise}}


def sequence(children):
    return {'kind': 'node.sequence', 'value': {'Children': children}}


def apply_status(status_id, stacks):
    return {'kind': 'node.applyStatus',
            'value': {'TargetSelector': sel_source(),
                      'StatusDefinitionId': {'value': status_id},
                      'Stacks': const(stacks),
                      'Duration': None,
                      'ResultKey': None}}


def create_random_card(tag, zone, cost_zero):
    return {'kind': 'node.createRandomCardInstance',
            'value': {'Tag': tag, 'ToZone': zone, 'Count': const(1),
                      'CostZero': cost_zero, 'ResultKey': None}}


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


def enchiridion():
    # 首回合：`TurnStarted` + 计数器 == 0（抄 `standard.lantern` 的门），然后 +1。
    first_turn = conditional(
        compare(counter('enchiridion_turns'), const(0)),
        create_random_card('power', 'Hand', True),
    )
    return status('standard.enchiridion', 'Enchiridion',
                  'At the start of each combat, add a random Power card into your hand. '
                  'It costs 0 this turn.',
                  program(sequence([first_turn, bump('enchiridion_turns')]), 'TurnStarted'))


def orange_pellets():
    power = conditional(has_tag('power'), bump('orange_pellets_power'))
    attack = conditional(has_tag('attack'), bump('orange_pellets_attack'))
    skill = conditional(has_tag('skill'), bump('orange_pellets_skill'))
    ready = and_(
        and_(compare(counter('orange_pellets_power'), const(1), 'GreaterOrEqual'),
             compare(counter('orange_pellets_attack'), const(1), 'GreaterOrEqual')),
        compare(counter('orange_pellets_skill'), const(1), 'GreaterOrEqual'),
    )
    pay = sequence([
        # wiki: "apply 3 Strength, Focus, and Dexterity" —— 本角色没有 Focus（那是 Defect 的），
        # 所以是力量 + 敏捷两项。这条偏差写进 gap 的 F.19。
        apply_status('standard.strength', 3),
        apply_status('standard.dexterity', 3),
        reset('orange_pellets_power'),
        reset('orange_pellets_attack'),
        reset('orange_pellets_skill'),
    ])
    return status('standard.orange_pellets', 'Orange Pellets',
                  'Whenever you play a Power, Attack, and Skill in the same turn, '
                  'gain 3 Strength and 3 Dexterity.',
                  program(sequence([power, attack, skill, conditional(ready, pay)]),
                          'CardPlayed'))


def dead_branch():
    return status('standard.dead_branch', 'Dead Branch',
                  'Whenever you Exhaust a card, add a random card to your hand.',
                  program(create_random_card('*', 'Hand', False), 'CardExhausted'))


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    have = {row['Id'] for row in doc['Statuses']}
    for row in (enchiridion(), orange_pellets(), dead_branch()):
        if row['Id'] in have:
            continue
        doc['Statuses'].append(row)
    relics = {row['Id'] for row in doc['Relics']}
    for rid, name, rarity in (
        ('enchiridion', 'Enchiridion', 'Event'),
        ('orange_pellets', 'Orange Pellets', 'Shop'),
        ('dead_branch', 'Dead Branch', 'Rare'),
    ):
        if rid in relics:
            continue
        doc['Relics'].append({'Id': rid, 'DisplayName': name, 'RunPrograms': None,
                              'CombatRules': None, 'Rarity': rarity})
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('statuses', len(doc['Statuses']), 'relics', len(doc['Relics']))

    # 内核：`in_random_pool` 的通配 tag
    s = io.open(EXEC, encoding='utf-8').read()
    old = '''    if content.card_has_tag(definition, tag.as_str()) != Some(true) {
        return false;
    }'''
    new = '''    // §299：`*` = **任意基础牌**（`dead_branch` 的"a random card"）。
    //
    // 需要这一条的理由：`createRandomCardInstance` 的池子按 tag 过滤，而"任意牌"没有这样的
    // tag —— 一张牌要么 attack / skill / power，要么都不是。`*` 只跳过**这一道**门；
    // 上面"`+` 行不进池"与下面"`x_cost` 不进池"两条是池子的规矩，通配**不**越过它们。
    if tag.as_str() != "*"
        && content.card_has_tag(definition, tag.as_str()) != Some(true)
    {
        return false;
    }'''
    assert s.count(old) == 1
    io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))
    print('wildcard tag')

    # rd-run 表项
    s = io.open(RUNSTATE, encoding='utf-8').read()
    old2 = '''            "blue_candle" => Some(RelicEffect::StartCombatStatus("standard.blue_candle", 1)),'''
    new2 = '''            "blue_candle" => Some(RelicEffect::StartCombatStatus("standard.blue_candle", 1)),
            // §299：C 类三件 —— 规则**全在内容程序**里（触发器 + 原子），内核只认状态。
            "enchiridion" => Some(RelicEffect::StartCombatStatus("standard.enchiridion", 1)),
            "orange_pellets" => {
                Some(RelicEffect::StartCombatStatus("standard.orange_pellets", 1))
            }
            "dead_branch" => Some(RelicEffect::StartCombatStatus("standard.dead_branch", 1)),'''
    assert s.count(old2) == 1
    io.open(RUNSTATE, 'w', encoding='utf-8', newline='\n').write(s.replace(old2, new2))

    # has_behaviour
    s = io.open(CATALOG, encoding='utf-8').read()
    old3 = '''            | "standard.blue_candle"'''
    new3 = '''            | "standard.blue_candle"
            // §299: C 类三件 —— 行为全在内容触发器里。
            | "standard.enchiridion"
            | "standard.orange_pellets"
            | "standard.dead_branch"'''
    assert s.count(old3) == 1
    io.open(CATALOG, 'w', encoding='utf-8', newline='\n').write(s.replace(old3, new3))

    # 内容门
    g = io.open(GATE, encoding='utf-8').read()
    g = g.replace('''    # §298: +3 (`magic_flower` / `medical_kit` / `blue_candle`).
    "statuses": 139,''', '''    # §298: +3 (`magic_flower` / `medical_kit` / `blue_candle`)。
    # §299: +3 (C 类三件 —— 行为全在内容程序里).
    "statuses": 142,''')
    g = g.replace('''    # §298：三件都**没有**被动修饰器 —— 前两件的规则在内核，第三件在触发器里。
    "standard.magic_flower": [],
    "standard.medical_kit": [],
    "standard.blue_candle": [],''', '''    # §298：三件都**没有**被动修饰器 —— 前两件的规则在内核，第三件在触发器里。
    "standard.magic_flower": [],
    "standard.medical_kit": [],
    "standard.blue_candle": [],
    # §299：C 类三件都没有被动修饰器（规则在触发器里）。
    "standard.enchiridion": [],
    "standard.orange_pellets": [],
    "standard.dead_branch": [],''')
    g = g.replace('''                     "standard.blue_candle"):''',
                  '''                     "standard.blue_candle",
                     "standard.enchiridion", "standard.orange_pellets",
                     "standard.dead_branch"):''')
    g = g.replace('''                        "standard.blue_candle": ["CardPlayed"]}[sid]''',
                  '''                        "standard.blue_candle": ["CardPlayed"],
                        # §299
                        "standard.enchiridion": ["TurnStarted"],
                        "standard.orange_pellets": ["CardPlayed"],
                        "standard.dead_branch": ["CardExhausted"]}[sid]''')
    g = g.replace('''                      "magic_flower", "medical_kit", "blue_candle",''',
                  '''                      "magic_flower", "medical_kit", "blue_candle",
                      # §299：C 类三件（纯内容程序）。
                      "enchiridion", "orange_pellets", "dead_branch",''')
    io.open(GATE, 'w', encoding='utf-8', newline='\n').write(g)
    print('wired')


main()
