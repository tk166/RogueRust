"""§267 零基建批次：17 件遗物（**全部纯内容**，外加 3 处元数据修正）。

## 分类

| 组 | 遗物 | 靠什么 |
|---|---|---|
| 开战载体（不用状态） | `clockwork_souvenir` / `red_mask` / `gremlin_visage` / `fossilized_helix` | `StartCombatStatus(OnEnemies)` 的既有四个变体 |
| 轮次轴 | `ring_of_the_snake` / `ring_of_the_serpent` / `philosophers_stone` / `happy_flower` / `art_of_war` | `TurnStarted`/`TurnEnded` 触发器 + `TurnStartDraw`/`TurnStartEnergy` 修饰器 |
| 反应轴 | `centennial_puzzle` / `runic_cube` / `charons_ashes` / `duality` / `akabeko` / `brimstone` | `HpLost` / `CardExhausted` / `CardPlayed` 触发器 + `Condition` |
| 拾取即生效 | `mango` | 既有 `MaxHealthUp` 变体 |

## 顺手修的三处元数据（`audit_relic_gap.py` 报的）

`nunchaku` / `pen_nib` 的稀有度应是 **Common**、`paper_krane` 应是 **Uncommon**
（§262/§264 当时按"这七件全是 Uncommon"批量写的，那是错的）。

## 一个"声明了但没实现"的表达式

`cardsPlayedThisTurnWithTag` 在 `expr.rs` 的 `INT_KINDS` 里**声明着**，但没有求值臂 ——
用它会在运行期 `UnsupportedKind`。所以 `art_of_war`（"这回合没出攻击牌"）与 `akabeko`
（"第一张攻击"）都用**内容自己的计数器**：`CardPlayed` + `event.bool(card.hasTag.attack)`
自增，`TurnEnded` 读它并清零。
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


def event_bool(field):
    return {"kind": "event.bool", "value": {"FieldKey": field}}


def counter_get(counter):
    return {"kind": "combatantCounter",
            "value": {"Selector": sel_source(), "CounterId": counter}}


def counter_bump(counter, amount=1):
    return n("setCombatantCounter", TargetSelector=sel_source(),
             CounterId={"value": counter}, Amount=const(amount), Relative=True)


def counter_reset(counter):
    return n("setCombatantCounter", TargetSelector=sel_source(),
             CounterId={"value": counter}, Amount=const(0), Relative=False)


def compare(left, op, right):
    return {"kind": "compare", "value": {"Left": left, "Right": right, "Op": op}}


def remainder(left, right):
    return {"kind": "remainder", "value": {"Left": left, "Right": right}}


def conditional(condition, then):
    return n("conditional", Condition=condition, Then=then, Else=None)


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def draw(count):
    return n("drawCards", TargetSelector=sel_source(), Count=const(count), ResultKey=None)


def gain_energy(amount):
    return n("gainResource", TargetSelector=sel_source(), ResourceId="standard.energy",
             Amount=const(amount), ResultKey=None)


def status(definition_id, stacks, target=None):
    return n("applyStatus", TargetSelector=target or sel_source(),
             StatusDefinitionId={"value": definition_id}, Stacks=const(stacks))


def change_stacks(definition_id, delta):
    return n("modifyStatusStacks", TargetSelector=sel_source(),
             StatusDefinitionId={"value": definition_id}, Delta=const(delta), ResultKey=None)


def damage_all(amount):
    return n("dealDamage", TargetSelector=sel_all_enemies(), Amount=const(amount),
             ResultKey=None, IgnoresBlock=False, Element=None)


def create_card(card_id, zone, count=1):
    return n("createCardInstance", CardDefinitionId={"value": card_id},
             Count=const(count), TargetSelector=sel_source(), ToZone=zone, ResultKey=None)


def buff(definition_id, name, text, triggers, modifiers=None, tags=None, triggers_extra=None):
    return {
        'Id': definition_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': text,
        'Polarity': 'Buff', 'UsesStacks': True, 'UsesDuration': False, 'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': tags or ['buff'],
        'PassiveModifiers': modifiers or [],
        'Triggers': list(triggers) + list(triggers_extra or []),
    }


def spec(pipeline, operation, magnitude, priority, kind, applies_to=None, condition=None,
         card_tag=None, scope=None):
    row = {
        'Pipeline': pipeline, 'Operation': operation, 'Magnitude': magnitude,
        'Priority': priority, 'RestrictDamageKind': kind,
        'AppliesToStatusId': {'value': applies_to} if applies_to else None,
        'RestrictSourceCardTag': {'value': card_tag} if card_tag else None,
    }
    if scope:
        row['OverrideScope'] = scope
    if condition:
        row['Condition'] = condition
    return row


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

    # ---------------- 轮次轴 ----------------

    # Ring of the Snake（起手）：开战多抽 2 张 —— 与 `bag_of_preparation` 同一个形状。
    add_status(buff(
        'standard.ring_of_the_snake', 'Ring of the Snake',
        'At the start of each combat, draw 2 additional cards.',
        [{'Event': 'TurnStarted', 'Program': program(seq(
            conditional(compare(counter_get('ring_of_the_snake_turns'), 'Equal', const(0)),
                        draw(2)),
            counter_bump('ring_of_the_snake_turns')))}]))

    # Ring of the Serpent（Boss）：每回合多抽 1 张 —— 走 `TurnStartDraw` 修饰器，**没有触发器**。
    add_status(buff(
        'standard.ring_of_the_serpent', 'Ring of the Serpent',
        'At the start of your turn, draw 1 additional card.',
        [], modifiers=[spec('TurnStartDraw', 'AddFlat', 1, 100, None)]))

    # Philosopher's Stone（Boss）：每回合 +1 能量（`TurnStartEnergy` 修饰器）。
    add_status(buff(
        "standard.philosophers_stone", "Philosopher's Stone",
        'Gain 1 Energy at the start of your turn. ALL enemies start combat with 1 Strength.',
        [], modifiers=[spec('TurnStartEnergy', 'AddPerStack', 1, 100, None)]))

    # Happy Flower：每 3 回合 +1 能量（全部等幅）。
    add_status(buff(
        'standard.happy_flower', 'Happy Flower', 'Every 3 turns, gain 1 Energy.',
        [{'Event': 'TurnStarted', 'Program': program(seq(
            # 判断在自增**之前**（§260 的教训：`setCombatantCounter` 是入队效果）。
            conditional(compare(remainder(counter_get('happy_flower_turns'), const(3)),
                                'Equal', const(2)),
                        gain_energy(1)),
            counter_bump('happy_flower_turns')))}]))

    # Art of War：这回合**没出攻击牌** ⇒ 下回合多 1 能量。
    #
    # 两个触发器：`CardPlayed` 只数攻击牌（`event.bool` 的卡牌 tag 位），`TurnEnded` 读计数、
    # 给能量、然后**绝对清零**（回合末清零就是 wiki 的 "during your turn"）。
    add_status(buff(
        'standard.art_of_war', 'Art of War',
        'If you do not play any Attacks during your turn, gain an additional Energy next turn.',
        [
            {'Event': 'CardPlayed', 'Program': program(conditional(
                event_bool("card.hasTag.attack"), counter_bump('art_of_war_attacks')))},
            # 回合末：没出攻击 ⇒ 立一个"下回合多 1 能量"的待决标记（`art_of_war_pending`）。
            # ⚠️ **不能**在这里直接 `gainResource`：下一回合的补给是"设成 base"，会把这点抹掉
            # （§267 的判据就是这么红的：3 而不是 4）。
            {'Event': 'TurnEnded', 'Program': program(seq(
                conditional(compare(counter_get('art_of_war_attacks'), 'Equal', const(0)),
                            counter_bump('art_of_war_pending')),
                counter_reset('art_of_war_attacks')))}],
        modifiers=[spec(
            'TurnStartEnergy', 'AddFlat', 1, 100, None,
            # 补给（turn-start 第 2 步）**先于**触发器（第 4 步），所以这一刻读到的还是上回合
            # 留下的标记；清零由下面那条 `TurnStarted` 做（晚一步，已经给过了）。
            condition=compare(counter_get('art_of_war_pending'), 'Greater', const(0)))],
        triggers_extra=[{'Event': 'TurnStarted', 'Program': program(
            counter_reset('art_of_war_pending'))}]))

    # ---------------- 开战 / 回合初的反应 ----------------

    # Brimstone：回合初自己 +2 力量、所有敌人 +1 力量。
    add_status(buff(
        'standard.brimstone', 'Brimstone',
        'At the start of your turn, gain 2 Strength and ALL enemies gain 1 Strength.',
        [{'Event': 'TurnStarted', 'Program': program(seq(
            status('standard.strength', 2),
            status('standard.strength', 1, sel_all_enemies())))}]))

    # Mark of Pain（Boss）：每回合 +1 能量 + 开战把 2 张 Wound 洗进抽牌堆。
    add_status(buff(
        'standard.mark_of_pain', 'Mark of Pain',
        'Gain 1 Energy at the start of your turn. '
        'At the start of combat, shuffle 2 Wounds into your draw pile.',
        [{'Event': 'TurnStarted', 'Program': program(seq(
            conditional(compare(counter_get('mark_of_pain_turns'), 'Equal', const(0)),
                        create_card('wound', 'DrawPile', 2)),
            counter_bump('mark_of_pain_turns')))}],
        modifiers=[spec('TurnStartEnergy', 'AddPerStack', 1, 100, None)]))

    # Mutagenic Strength：开战 3 力量、**第一回合末**失去 3 力量。
    add_status(buff(
        'standard.mutagenic_strength', 'Mutagenic Strength',
        'Start each combat with 3 Strength. At the end of your first turn, lose 3 Strength.',
        [{'Event': 'TurnEnded', 'Program': program(seq(
            conditional(compare(counter_get('mutagenic_strength_turns'), 'Equal', const(0)),
                        change_stacks('standard.strength', -3)),
            counter_bump('mutagenic_strength_turns')))}]))

    # ---------------- 掉血 / 消耗 / 出牌的反应 ----------------

    # Centennial Puzzle：本场**第一次**掉血 ⇒ 抽 3 张。
    # ⚠️ "掉血"有**两条**路：伤害（`DamageTaken`）与直接失去生命（`HpLost`，如 `offering`）。
    # wiki 说的是 "lose HP"，两者都算 ⇒ 两条触发器、共用同一个计数器。
    # `DamageTaken` 还带"这一下掉了几点"（`eventAmount`），被格挡吃干净的那次是 0 ⇒ 要门。
    add_status(buff(
        'standard.centennial_puzzle', 'Centennial Puzzle',
        'The first time you lose HP each combat, draw 3 cards.',
        [
            {'Event': 'DamageTaken', 'Program': program(conditional(
                compare({"kind": "eventAmount", "value": {}}, 'Greater', const(0)),
                seq(
                    conditional(compare(counter_get('centennial_puzzle_hits'), 'Equal', const(0)),
                                draw(3)),
                    counter_bump('centennial_puzzle_hits'))))},
            {'Event': 'HpLost', 'Program': program(seq(
                conditional(compare(counter_get('centennial_puzzle_hits'), 'Equal', const(0)),
                            draw(3)),
                counter_bump('centennial_puzzle_hits')))}]))

    # Runic Cube（Boss）：每次掉血抽 1 张。
    add_status(buff(
        'standard.runic_cube', 'Runic Cube', 'Whenever you lose HP, draw 1 card.',
        [
            {'Event': 'DamageTaken', 'Program': program(conditional(
                compare({"kind": "eventAmount", "value": {}}, 'Greater', const(0)), draw(1)))},
            {'Event': 'HpLost', 'Program': program(draw(1))}]))

    # Charon's Ashes：消耗一张牌 ⇒ 对所有敌人 3 点。
    add_status(buff(
        "standard.charons_ashes", "Charon's Ashes",
        'Whenever you Exhaust a card, deal 3 damage to ALL enemies.',
        [{'Event': 'CardExhausted', 'Program': program(damage_all(3))}]))

    # Duality：每出一张攻击牌 ⇒ +1 敏捷，**本回合末消失**。
    #
    # `standard.lose_dexterity` 就是"回合末把借来的敏捷还回去"的那条状态（§158 的 Flex 半边），
    # 所以这里成对施加：+1 敏捷 与 +1 待还。
    add_status(buff(
        'standard.duality', 'Duality',
        'Whenever you play an Attack, gain 1 temporary Dexterity.',
        [{'Event': 'CardPlayed', 'Program': program(conditional(
            event_bool("card.hasTag.attack"),
            seq(status('standard.dexterity', 1),
                status('standard.lose_dexterity', 1))))}]))

    # Akabeko：每场战斗的**第一张**攻击牌 +8 伤害。
    #
    # 伤害那一侧是 `Condition`（计数器为 0）+ `RestrictSourceCardTag: attack`；
    # 计数器由 `CardPlayed` 在**这一击结算之后**自增（触发器在节目之后派发），所以第一击读到的
    # 就是 0 —— 这正是我们要的时序，写下来免得以后有人"顺手"把它挪到前面。
    add_status(buff(
        'standard.akabeko', 'Akabeko',
        'Your first Attack each combat deals 8 additional damage.',
        [{'Event': 'CardPlayed', 'Program': program(conditional(
            event_bool("card.hasTag.attack"), counter_bump('akabeko_attacks')))}],
        modifiers=[spec('DamageDealt', 'AddFlat', 8, 100, 'Direct',
                        condition=compare(counter_get('akabeko_attacks'), 'Equal', const(0)),
                        card_tag='attack')]))

    # ---------------- 遗物行 ----------------
    #
    # `carrier`：`hero` = 挂给英雄的状态；`enemies` = 开战给敌人的状态；`none` = 不需要状态。
    ROWS = [
        # 轮次轴
        ('ring_of_the_snake', 'Ring of the Snake', 'Starter', ('hero', 'standard.ring_of_the_snake', 1)),
        ('ring_of_the_serpent', 'Ring of the Serpent', 'Boss', ('hero', 'standard.ring_of_the_serpent', 1)),
        ('philosophers_stone', "Philosopher's Stone", 'Boss', ('hero', 'standard.philosophers_stone', 1)),
        ('happy_flower', 'Happy Flower', 'Common', ('hero', 'standard.happy_flower', 1)),
        ('art_of_war', 'Art of War', 'Common', ('hero', 'standard.art_of_war', 1)),
        ('brimstone', 'Brimstone', 'Shop', ('hero', 'standard.brimstone', 1)),
        ('mark_of_pain', 'Mark of Pain', 'Boss', ('hero', 'standard.mark_of_pain', 1)),
        ('mutagenic_strength', 'Mutagenic Strength', 'Event', ('hero', 'standard.mutagenic_strength', 1)),
        # 反应轴
        ('centennial_puzzle', 'Centennial Puzzle', 'Common', ('hero', 'standard.centennial_puzzle', 1)),
        ('runic_cube', 'Runic Cube', 'Boss', ('hero', 'standard.runic_cube', 1)),
        ('charons_ashes', "Charon's Ashes", 'Rare', ('hero', 'standard.charons_ashes', 1)),
        ('duality', 'Duality', 'Uncommon', ('hero', 'standard.duality', 1)),
        ('akabeko', 'Akabeko', 'Common', ('hero', 'standard.akabeko', 1)),
        # 开战载体（不需要状态）：状态 id 那一栏写的是**那条状态本身**
        ('clockwork_souvenir', 'Clockwork Souvenir', 'Shop', ('hero', 'standard.artifact', 1)),
        ('red_mask', 'Red Mask', 'Event', ('enemies', 'standard.weak', 1)),
        ('gremlin_visage', 'Gremlin Visage', 'Event', ('hero', 'standard.weak', 1)),
        ('fossilized_helix', 'Fossilized Helix', 'Rare', ('hero', 'standard.buffer', 1)),
        # 拾取即生效（走既有的 `MaxHealthUp`）
        ('mango', 'Mango', 'Rare', ('none', None, 0)),
    ]
    for rid, display, rarity, carrier in ROWS:
        relics[rid] = {
            'Id': rid, 'DisplayName': display, 'Rarity': rarity,
            'RunPrograms': None, 'CombatRules': None,
        }
        print('relic %-20s %-9s %s' % (rid, rarity, carrier))

    # ---------------- 三处元数据修正 ----------------
    FIX = {'nunchaku': 'Common', 'pen_nib': 'Common', 'paper_krane': 'Uncommon'}
    for rid, rarity in FIX.items():
        old = relics[rid]['Rarity']
        relics[rid]['Rarity'] = rarity
        print('rarity fix %-14s %s -> %s' % (rid, old, rarity))

    doc['Relics'] = [relics[k] for k in sorted(relics)]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: statuses %d, relics %d' % (len(doc['Statuses']), len(doc['Relics'])))


main()
