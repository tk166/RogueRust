"""§256 敌人侧：把 5 个精英的**语义**校对一遍（它们其实都在，缺的是细节）。

## 先说结论

FACT 里那条"精英只有 4 个遭遇，缺 `Lagavulin` / `Book of Stabbing` / `Slavers` / `Nemesis` /
`Reptomancer`"**已经过期**：五个 encounter 都在内容里、招式也都接上了
（`Elite` / `Elite2` / `Elite3` 三张表齐全）。所以这一节的活是**校对数字与机制**，
不是补骨架。核对 wiki 之后真正不对的是三处：

| # | 问题 | 修法 |
|---|---|---|
| 1 | `enc_slavers` 的 `blue_slaver` 挂着 **`standard.time_warp`** —— 那是**时间吞噬者**的能力，蓝皮强盗不该有 | 删掉 |
| 2 | `Book of Stabbing` 缺 **Painful Stabs**（"每当它造成未被格挡的伤害，往你的弃牌堆塞一张 Wound"） | 新状态 `standard.painful_stabs` + 挂在它的起始状态上 |
| 3 | `Lagavulin` 缺 **Stunned**（醒来后那一回合什么都不做） | 新 EACT `lagavulin.stunned`（空节目）+ 一条 `intent.round == 4` 的规则 |

`Painful Stabs` 之所以能**零内核改动**做出来：`DamageDealt` 事件的 bearer 是**出手方**、
`eventTarget` 是**承受者**、`eventAmount` 是**实际掉血**（= 未被格挡的部分）—— 三要素齐了，
所以整条规则就是"条件 + 造一张牌"。

## 已知仍未做的（写下来，别假装做了）

* `Lagavulin` 的"**受伤就提前醒**"与 A8/A18 的招式数值；
* `Nemesis` 的 AI 约束（"Tri Burn / Scythe 不连续两次"）；
* `Reptomancer` 的"最多 4 把匕首"与 A18 一次召 2 把；
* `Book of Stabbing` 的 A3+/A18+ 数值（7×N、24）；
* `Blue Slaver` 的 A17"不连续 Rake"。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CATALOG = 'D:/Vibe/sts-tui/kernel/rd-core/src/status_catalog.rs'

SELF = {"kind": "sel.source",
        "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
EVENT_TARGET = {"kind": "sel.eventTarget",
                "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def status(definition_id, name, text, triggers):
    return {
        "Id": definition_id, "PackageId": "sts", "NameKey": name, "DescriptionKey": text,
        "Polarity": "Buff", "UsesStacks": True, "UsesDuration": False, "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance", "Tags": ["buff"],
        "PassiveModifiers": [], "Triggers": triggers,
    }


# `Painful Stabs`：`DamageDealt`（bearer = 出手方）→ 如果实际掉血 > 0 ⇒ 往**承受者**的弃牌堆塞 Wound。
PAINFUL_STABS = status(
    'standard.painful_stabs', 'Painful Stabs',
    'Whenever this enemy deals unblocked damage, shuffle a Wound into your discard pile.',
    [{
        'Event': 'DamageDealt',
        'Program': program(node(
            'node.conditional',
            Condition={
                "kind": "compare",
                "value": {"Left": {"kind": "eventAmount", "value": {}},
                          "Right": const(0), "Op": "Greater"},
            },
            Then=node('node.createCardInstance',
                      CardDefinitionId={"value": "wound"},
                      ToZone="DiscardPile",
                      TargetSelector=EVENT_TARGET,
                      Count=const(1)),
            Else=None)),
    }])

# `Lagavulin` 醒来那一回合：什么都不做（StS 的 `Stunned`）。
STUNNED_ACTION = {
    'Id': 'lagavulin.stunned',
    'Program': program(node('node.sequence', Children=[])),
}


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())

    # 1) 新状态
    have = {row['Id'] for row in doc['Statuses']}
    if PAINFUL_STABS['Id'] not in have:
        doc['Statuses'].append(PAINFUL_STABS)

    # 2) 新敌人动作
    have_actions = {row['Id'] for row in doc['EnemyActions']}
    if STUNNED_ACTION['Id'] not in have_actions:
        doc['EnemyActions'].append(STUNNED_ACTION)

    # 3) 三个 encounter 的修正
    encounters = doc['Encounters']
    for encounter in encounters:
        encounter_id = encounter['Id']['Value'] if isinstance(encounter.get('Id'), dict) else encounter['Id']
        if encounter_id == 'enc_slavers':
            for enemy in encounter['Enemies']:
                if enemy['Id'] == 'blue_slaver':
                    # `standard.time_warp` 是**时间吞噬者**的能力；蓝皮强盗不该有它。
                    before = len(enemy.get('StartingStatuses') or [])
                    enemy['StartingStatuses'] = [
                        s for s in (enemy.get('StartingStatuses') or [])
                        if s['StatusDefinitionId']['value'] != 'standard.time_warp'
                    ]
                    print('enc_slavers/blue_slaver: dropped %d status(es)'
                          % (before - len(enemy['StartingStatuses'])))
        if encounter_id == 'enc_book_of_stabbing':
            for enemy in encounter['Enemies']:
                if enemy['Id'] != 'book_of_stabbing':
                    continue
                statuses = enemy.get('StartingStatuses') or []
                if not any(s['StatusDefinitionId']['value'] == 'standard.painful_stabs'
                           for s in statuses):
                    statuses.append({
                        'StatusDefinitionId': {'value': 'standard.painful_stabs'},
                        'Stacks': 1,
                    })
                    enemy['StartingStatuses'] = statuses
                    print('enc_book_of_stabbing: Painful Stabs attached')
        if encounter_id == 'enc_lagavulin':
            for enemy in encounter['Enemies']:
                if enemy['Id'] != 'lagavulin':
                    continue
                actions = [a['value'] for a in (enemy.get('Actions') or [])]
                if 'lagavulin.stunned' not in actions:
                    enemy['Actions'].append({'value': 'lagavulin.stunned'})
                rules = enemy.get('IntentRules') or []
                # 睡 3 回合（已有 `round <= 3`），**第 4 回合醒来时眩晕**。
                # 优先级 10 与 sleep 那条相同 —— 两条条件互斥（`<= 3` vs `== 4`），不会同时命中。
                if not any((r.get('Action') or {}).get('value') == 'lagavulin.stunned' for r in rules):
                    rules.append({
                        'Condition': {"kind": "intent.round",
                                      "value": {"Op": "Equal", "Round": 4}},
                        'Action': {'value': 'lagavulin.stunned'},
                        'Priority': 10,
                    })
                    enemy['IntentRules'] = rules
                    print('enc_lagavulin: Stunned on round 4')

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: statuses %d, enemy_actions %d'
          % (len(doc['Statuses']), len(doc['EnemyActions'])))

    # 4) 内核的状态目录要认识这个新 id（`the_status_catalogue_is_honest` 会查）。
    src = io.open(CATALOG, encoding='utf-8').read()
    if '"standard.painful_stabs"' not in src:
        anchor = '''            | "standard.stun"
            | "standard.artifact"'''
        assert src.count(anchor) == 1, src.count(anchor)
        src = src.replace(anchor, '''            | "standard.stun"
            | "standard.artifact"
            // §256: `Painful Stabs`（Book of Stabbing）—— 纯触发器状态，规则全在内容里。
            | "standard.painful_stabs"''')
        io.open(CATALOG, 'w', encoding='utf-8', newline='\n').write(src)
        print('status_catalog: painful_stabs registered')


main()
