"""§262 遗物第三批：**"每第 N 张某类型牌"**（7 件）。

## 七件共用一个机制

| 遗物 | 触发 | 效果 | 计数 | N |
|---|---|---|---|---|
| `kunai` | 第 3 张 Attack | +1 敏捷 | `kunai_attacks` | 3 |
| `shuriken` | 第 3 张 Attack | +1 力量 | `shuriken_attacks` | 3 |
| `ornamental_fan` | 第 3 张 Attack | +4 格挡 | `ornamental_fan_attacks` | 3 |
| `letter_opener` | 第 3 张 Skill | 对所有敌人 5 伤害 | `letter_opener_skills` | 3 |
| `nunchaku` | 第 10 张 Attack | +1 能量 | `nunchaku_attacks` | 10 |
| `ink_bottle` | 第 10 张**任何**牌 | 抽 1 张 | `ink_bottle_cards` | 10 |
| `pen_nib` | 第 10 张 Attack | **那次攻击**双倍伤害 | `pen_nib_attacks` | 10 |

**零内核改动。** 内核早就给了三样东西，这批只是把它们拼起来：

1. `CardPlayed` 触发器（派发给出牌者本人 —— `standard.rage` / `enrage` / `sharp_hide` 早就用着）；
2. `event.bool { FieldKey: "card.hasTag.attack" }` —— 宿主在派发 `CardPlayed` 时把卡牌 tag
   位算好（`exec::CARD_HAS_TAG_ATTACK` / `_SKILL`），所以"只数攻击牌"不需要把卡牌标签
   塞进表达式；
3. `remainder` + `combatantCounter` + `setCombatantCounter(Relative: false)` —— 一个模 N 计数器。

## 计数的写法：判断 → 清零 / 自增（§260 的教训）

`setCombatantCounter` 是**入队**效果，同一节目里读不到刚写的值。所以形状必须是

```
if (这张牌是 Attack) {
    if (counter % N == N-1) { 效果;  counter = 0 }   // 绝对写入
    else                    { counter += 1 }
}
```

两个分支互斥 ⇒ 只发生一次写入，不需要"读两次"。判据是 `N-1`（第 3 张时 counter 已经是 2）。

## Pen Nib：为什么它在**第 9 张**上挂翻倍

`CardPlayed` 触发器在**卡牌节目跑完之后**才派发（`play.rs` 把事件入队、程序就地执行，
队列随后的排空才跑触发器）。所以"第 10 张攻击时挂翻倍"会让**下一次**攻击翻倍。

⇒ 反过来用：**第 9 张攻击时**挂 `standard.double_damage`，那么被翻倍的就是第 10 张 —— 正是
wiki 说的那一次。翻倍状态自己带一条 `CardPlayed` 触发器：**下一张 Attack 打完之后摘掉自己**
（那时这一击的伤害已经吃到了 ×2）。

⚠️ 两处写明了的偏差（都记在 `docs/port-state.md` 的"说明了的不对称"里）：

* 窗口边界是"下一张 Attack 牌打完"，而不是 StS 那个 power 的生命周期 —— 窗口内**别的**
  直接伤害（例如 `Juggernaut` 那种由触发器打出的）也会被翻倍。参考的 `DoubleDamagePower`
  本身也不看卡牌类型，所以差异只在"窗口多长"，不在"翻不翻"。
* `PassiveModifiers.RestrictSourceCardTag` 本内核**故意**不解（`status_bind` 报 `Unsupported`，
  字段在镜像里恒 `NULL16`），所以翻倍不能写"只对攻击牌生效"。要写它需要先把
  "来源卡的哪个标签"从 bool 改成 tag id —— 那是另一件事，别在这里悄悄做。
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


def counter_get(counter):
    return {"kind": "combatantCounter",
            "value": {"Selector": sel_source(), "CounterId": counter}}


def counter_reset(counter):
    return n("setCombatantCounter", TargetSelector=sel_source(),
             CounterId={"value": counter}, Amount=const(0), Relative=False)


def counter_bump(counter):
    return n("setCombatantCounter", TargetSelector=sel_source(),
             CounterId={"value": counter}, Amount=const(1), Relative=True)


def compare(left, op, right):
    return {"kind": "compare", "value": {"Left": left, "Right": right, "Op": op}}


def remainder(left, right):
    return {"kind": "remainder", "value": {"Left": left, "Right": right}}


def conditional(condition, then, otherwise=None):
    return n("conditional", Condition=condition, Then=then, Else=otherwise)


def event_bool(field):
    return {"kind": "event.bool", "value": {"FieldKey": field}}


def gain_block(amount):
    return n("gainBlock", TargetSelector=sel_source(), Amount=const(amount), ResultKey=None)


def damage(amount):
    return n("dealDamage", TargetSelector=sel_all_enemies(), Amount=const(amount),
             ResultKey=None, IgnoresBlock=False, Element=None)


def gain_energy(amount):
    return n("gainResource", TargetSelector=sel_source(), ResourceId="standard.energy",
             Amount=const(amount), ResultKey=None)


def draw(count):
    return n("drawCards", TargetSelector=sel_source(), Count=const(count), ResultKey=None)


def status(definition_id, stacks):
    return n("applyStatus", TargetSelector=sel_source(),
             StatusDefinitionId={"value": definition_id}, Stacks=const(stacks))


def change_stacks(definition_id, delta):
    """**增减层数**（负数 = 摘掉若干层，0 层时内核删掉实例）。

    ⚠️ 不能用 `applyStatus` 加负数：`apply_one_status` 的受理不变量是"三轴负数一律 fault"
    （`StatusEffects.cs:55-62`，映射成 `Exec(Modifier)`）。§262 第一版就是这么红的 ——
    Pen Nib 的"下一击之后摘掉自己"写成了 `applyStatus(-1)`。
    """
    return n("modifyStatusStacks", TargetSelector=sel_source(),
             StatusDefinitionId={"value": definition_id}, Delta=const(delta), ResultKey=None)


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def and_(left, right):
    return {"kind": "and", "value": {"Left": left, "Right": right}}


def every_nth(counter, tag, period, effect):
    """每第 `period` 张 `tag` 牌做 `effect`。`tag=None` ⇒ 任何牌都算。

    ## 形状：**拍平 + 不清零**

    ```
    sequence[
        if (tag AND counter % N == N-1) { effect },
        if (tag)                        { counter += 1 },
    ]
    ```

    三条约束都是硬的，每一条都有一个踩出来的理由：

    1. **不许嵌套 `conditional`**（哪怕内层带 `Else`）。本镜像里
       `conditional(gate, sequence[conditional(...), ...])` 会在条件为假时 `Exec(Modifier)`
       炸掉 —— 见 §262.4 的复现记录。两个 `conditional` 平铺在同一层 `sequence` 里就没问题
       （§260 的 `incense_burner` 就是这个形状，一直在跑）。
    2. **不许把 `Else` 用起来**：`Else = seq()`（空）可以，`Else` 里放请求节点会炸。既然拍平之后
       不需要 `Else`，就不碰它。
    3. **不清零**：命中点落在 `N-1`、`2N-1`、`3N-1`… —— 对任何 N 都严格是"每第 N 张"。
       "命中后清零"只有在"命中点 == 消费点"时才碰巧对齐（§262 的 `pen_nib` 是反例：
       第 9 张挂、第 10 张吃，清零会让周期每轮漂一位）。

    计数器的增长是 `i32` 的 `wrapping_add`（一场战斗几百次出牌，够用）。
    """
    match = compare(remainder(counter_get(counter), const(period)), 'Equal', const(period - 1))
    if tag is None:
        return program(seq(conditional(match, effect), counter_bump(counter)))
    gate = event_bool("card.hasTag." + tag)
    return program(seq(
        conditional(and_(gate, match), effect),
        conditional(gate, counter_bump(counter)),
    ))


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

    # ---- Pen Nib 的翻倍载体：下一击（含多段攻击的每一段）伤害 ×2
    #
    # `ScalePercent 200` 与 `standard.vulnerable` 的 `150` 同一套；`Priority 250` 排在
    # 力量（100，加法）与虚弱（200，×0.75）之后 —— 三者都是乘法时顺序不影响结果，
    # 但"加法在乘法之前"是必须的，所以不能给 100。
    add_status(buff(
        'standard.double_damage', 'Double Damage',
        'Attacks deal double damage.',
        [{'Event': 'CardPlayed', 'Program': program(conditional(
            event_bool("card.hasTag.attack"),
            # **打完才摘**：这一刻这一击的伤害已经算过了（触发器在节目之后派发），
            # 而多段攻击的每一段都在节目里，所以两段都被翻倍 —— 与 StS 一致。
            change_stacks('standard.double_damage', -1)))}],
        modifiers=[{
            'Pipeline': 'DamageDealt',
            'Operation': 'ScalePercent',
            'Magnitude': 200,
            'Priority': 250,
            'RestrictDamageKind': 'Direct',
            'AppliesToStatusId': None,
            'RestrictSourceCardTag': None,
        }]))

    # ---- 六件"每第 N 张"
    add_status(buff(
        'standard.kunai', 'Kunai', 'Every 3rd Attack you play, gain 1 Dexterity.',
        [{'Event': 'CardPlayed',
          'Program': every_nth('kunai_attacks', 'attack', 3,
                               status('standard.dexterity', 1))}]))

    add_status(buff(
        'standard.shuriken', 'Shuriken', 'Every 3rd Attack you play, gain 1 Strength.',
        [{'Event': 'CardPlayed',
          'Program': every_nth('shuriken_attacks', 'attack', 3,
                               status('standard.strength', 1))}]))

    add_status(buff(
        'standard.ornamental_fan', 'Ornamental Fan',
        'Every 3rd Attack you play, gain 4 Block.',
        [{'Event': 'CardPlayed',
          'Program': every_nth('ornamental_fan_attacks', 'attack', 3, gain_block(4))}]))

    add_status(buff(
        'standard.letter_opener', 'Letter Opener',
        'Every 3rd Skill you play, deal 5 damage to ALL enemies.',
        [{'Event': 'CardPlayed',
          'Program': every_nth('letter_opener_skills', 'skill', 3, damage(5))}]))

    add_status(buff(
        'standard.nunchaku', 'Nunchaku', 'Every 10th Attack you play, gain 1 Energy.',
        [{'Event': 'CardPlayed',
          'Program': every_nth('nunchaku_attacks', 'attack', 10, gain_energy(1))}]))

    add_status(buff(
        'standard.ink_bottle', 'Ink Bottle', 'Every 10th card you play, draw 1 card.',
        [{'Event': 'CardPlayed',
          # 没有 tag 门：**任何**牌都算。
          'Program': every_nth('ink_bottle_cards', None, 10, draw(1))}]))

    # ---- Pen Nib：**第 9 张**挂翻倍（于是被翻倍的是第 10 张，见文件头）
    #
    # ⚠️ 阈值是 `8` 而不是 `9`：它的**挂**在攻击 #9、**吃**在攻击 #10，两个时点不同。
    # 若改成"每 10 张清零后挂"，下一轮就变成"第 19 张挂"⇒ 被翻倍的是第 19 张，每轮漂一位。
    # 一直累加 + `counter % 10 == 8` 才是 9/19/29 ⇒ 翻倍 10/20/30。
    _pen_gate = event_bool("card.hasTag.attack")
    _pen_arm = compare(remainder(counter_get('pen_nib_attacks'), const(10)), 'Equal', const(8))
    add_status(buff(
        'standard.pen_nib', 'Pen Nib', 'Every 10th Attack you play deals double damage.',
        [{'Event': 'CardPlayed', 'Program': program(seq(
            # 第 9、19、29… 次攻击：把翻倍挂上。
            conditional(and_(_pen_gate, _pen_arm), status('standard.double_damage', 1)),
            # 计数器**总是** +1（第二条 conditional 只看 tag 门）。
            conditional(_pen_gate, counter_bump('pen_nib_attacks')),
        ))}]))

    ROWS = [
        ('kunai', 'Kunai', 'standard.kunai'),
        ('shuriken', 'Shuriken', 'standard.shuriken'),
        ('ornamental_fan', 'Ornamental Fan', 'standard.ornamental_fan'),
        ('letter_opener', 'Letter Opener', 'standard.letter_opener'),
        ('nunchaku', 'Nunchaku', 'standard.nunchaku'),
        ('ink_bottle', 'Ink Bottle', 'standard.ink_bottle'),
        ('pen_nib', 'Pen Nib', 'standard.pen_nib'),
    ]
    for rid, display, carrier in ROWS:
        # wiki 的 `Module:Relics/data`：这七件**全部是 Uncommon**。
        relics[rid] = {
            'Id': rid, 'DisplayName': display, 'Rarity': 'Uncommon',
            'RunPrograms': None, 'CombatRules': None,
        }
        print('relic %-18s Uncommon  -> %s' % (rid, carrier))

    doc['Relics'] = [relics[k] for k in sorted(relics)]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: statuses %d, relics %d' % (len(doc['Statuses']), len(doc['Relics'])))


main()
