"""§264 遗物第五批：**改写别的状态**（3 件）+ 顺手消掉 §262 的一条偏差。

## 三件

| 遗物 | wiki 原话 | 稀有度 | 用哪条基建 |
|---|---|---|---|
| `paper_phrog` | "Enemies with Vulnerable take 75% more damage rather than 50%." | Uncommon | `AppliesToStatusId` 改写易伤的 150 → 175 |
| `paper_krane` | "Enemies with Weak deal 40% less damage rather than 25%." | Rare | 同上，改虚弱的 75 → 60 |
| `champion_belt` | "Whenever you apply Vulnerable, also apply 1 Weak." | Rare | `event.statusIs` |

## 为什么它们是"内容"而不是又一批内核常量

§263 的三件（The Boot / Torii / Tungsten Rod）是内核规则，因为它们的规则说的是
"**未被格挡的**那个数"，而管线在扣格挡之前跑；而且 `(阈值, 替换值)` 是**两个参数**。
这三件不一样：

* `paper_phrog` / `paper_krane` 改的是**另一条状态自己的幅值** —— 一条 spec 说
  "`standard.vulnerable` 在这条管线里按 175 算"。规则（易伤乘 1.5）仍然只写在易伤身上。
* `champion_belt` 要的是"这次施加的是不是易伤"，那是 §264 新加的**事件事实**
  （`event.statusIs`，事件带状态 id）。

## 改写发生在**对面阵营**

`paper_phrog` 的持有者是英雄、易伤挂在**敌人**身上：折叠 `DamageReceived`（敌人的贡献）时，
改写来自**出手方**（英雄）。`paper_krane` 反过来：虚弱挂在**敌人**（出手方）身上，折叠加成
`DamageDealt` 时改写来自**承受方**（英雄）。所以内核的规则是"改写来自对面"，
见 `exec::apply_status_magnitude_overrides` 的注释。

## 顺手：`pen_nib` 的翻倍现在**只对攻击牌**生效

§262 留过一条写明了的偏差：`RestrictSourceCardTag` 解不开，所以 `standard.double_damage` 的
×200 挡不住"由触发器打出的非攻击伤害"。§264 把它解开了 —— 这里补上那个参数，
那条偏差随之消失（`port-plan.md` §262.1 的注已改为"§264 已消掉"）。
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


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def status(definition_id, stacks):
    return n("applyStatus", TargetSelector=sel_source(),
             StatusDefinitionId={"value": definition_id}, Stacks=const(stacks))


def event_status_is(definition_id):
    return {"kind": "event.statusIs",
            "value": {"StatusId": {"value": definition_id}, "ResultKey": None}}


def conditional(condition, then):
    return n("conditional", Condition=condition, Then=then, Else=None)


def buff(definition_id, name, text, triggers, modifiers=None, tags=None):
    return {
        'Id': definition_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': text,
        'Polarity': 'Buff', 'UsesStacks': True, 'UsesDuration': False, 'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': tags or ['buff'],
        'PassiveModifiers': modifiers or [],
        'Triggers': triggers,
    }


def spec(pipeline, operation, magnitude, priority, kind, applies_to=None, card_tag=None):
    return {
        'Pipeline': pipeline,
        'Operation': operation,
        'Magnitude': magnitude,
        'Priority': priority,
        'RestrictDamageKind': kind,
        'AppliesToStatusId': {'value': applies_to} if applies_to else None,
        'RestrictSourceCardTag': {'value': card_tag} if card_tag else None,
    }


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    statuses = {row['Id']: row for row in doc['Statuses']}
    relics = {row['Id']: row for row in doc['Relics']}

    def add_status(row):
        if row['Id'] in statuses:
            statuses[row['Id']].update(row)
        else:
            doc['Statuses'].append(row)
            statuses[row['Id']] = row

    # ---- Paper Phrog：易伤 150 → 175（承受侧、对面改写）
    #
    # 幅值只改**数字**：`ScalePercent` 仍然是易伤自己说的，`Priority` 也仍然按易伤那条走
    # （改写不动排序 —— 否则"谁先乘"会跟着内容偷偷变）。
    add_status(buff(
        'standard.paper_phrog', 'Paper Phrog',
        'Enemies with Vulnerable take 75% more damage rather than 50%.',
        [],
        modifiers=[spec('DamageReceived', 'ScalePercent', 175, 300, 'Direct',
                        applies_to='standard.vulnerable')]))

    # ---- Paper Krane：虚弱 75 → 60（出手侧、对面改写）
    add_status(buff(
        'standard.paper_krane', 'Paper Krane',
        'Enemies with Weak deal 40% less damage rather than 25%.',
        [],
        modifiers=[spec('DamageDealt', 'ScalePercent', 60, 200, 'Direct',
                        applies_to='standard.weak')]))

    # ---- Champion Belt：施加易伤时也给 1 层虚弱
    add_status(buff(
        'standard.champion_belt', 'Champion Belt',
        'Whenever you apply Vulnerable, also apply 1 Weak.',
        [{'Event': 'StatusApplied',
          # ⚠️ 只认**易伤**：`event.bool("status.isDebuff")` 会把所有 debuff 都算进来
          # （那会给"施加任何 debuff 都附带虚弱"），所以这条用的是 `event.statusIs`。
          'Program': program(conditional(
              event_status_is('standard.vulnerable'),
              # 目标 = **被施加的那一方**（`sel.eventTarget`），不是自己。
              n('applyStatus',
                TargetSelector={"kind": "sel.eventTarget",
                                "value": {"Cardinality": "ZeroOrOne",
                                          "RequiredContextCapabilities": "EventTarget"}},
                StatusDefinitionId={"value": "standard.weak"},
                Stacks=const(1))))}]))

    # ---- §264：`double_damage` 补上"只对攻击牌"（消掉 §262 的偏差）
    dd = statuses['standard.double_damage']
    for modifier in dd['PassiveModifiers']:
        modifier['RestrictSourceCardTag'] = {'value': 'attack'}
    print('double_damage: RestrictSourceCardTag -> attack')

    ROWS = [
        ('paper_phrog', 'Paper Phrog', 'Uncommon', 'standard.paper_phrog'),
        ('paper_krane', 'Paper Krane', 'Rare', 'standard.paper_krane'),
        ('champion_belt', 'Champion Belt', 'Rare', 'standard.champion_belt'),
    ]
    for rid, display, rarity, carrier in ROWS:
        relics[rid] = {
            'Id': rid, 'DisplayName': display, 'Rarity': rarity,
            'RunPrograms': None, 'CombatRules': None,
        }
        print('relic %-16s %-9s -> %s' % (rid, rarity, carrier))

    doc['Relics'] = [relics[k] for k in sorted(relics)]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: statuses %d, relics %d' % (len(doc['Statuses']), len(doc['Relics'])))


main()
