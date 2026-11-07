"""§260 遗物第一批：**战斗开始类**与**回合末/回合初类**（8 件，**零内核改动**）。

## 为什么这批能零内核改动

本仓库已经有两个现成的载体：

1. `RelicEffect::StartCombatStatus(id, stacks)` —— 开战时把一条**内容状态**挂到英雄身上；
2. 内容状态可以有 `TurnStarted` / `TurnEnded` 触发器（`standard.combust` / `standard.mayhem`
   就是英雄侧的样板）。

于是"每回合做一件小事"这类遗物根本不需要新代码：**遗物 = 开战时挂一条带触发器的状态**。
判断条件也够用：`combatantDefensivePool`（当前格挡）、`combatantZoneCount`（手牌数）、
`cardsPlayedLastTurn`（上回合打了几张）、`sel.allEnemies` + `dealDamage`、`gainBlock`、
`drawCards`、`applyStatus`。

## 这批的八件（wiki 原话，数字逐条抄 `relics_data`）

| 遗物 | 稀有度 | 规则 | 载体 |
|---|---|---|---|
| `orichalcum` | Common | 回合末**没有格挡**时给 6 格挡 | `TurnEnded` + `compare(block, 0, Equal)` |
| `mercury_hourglass` | Uncommon | 回合初对**所有敌人**造成 3 伤害 | `TurnStarted` + `sel.allEnemies` |
| `horn_cleat` | Uncommon | **第 2 回合**初给 14 格挡 | 自己数回合（计数器 2） |
| `captain's_wheel` | Rare | **第 3 回合**初给 18 格挡 | 同上（计数器 3） |
| `stone_calendar` | Rare | 第 7 回合**末**对所有敌人 52 伤害 | 计数器 7 |
| `cloak_clasp` | Rare | 回合末按**手牌张数**给格挡 | `combatantZoneCount(hand)` |
| `incense_burner` | Rare | **每 6 回合**给 1 层无形 | 计数器取模 |
| `pocketwatch` | Rare | 上回合打了 **≤3 张**牌 ⇒ 这回合初抽 3 张 | `cardsPlayedLastTurn` |

**"第 N 回合"一律用状态自己的计数器，不用 `turnNumber`**：`turnNumber` 是**整场战斗**的行动者
序号（多敌人战斗里会跳），而 wiki 说的是"**你的**第 N 回合"。计数器 +1 在 `TurnStarted` 上，
是唯一能对上"你的"那个口径的写法。
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


def sel_all_enemies():
    return {"kind": "sel.allEnemies", "value": {}}


def seq(*children):
    return n("sequence", Children=list(children))


def gain_block(amount, target=None):
    return n("gainBlock", TargetSelector=target or sel_source(), Amount=amount, ResultKey=None)


def damage(amount, target=None):
    return n("dealDamage", TargetSelector=target or sel_all_enemies(), Amount=amount,
             ResultKey=None, IgnoresBlock=False, Element=None)


def status(definition_id, stacks, target=None):
    return n("applyStatus", TargetSelector=target or sel_source(),
             StatusDefinitionId={"value": definition_id}, Stacks=stacks)


def draw(count):
    return n("drawCards", Count=const(count), ResultKey=None)


def counter_get(counter):
    return {"kind": "combatantCounter", "value": {"Selector": sel_source(),
                                                  "CounterId": counter}}


def counter_set(counter, amount, relative=True):
    return n("setCombatantCounter", TargetSelector=sel_source(),
             CounterId={"value": counter}, Amount=amount, Relative=relative)


def compare(left, op, right):
    return {"kind": "compare", "value": {"Left": left, "Right": right, "Op": op}}


def add(left, right):
    return {"kind": "add", "value": {"Left": left, "Right": right}}


def remainder(dividend, divisor):
    return {"kind": "remainder", "value": {"Left": dividend, "Right": divisor}}


def conditional(condition, then, otherwise=None):
    return n("conditional", Condition=condition, Then=then, Else=otherwise)


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def buff(definition_id, name, text, triggers):
    return {
        'Id': definition_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': text,
        'Polarity': 'Buff', 'UsesStacks': True, 'UsesDuration': False, 'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance', 'Tags': ['buff'],
        'PassiveModifiers': [], 'Triggers': triggers,
    }


def turn_counter(counter):
    """`TurnStarted` 上把计数器 +1（"这是我第几个回合"）。"""
    return counter_set(counter, const(1), relative=True)


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

    # ---------------------------------------------------------------- 回合末两类
    add_status(buff(
        'standard.orichalcum', 'Orichalcum',
        'If you end your turn without Block, gain 6 Block.',
        [{'Event': 'TurnEnded', 'Program': program(conditional(
            # 判据是"**当前**格挡为 0"，不是"这回合没获得过格挡"——wiki 的写法就是 "without Block"。
            compare({"kind": "combatantDefensivePool",
                     "value": {"Selector": sel_source()}}, 'Equal', const(0)),
            gain_block(const(6))))}]))

    add_status(buff(
        'standard.cloak_clasp', 'Cloak Clasp',
        'At the end of your turn, gain 1 Block for each card in your hand.',
        [{'Event': 'TurnEnded', 'Program': program(gain_block(
            {"kind": "combatantZoneCount",
             "value": {"Selector": sel_source(), "Zone": "Hand"}}))}]))

    add_status(buff(
        'standard.stone_calendar', 'Stone Calendar',
        'At the end of turn 7, deal 52 damage to ALL enemies.',
        [{'Event': 'TurnEnded', 'Program': program(seq(
            turn_counter('stone_calendar_turns'),
            conditional(
                compare(counter_get('stone_calendar_turns'), 'Equal', const(7)),
                damage(const(52))),
        ))}]))

    # ---------------------------------------------------------------- 回合初三类
    add_status(buff(
        'standard.mercury_hourglass', 'Mercury Hourglass',
        'At the start of your turn, deal 3 damage to ALL enemies.',
        [{'Event': 'TurnStarted', 'Program': program(damage(const(3))) }]))

    add_status(buff(
        'standard.horn_cleat', 'Horn Cleat',
        'At the start of your 2nd turn, gain 14 Block.',
        [{'Event': 'TurnStarted', 'Program': program(seq(
            turn_counter('horn_cleat_turns'),
            conditional(
                compare(counter_get('horn_cleat_turns'), 'Equal', const(2)),
                gain_block(const(14))),
        ))}]))

    add_status(buff(
        "standard.captains_wheel", "Captain's Wheel",
        'At the start of your 3rd turn, gain 18 Block.',
        [{'Event': 'TurnStarted', 'Program': program(seq(
            turn_counter('captains_wheel_turns'),
            conditional(
                compare(counter_get('captains_wheel_turns'), 'Equal', const(3)),
                gain_block(const(18))),
        ))}]))

    add_status(buff(
        'standard.incense_burner', 'Incense Burner',
        'Every 6 turns, gain 1 Intangible.',
        [{'Event': 'TurnStarted', 'Program': program(seq(
            turn_counter('incense_burner_turns'),
            conditional(
                compare(remainder(counter_get('incense_burner_turns'), const(6)),
                        'Equal', const(0)),
                status('standard.intangible', const(1))),
        ))}]))

    add_status(buff(
        'standard.pocketwatch', 'Pocketwatch',
        'Whenever you play 3 or less cards during your turn, draw 3 additional cards at the '
        'start of your next turn.',
        [{'Event': 'TurnStarted', 'Program': program(conditional(
            compare({"kind": "cardsPlayedLastTurn", "value": {}}, 'LessOrEqual', const(3)),
            draw(3)))}]))

    # ---------------------------------------------------------------- 八行遗物
    ROWS = [
        ('orichalcum', 'Orichalcum', 'standard.orichalcum'),
        ('mercury_hourglass', 'Mercury Hourglass', 'standard.mercury_hourglass'),
        ('horn_cleat', 'Horn Cleat', 'standard.horn_cleat'),
        ('captains_wheel', "Captain's Wheel", 'standard.captains_wheel'),
        ('stone_calendar', 'Stone Calendar', 'standard.stone_calendar'),
        ('cloak_clasp', 'Cloak Clasp', 'standard.cloak_clasp'),
        ('incense_burner', 'Incense Burner', 'standard.incense_burner'),
        ('pocketwatch', 'Pocketwatch', 'standard.pocketwatch'),
    ]
    # 稀有度照 wiki（`relics_data` 的 Rarity 字段）。
    RARITY = {
        'orichalcum': 'Common',
        'mercury_hourglass': 'Uncommon',
        'horn_cleat': 'Uncommon',
        'captains_wheel': 'Rare',
        'stone_calendar': 'Rare',
        'cloak_clasp': 'Rare',
        'incense_burner': 'Rare',
        'pocketwatch': 'Rare',
    }
    for rid, display, _status in ROWS:
        relics[rid] = {
            'Id': rid, 'DisplayName': display, 'Rarity': RARITY[rid],
            'RunPrograms': None, 'CombatRules': None,
        }
        print('relic %-20s %-9s -> %s' % (rid, RARITY[rid], _status))

    doc['Relics'] = [relics[k] for k in sorted(relics)]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: statuses %d, relics %d' % (len(doc['Statuses']), len(doc['Relics'])))


main()
