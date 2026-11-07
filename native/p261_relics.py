"""§261 遗物第二批：**战斗开始类**（5 件）。

这批的三种机制各不相同，正好覆盖三条不同的接缝：

| 遗物 | 规则 | 载体 |
|---|---|---|
| `lantern` | 每场战斗**第 1 回合** +1 能量 | 内容状态 + `TurnStarted`（判断在自增**之前**） |
| `bag_of_preparation` | 开战多抽 2 张 | 同上（`drawCards` 在 turn-start 的抽牌**之前**跑） |
| `ice_cream` | 能量跨回合**保留** | 内容状态 + **标签** `unspent_energy_carries`（内核读） |
| `calipers` | 回合开始只失去 **15** 点格挡 | 内容状态 + 标签 `block_loss_cap`，**层数 = 15** |
| `du_vu_doll` | 每张**诅咒** +1 力量 | `CombatBonus::per_curse_statuses`（层数由内容数出来） |

## 为什么 `lantern` / `bag_of_preparation` 能零内核改动

`turn.rs` 文件头那张表是**规格**：补能量(#2) → 触发器(#4/#5) → 抽牌(#6) → 清格挡(#7)。
于是"第 1 回合多 1 点能量"和"开战多抽 2 张"都只是**触发器在正确的位置上做了正确的事**：

* `lantern` 在触发器里 `gainResource(energy, 1)` —— 那时补能量已经发生，所以是 3+1=4；
* `bag_of_preparation` 在触发器里 `drawCards(2)` —— 那时抽 5 还没发生，最终手牌 7 张。

⚠️ 两条都**依赖那个顺序**。如果有人把触发器挪到抽牌之后，`bag_of_preparation` 会从
"手牌 7"变成"手牌 7"（等价），但 `lantern` 会变成"4 点里被补能量覆盖成 3"——
所以判据必须**读能量数**，不能只读"手牌够不够"。

## 为什么"第 1 回合"要自己数，而不是读 `turnNumber`

与 §260 同一个理由：`turnNumber` 是整场战斗的**行动者序号**（多敌人战斗里会跳）。
状态自己的计数器 +1 才等于"你的第 N 回合"。⚠️ 而且 `setCombatantCounter` 是**入队**效果，
同一节目里读不到刚写的值 ⇒ 判断写在自增**之前**，判据是"读到 0"（§260 踩过）。
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


def counter_get(counter):
    return {"kind": "combatantCounter", "value": {"Selector": sel_source(),
                                                  "CounterId": counter}}


def counter_bump(counter):
    return n("setCombatantCounter", TargetSelector=sel_source(),
             CounterId={"value": counter}, Amount=const(1), Relative=True)


def compare(left, op, right):
    return {"kind": "compare", "value": {"Left": left, "Right": right, "Op": op}}


def conditional(condition, then):
    return n("conditional", Condition=condition, Then=then, Else=None)


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def gain_energy(amount):
    return n("gainResource", TargetSelector=sel_source(), ResourceId="standard.energy",
             Amount=const(amount), ResultKey=None)


def draw(count):
    return n("drawCards", TargetSelector=sel_source(), Count=const(count), ResultKey=None)


def buff(definition_id, name, text, triggers, tags=None):
    return {
        'Id': definition_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': text,
        'Polarity': 'Buff', 'UsesStacks': True, 'UsesDuration': False, 'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': tags or ['buff'],
        'PassiveModifiers': [], 'Triggers': triggers,
    }


def first_turn(counter, action):
    """**第 1 回合**做 `action`：判断（读到 0）在自增之前（§260 的教训）。"""
    return program(seq(
        conditional(compare(counter_get(counter), 'Equal', const(0)), action),
        counter_bump(counter),
    ))


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

    add_status(buff(
        'standard.lantern', 'Lantern',
        'Gain 1 Energy on the first turn of each combat.',
        [{'Event': 'TurnStarted', 'Program': first_turn('lantern_turns', gain_energy(1))}]))

    add_status(buff(
        'standard.bag_of_preparation', 'Bag of Preparation',
        'At the start of each combat, draw 2 additional cards.',
        [{'Event': 'TurnStarted', 'Program': first_turn('bag_of_preparation_turns', draw(2))}]))

    # 两条**没有触发器**的状态：它们的作用是让内核的回合机改变行为，靠的是**标签**。
    add_status(buff(
        'standard.ice_cream', 'Ice Cream',
        'Energy is now conserved between turns.',
        [], tags=['buff', 'unspent_energy_carries']))

    add_status(buff(
        'standard.calipers', 'Calipers',
        'At the start of your turn, lose 15 Block rather than all of your Block.',
        [], tags=['buff', 'block_loss_cap']))

    ROWS = [
        # (id, 显示名, 稀有度, 载体)
        ('lantern', 'Lantern', 'Common', ('status', 'standard.lantern', 1)),
        ('bag_of_preparation', 'Bag of Preparation', 'Common',
         ('status', 'standard.bag_of_preparation', 1)),
        ('ice_cream', 'Ice Cream', 'Rare', ('status', 'standard.ice_cream', 1)),
        # `calipers` 的 **15** 不是"层数"，是"失去多少格挡" —— 层数被当成标签的参数用。
        ('calipers', 'Calipers', 'Rare', ('status', 'standard.calipers', 15)),
        # `du_vu_doll` 没有自己的状态：它给的是**标准力量**，层数 = 每张诅咒 1 点。
        ('du_vu_doll', 'Du-Vu Doll', 'Rare', ('per_curse', 'standard.strength', 1)),
    ]
    for rid, display, rarity, carrier in ROWS:
        relics[rid] = {
            'Id': rid, 'DisplayName': display, 'Rarity': rarity,
            'RunPrograms': None, 'CombatRules': None,
        }
        print('relic %-20s %-7s %s' % (rid, rarity, carrier))

    doc['Relics'] = [relics[k] for k in sorted(relics)]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: statuses %d, relics %d' % (len(doc['Statuses']), len(doc['Relics'])))


main()
