"""§263 遗物第四批：**敌人死亡时**（2 件）+ **伤害管线上的数值改写**（3 件）。

## 五件与它们各自的接缝

| 遗物 | 规则（wiki 原话） | 稀有度 | 载体 |
|---|---|---|---|
| `gremlin_horn` | "Whenever an enemy dies, gain 1 Energy and draw 1 card." | Uncommon | 内容状态 + 新事件 `FoeDowned` |
| `the_specimen` | "Whenever an enemy dies, transfer any Poison it has to a random enemy." | Rare | **内核规则**（要随机） |
| `the_boot` | "4 or less **unblocked** Attack damage ⇒ 5." | Common | 内核规则（`exec.rs::S6a`） |
| `torii` | "5 or less **unblocked** Attack damage ⇒ 1." | Rare | 内核规则（同上） |
| `tungsten_rod` | "Whenever you would lose HP, lose 1 less." | Rare | 内核规则（同上） |

## 为什么后三件不是 `PassiveModifiers`

那张表跑在**扣格挡之前**（和力量/虚弱同一条管线），而这三条说的都是 *unblocked* 那一半。
第二个理由是**两个参数**（阈值 + 替换值），而一条 spec 只有一个 `Magnitude`。

## 为什么 `the_specimen` 不是内容触发器

它的"随机一个敌人"没有选择器可用：`sel.*` 全是确定性选择器，随机抽取要推进 `random_step`，
那是 `ExecContext` 的可变侧。`random_living_opponent`（Havoc 用的那个）就是因为这个才写成了函数。
⇒ 走 `Buffer` / `DeathPrevention` 的先例：内核认状态 id。

## `FoeDowned` 这个事件名是本内核自己的

参考没有"别人的死"这个事件（`Downed` 的 Bearer 就是倒下的那个）。把它扩成"派给所有人"会让
现有内容改变行为 —— `standard.split` 长在每只史莱姆身上，任何一只死掉都会触发**其它**史莱姆分裂。
所以新开一个名字，只派给**另一个阵营**。
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


def seq(*children):
    return n("sequence", Children=list(children))


def gain_energy(amount):
    return n("gainResource", TargetSelector=sel_source(), ResourceId="standard.energy",
             Amount=const(amount), ResultKey=None)


def draw(count):
    return n("drawCards", TargetSelector=sel_source(), Count=const(count), ResultKey=None)


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


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

    # ---- 敌人死亡：一条 `FoeDowned` 触发器（+1 能量、抽 1 张）
    add_status(buff(
        'standard.gremlin_horn', 'Gremlin Horn',
        'Whenever an enemy dies, gain 1 Energy and draw 1 card.',
        [{'Event': 'FoeDowned',
          'Program': program(seq(gain_energy(1), draw(1)))}]))

    # ---- 另外四件：**没有触发器也没有修饰器**，规则在内核（读的是状态 id 本身）。
    add_status(buff(
        'standard.the_specimen', 'The Specimen',
        'Whenever an enemy dies, transfer any Poison it has to a random enemy.', []))
    add_status(buff(
        'standard.the_boot', 'The Boot',
        'Whenever you would deal 4 or less unblocked Attack damage, increase it to 5.', []))
    add_status(buff(
        'standard.torii', 'Torii',
        'Whenever you would receive 5 or less unblocked Attack damage, reduce it to 1.', []))
    add_status(buff(
        'standard.tungsten_rod', 'Tungsten Rod',
        'Whenever you would lose HP, lose 1 less.', []))

    ROWS = [
        ('gremlin_horn', 'Gremlin Horn', 'Uncommon', 'standard.gremlin_horn'),
        ('the_specimen', 'The Specimen', 'Rare', 'standard.the_specimen'),
        ('the_boot', 'The Boot', 'Common', 'standard.the_boot'),
        ('torii', 'Torii', 'Rare', 'standard.torii'),
        ('tungsten_rod', 'Tungsten Rod', 'Rare', 'standard.tungsten_rod'),
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
