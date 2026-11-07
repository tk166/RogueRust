"""§265 遗物第六批：**改状态施加**（4 件）。

| 遗物 | 稀有度 | wiki 原话 | 靠什么 |
|---|---|---|---|
| `snecko_skull` | Common | "Whenever you apply Poison, apply an additional 1 Poison." | 新管线 `StatusStacks` + `AppliesToStatusId` |
| `ginger` | Rare | "You can no longer become Weakened." | 新管线 `StatusImmunity` + `AppliesToStatusId` |
| `turnip` | Rare | "You can no longer become Frail." | 同上 |
| `twisted_funnel` | Shop | "At the start of each combat, apply 4 Poison to ALL enemies." | 已有 `StartCombatStatusOnEnemies`（零基建） |

## 两条新管线都配 `AppliesToStatusId`

§264 把那个键当"**改写**另一条状态的幅值"用（`paper_phrog`）。这里给它**第二种语义**：
它是**过滤器** —— "这条 spec 是给哪条状态写的"。

* `StatusStacks`：施加某条状态时，把**层数**过一遍折叠（读施加者 = `ctx.source`）；
* `StatusImmunity`：某条状态**不能被施加**（读承受者）。

同一条管线里两种语义不冲突，因为 `image_rows`（伤害那几条）把带 `AppliesToStatusId` 的 spec
**跳过**、交给改写器；而这两条新管线只走 `status_scoped_rows`（把它们当过滤条件）。
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


def status(definition_id, stacks, target=None):
    return n("applyStatus", TargetSelector=target or sel_source(),
             StatusDefinitionId={"value": definition_id}, Stacks=const(stacks))


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

    # ---- Snecko Skull：你施加中毒时 +1 层
    #
    # `AddFlat` 而不是 `AddPerStack`：遗物只有一层，两层也没有意义（它不是"每层 +1"）。
    # `Priority 100` 与力量那条同档 —— 这条管线里只有它一个人，顺序不构成语义。
    add_status(buff(
        'standard.snecko_skull', 'Snecko Skull',
        'Whenever you apply Poison, apply an additional 1 Poison.',
        [],
        modifiers=[spec('StatusStacks', 'AddFlat', 1, 100, None,
                        applies_to='standard.poison')]))

    # ---- Ginger / Turnip：那条状态永远撒不上
    #
    # 这两条 spec 的 `Operation` / `Magnitude` **不参与计算**（判定只问"有没有这条 spec"），
    # 但镜像的行必须有值 ⇒ 写 `AddFlat 0`（最无害的"什么都不加"）。
    add_status(buff(
        'standard.ginger', 'Ginger', 'You can no longer become Weakened.',
        [],
        modifiers=[spec('StatusImmunity', 'AddFlat', 0, 100, None,
                        applies_to='standard.weak')]))
    add_status(buff(
        'standard.turnip', 'Turnip', 'You can no longer become Frail.',
        [],
        modifiers=[spec('StatusImmunity', 'AddFlat', 0, 100, None,
                        applies_to='standard.frail')]))

    ROWS = [
        ('snecko_skull', 'Snecko Skull', 'Common', ('status', 'standard.snecko_skull', 1)),
        ('ginger', 'Ginger', 'Rare', ('status', 'standard.ginger', 1)),
        ('turnip', 'Turnip', 'Rare', ('status', 'standard.turnip', 1)),
        # `twisted_funnel` 不需要载体状态：开战给**所有敌人** 4 层中毒（`StartCombatStatusOnEnemies`）。
        ('twisted_funnel', 'Twisted Funnel', 'Shop', ('enemies', 'standard.poison', 4)),
    ]
    for rid, display, rarity, carrier in ROWS:
        relics[rid] = {
            'Id': rid, 'DisplayName': display, 'Rarity': rarity,
            'RunPrograms': None, 'CombatRules': None,
        }
        print('relic %-16s %-9s %s' % (rid, rarity, carrier))

    doc['Relics'] = [relics[k] for k in sorted(relics)]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: statuses %d, relics %d' % (len(doc['Statuses']), len(doc['Relics'])))


main()
