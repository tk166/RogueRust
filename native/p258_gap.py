"""§258 查漏：A 数据三条 + 虱子一族（红/绿装反了）。

## 一、A 数据的真缺口（`native/audit_asc_gap.py` 抓出来的）

审计脚本把 `native/wiki_asc/*.txt` 的 `{{Asc|N|…}}` 与内容的 `ProgramAsc` 逐条对上，
真正对不上的只有三条（其余 10 条"不一致"是脚本的误报：升档维度长在 `Rolls` 或
写在**别的招式**上，比如 `the_champ` 的 A19 是"Gloat 被 Defensive Stance 顶替"）：

| 招式 | wiki | 我们 | 修法 |
|---|---|---|---|
| `time_eater.head_slam` | A4: 26 → **32**（A19 另加 2 张 Slimed） | 只有 A19，且伤害没变 | 补 A4 档，A19 档也带 32 |
| `slaver_red.scrape` | A17: Vulnerable 1 → **2** | 只有 A2（伤害 9） | 补 A17 档（9 + 2 层） |
| `louse_green.bite` | **5-7（A2: 6-8）随机** | 写死 6 | 改读开局掷的 `roll.bite` |

第三条顺带把整族翻出来：wiki 上 **红虱子 = Bite + Grow，绿虱子 = Bite + Spit Web**，
而内容是**反的**（红虱子身上挂着 Spit Web，绿虱子有 Grow 而没有 Spit Web）。
而且 `louse_green` **没有任何遭遇用它** —— 内容门早就把它记在 `INV_UNWIRED` 里，
那是一条"存在但玩家永远见不到"的死内容。

## 二、虱子这一族的修法

* `louse_red.spit_web` 改名 `louse_green.spit_web`（它本来就是绿虱子的招）；
* `louse_green.grow` 删掉（绿虱子没有 Grow）；
* `louse_green.bite` 改成读 `roll.bite`，与红虱子同一份掷骰（5-7 / A2 6-8）；
* 两只都补 AI（wiki 原话）：
  * 红：25% Grow / 75% Bite；同招不连三次；**A17 起 Grow 不连两次**；
  * 绿：25% Spit Web / 75% Bite；同招不连三次；**A17 起 Spit Web 不连两次**；
* 新增 `enc_two_louses`（红 + 绿，即 wiki 的 "2 Red or Green Louses"）并进 1 幕弱池 ——
  这样绿虱子才真的能被遇到。

⚠️ 写死的 `6` 不只是"少了个随机"：它在 A0 就比红虱子的 5-7 **偏高**、在 A2 又比 6-8 **偏低**，
两个方向都错，而屏幕上只有一个数，看不出来。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def n(kind, **value):
    return {"kind": "node." + kind, "value": value}


def const(v):
    return {"kind": "const", "value": {"Value": v}}


def sel_source():
    return {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def sel_target():
    return {"kind": "sel.eventTarget",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}


def seq(*children):
    return n("sequence", Children=list(children))


def damage(amount, target=None):
    return n("dealDamage", TargetSelector=target or sel_target(), Amount=amount,
             ResultKey=None, IgnoresBlock=False, Element=None)


def status(definition_id, stacks, target=None):
    return n("applyStatus", TargetSelector=target or sel_target(),
             StatusDefinitionId={"value": definition_id}, Stacks=stacks)


def counter_get(counter, target=None):
    return {"kind": "combatantCounter", "value": {"Selector": target or sel_source(),
                                                  "CounterId": counter}}


def counter_set(counter, amount, relative, target=None):
    return n("setCombatantCounter", TargetSelector=target or sel_source(),
             CounterId={"value": counter}, Amount=amount, Relative=relative)


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def bookkeeping(code):
    return [
        counter_set("prev_move", counter_get("last_move"), relative=False),
        counter_set("last_move", const(code), relative=False),
    ]


def no_three_in_a_row(first, second, second_action):
    """`allOf[last==first, prev==first] -> second_action`（同一种招不能连三次）。"""
    return {
        'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': [
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': first}},
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'prev_move'}, 'Op': 'Equal', 'Value': first}}]}},
        'Action': {'value': second_action}, 'Priority': 60,
    }


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    monsters = {row['Id']: row for row in doc['Monsters']}
    actions = {row['Id']: row for row in doc['EnemyActions']}

    # ============================================================ 一、A 数据
    head_slam = actions['time_eater.head_slam']
    base = head_slam['Program']['Root']
    a4 = json.loads(json.dumps(base))
    # 伤害 26 -> 32（A4）；节目里第一个 dealDamage 的常量。
    def set_damage(node, value):
        if isinstance(node, dict):
            if node.get('kind') == 'node.dealDamage':
                node['value']['Amount'] = const(value)
                return True
            for child in node.values():
                if set_damage(child, value):
                    return True
        elif isinstance(node, list):
            for child in node:
                if set_damage(child, value):
                    return True
        return False

    assert set_damage(a4, 32), 'head_slam has a dealDamage'
    a19 = None
    for variant in head_slam.get('ProgramAsc') or []:
        if variant['AscensionMin'] == 19:
            a19 = variant
    assert a19 is not None, 'the A19 variant exists'
    a19_root = json.loads(json.dumps(a19['Program']['Root']))
    assert set_damage(a19_root, 32), 'A19 keeps the A4 damage'
    head_slam['Program'] = program(base)
    head_slam['ProgramAsc'] = [
        {'AscensionMin': 4, 'Program': program(a4)},
        {'AscensionMin': 19, 'Program': program(a19_root)},
    ]
    print('time_eater.head_slam: A4 (26 -> 32), A19 keeps 32 + the Slimed')

    scrape = actions['slaver_red.scrape']
    a2 = None
    for variant in scrape.get('ProgramAsc') or []:
        if variant['AscensionMin'] == 2:
            a2 = variant
    assert a2 is not None
    a17 = json.loads(json.dumps(a2['Program']['Root']))

    def set_stacks(node, definition_id, value):
        if isinstance(node, dict):
            if (node.get('kind') == 'node.applyStatus'
                    and (node.get('value') or {}).get('StatusDefinitionId', {}).get('value')
                    == definition_id):
                node['value']['Stacks'] = const(value)
                return True
            for child in node.values():
                if set_stacks(child, definition_id, value):
                    return True
        elif isinstance(node, list):
            for child in node:
                if set_stacks(child, definition_id, value):
                    return True
        return False

    assert set_stacks(a17, 'standard.vulnerable', 2), 'scrape applies Vulnerable'
    scrape['ProgramAsc'] = [
        {'AscensionMin': 2, 'Program': a2['Program']},
        {'AscensionMin': 17, 'Program': program(a17)},
    ]
    print('slaver_red.scrape: A17 (Vulnerable 1 -> 2, damage stays 9)')

    # ============================================================ 二、虱子一族
    # 绿虱子的招：`louse_red.spit_web` 搬过去（它一直是绿虱子的）。
    spit = actions.pop('louse_red.spit_web')
    spit['Id'] = 'louse_green.spit_web'
    spit['Program'] = program(seq(
        status("standard.weak", const(2)),
        *bookkeeping(2),
    ))
    actions['louse_green.spit_web'] = spit
    if not any(row['Id'] == 'louse_green.spit_web' for row in doc['EnemyActions']):
        doc['EnemyActions'].append(spit)
    else:
        for index, row in enumerate(doc['EnemyActions']):
            if row['Id'] == 'louse_green.spit_web':
                doc['EnemyActions'][index] = spit
    # 绿虱子没有 Grow。
    doc['EnemyActions'] = [row for row in doc['EnemyActions']
                           if row['Id'] != 'louse_green.grow']
    actions.pop('louse_green.grow', None)

    # 绿虱子的 Bite：读开局掷的 `roll.bite`（与红虱子同一份），不再写死 6。
    bite = actions['louse_green.bite']
    bite['Program'] = program(seq(
        damage(counter_get("roll.bite")),
        *bookkeeping(1),
    ))
    # 红虱子的 Bite 只补收尾（它已经读 roll.bite）。
    red_bite = actions['louse_red.bite']
    red_bite['Program'] = program(seq(
        damage(counter_get("roll.bite")),
        *bookkeeping(1),
    ))
    # 红虱子的 Grow 补收尾（A17 档也要）。
    red_grow = actions['louse_red.grow']
    grow_base = red_grow['Program']['Root']
    red_grow['Program'] = program(seq(grow_base, *bookkeeping(2)))
    red_grow['ProgramAsc'] = [
        {'AscensionMin': 17,
         'Program': program(seq(json.loads(json.dumps(
             (red_grow.get('ProgramAsc') or [{'Program': {'Root': grow_base}}])[0]['Program']['Root']
             if red_grow.get('ProgramAsc') else grow_base)),
             *bookkeeping(2)))},
    ]

    # ============================================================ 三、AI（wiki 原话）
    def louse_rules(bite_action, other_action, other_code):
        return [
            # A17：另一招不连两次。
            {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': [
                {'kind': 'intent.ascensionAtLeast', 'value': {'Value': 17}},
                {'kind': 'intent.selfHasCounter',
                 'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal',
                           'Value': other_code}}]}},
             'Action': {'value': bite_action}, 'Priority': 70},
            no_three_in_a_row(1, 1, other_action),
            no_three_in_a_row(other_code, other_code, bite_action),
            # 25% 另一招 / 75% Bite。
            {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': []}},
             'Priority': 10,
             'Choice': [{'Action': {'value': bite_action}, 'Weight': 75},
                        {'Action': {'value': other_action}, 'Weight': 25}]},
        ]

    red = monsters['louse_red']
    red['Actions'] = [{'value': 'louse_red.bite'}, {'value': 'louse_red.grow'}]
    red['IntentRules'] = louse_rules('louse_red.bite', 'louse_red.grow', 2)
    red['AiNote'] = (
        '§258：wiki Red Louse（HP 10-15 / A7 11-16、Bite 5-7 随机 / A2 6-8、Grow 3 / A17 4、'
        'Curl Up 3-7 / A7 4-8 / A17 9-12）。AI：25% Grow / 75% Bite，同招不连三次，'
        'A17 起 Grow 不连两次。⚠️ §258 之前它身上挂着**绿**虱子的 Spit Web。'
    )
    green = monsters['louse_green']
    green['Actions'] = [{'value': 'louse_green.bite'}, {'value': 'louse_green.spit_web'}]
    green['IntentRules'] = louse_rules('louse_green.bite', 'louse_green.spit_web', 2)
    green['AiNote'] = (
        '§258：wiki Green Louse（HP 11-17 / A7 12-18、Bite 5-7 随机 / A2 6-8、Spit Web 2 Weak、'
        'Curl Up 同红虱子）。AI：25% Spit Web / 75% Bite，同招不连三次，'
        'A17 起 Spit Web 不连两次。⚠️ §258 之前它的 Bite 写死 6、招式表里只有 Bite/Grow。'
    )

    # ============================================================ 四、绿虱子要能被遇到
    first = next(row for row in doc['Encounters']
                 if (row['Id']['Value'] if isinstance(row['Id'], dict) else row['Id'])
                 == 'enc_louse')
    red_slot = json.loads(json.dumps(first['Enemies'][0]))
    green_slot = json.loads(json.dumps(red_slot))
    green_slot['Id'] = 'louse_green'
    green_slot['DisplayName'] = 'Green Louse'
    green_slot['MaxHealth'] = 11
    green_slot['Actions'] = [{'value': 'louse_green.bite'},
                             {'value': 'louse_green.spit_web'}]
    green_slot['IntentRules'] = green['IntentRules']
    green_slot['Position'] = 1
    green_slot['MaxHealthAsc'] = [{'AscensionMin': 7, 'MaxHealth': 12}]
    red_slot['Actions'] = red['Actions']
    red_slot['IntentRules'] = red['IntentRules']

    two = {
        'Id': {'Value': 'enc_two_louses'},
        'Enemies': [red_slot, green_slot],
        'HeroResources': json.loads(json.dumps(first.get('HeroResources') or [])),
        'HeroStartingStatuses': [],
        'TriggeredEffects': [],
        'HeroDisplayName': None,
        'CardsDrawnPerTurn': None,
    }
    if not any((row['Id']['Value'] if isinstance(row['Id'], dict) else row['Id'])
               == 'enc_two_louses' for row in doc['Encounters']):
        doc['Encounters'].append(two)
    # `enc_louse` 的槽位也要与名册同步（红虱子只剩两招）。
    first['Enemies'][0]['Actions'] = red['Actions']
    first['Enemies'][0]['IntentRules'] = red['IntentRules']

    weak = doc['EncounterTables']['Weak']
    if not any(row['Id'] == 'enc_two_louses' for row in weak):
        # wiki：1 幕 Easy Pool 里"1 Louse"与"2 Louses"各一条 ⇒ 两条同权。
        weak.insert(4, {'Id': 'enc_two_louses', 'Weight': 14})
    print('encounters: enc_two_louses (red + green) added to the act-1 weak pool')

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: statuses %d, actions %d, encounters %d'
          % (len(doc['Statuses']), len(doc['EnemyActions']), len(doc['Encounters'])))


main()
