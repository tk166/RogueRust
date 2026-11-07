"""§266 遗物第七批：**条件修饰器**（`red_skull`）+ **同侧改写**（`odd_mushroom`）。

| 遗物 | 稀有度 | wiki 原话 | 靠什么 |
|---|---|---|---|
| `red_skull` | Common | "While your HP is at or below 50%, you have 3 additional Strength." | 新键 `PassiveModifiers.Condition`（布尔表达式） |
| `odd_mushroom` | Event | "When Vulnerable, take 25% more attack damage rather than 50%." | 新键 `PassiveModifiers.OverrideScope = Self` |

## `Condition`

一条布尔表达式，为假时那条 spec **整条不生效**。存的是镜像里的**节点句柄**（不是解好的值）：
求值要用**折叠那一刻**的状态 —— `red_skull` 的"HP ≤ 50%"必须随血量立刻改变，而不是在某个
事件时点算一次。

主语是**这条 spec 的持有者**（`sel.source` = 持有者），所以内容写
`compare(multiply(currentHealth 100), LessOrEqual, multiply(maxHealth 50))` 就是 wiki 那句话。

## `OverrideScope`

§264 的改写只来自**对面**（`paper_phrog`："**敌人**有易伤时"）。`odd_mushroom` 反过来：
"**你**有易伤时" —— 它改的是自己身上那条易伤。所以改写需要一个显式的作用面：

* `Other`（缺省，保持 §264 的语义）：改**对手**身上那条状态；
* `Self`：改**自己**身上那条状态。

缺省值选 `Other` 是刻意的：§264 那两件不用改一个字。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def const(v):
    return {"kind": "const", "value": {"Value": v}}


def compare(left, op, right):
    return {"kind": "compare", "value": {"Left": left, "Right": right, "Op": op}}


def multiply(left, right):
    return {"kind": "multiply", "value": {"Left": left, "Right": right}}


def sel_source():
    return {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def health():
    return {"kind": "currentHealth", "value": {"Selector": sel_source()}}


def max_health():
    return {"kind": "maxHealth", "value": {"Selector": sel_source()}}


def spec(pipeline, operation, magnitude, priority, kind,
         applies_to=None, scope=None, condition=None, card_tag=None):
    return {
        'Pipeline': pipeline,
        'Operation': operation,
        'Magnitude': magnitude,
        'Priority': priority,
        'RestrictDamageKind': kind,
        'AppliesToStatusId': {'value': applies_to} if applies_to else None,
        'RestrictSourceCardTag': {'value': card_tag} if card_tag else None,
        # §266 的两个新键。**缺省不写**（`OverrideScope` 缺省 Other、`Condition` 缺省无条件），
        # 这样 §264/§265 那些行一个字都不用改。
        **({'OverrideScope': scope} if scope else {}),
        **({'Condition': condition} if condition else {}),
    }


def buff(definition_id, name, text, triggers, modifiers=None, tags=None):
    return {
        'Id': definition_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': text,
        'Polarity': 'Buff', 'UsesStacks': True, 'UsesDuration': False, 'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': tags or ['buff'],
        'PassiveModifiers': modifiers or [],
        'Triggers': triggers,
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

    # ---- Red Skull：HP ≤ 50% 时 +3 力量
    #
    # 「HP ≤ 50%」写成整数比较（**不用除法**）：`health * 100 <= max_health * 50`。
    # 比例式（`health*100/max`）会在整数除法上截断，两边乘起来没有这个问题。
    add_status(buff(
        'standard.red_skull', 'Red Skull',
        'While your HP is at or below 50%, you have 3 additional Strength.',
        [],
        modifiers=[spec(
            'DamageDealt', 'AddFlat', 3, 100, 'Direct',
            condition=compare(
                multiply(health(), const(100)),
                'LessOrEqual',
                multiply(max_health(), const(50))))]))

    # ---- Odd Mushroom：自己有易伤时只受 125% 而不是 150%
    #
    # `OverrideScope: Self` —— 改的是**自己身上**那条易伤（`paper_phrog` 用缺省的 `Other`）。
    add_status(buff(
        'standard.odd_mushroom', 'Odd Mushroom',
        'When Vulnerable, take 25% more attack damage rather than 50%.',
        [],
        modifiers=[spec(
            'DamageReceived', 'ScalePercent', 125, 300, 'Direct',
            applies_to='standard.vulnerable', scope='Self')]))

    ROWS = [
        ('red_skull', 'Red Skull', 'Common', 'standard.red_skull'),
        ('odd_mushroom', 'Odd Mushroom', 'Event', 'standard.odd_mushroom'),
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
