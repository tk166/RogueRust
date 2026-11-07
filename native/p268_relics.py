"""§268 零基建档收尾（6 件）+ 轻资产档的**钩子位置表**。

## 这一批

| 遗物 | 稀有度 | wiki 原话 | 机制 |
|---|---|---|---|
| `self_forming_clay` | Uncommon | "Whenever you lose HP, gain 3 Block next turn." | 掉血立待决标记，`TurnStarted` 兑现 |
| `bird_faced_urn` | Rare | "Whenever you play a Power card, heal 2 HP." | `CardPlayed` + `card.hasTag.power` |
| `runic_pyramid` | Boss | "At the end of your turn, you no longer discard your hand." | 状态的 `retain_hand` **标签** |
| `lizard_tail` | Rare | "When you would die, heal to 50% of your Max HP instead (works once)." | 状态的 `DeathPrevention` 行 |
| `black_blood` | Boss | "Replaces Burning Blood. At the end of combat, heal 12 HP." | 既有 `EndOfCombatHeal` |
| `unceasing_top` | Rare | "Whenever you have no cards in hand during your turn, draw a card." | `CardPlayed` + 手牌区计数 |

`runic_pyramid` 与 `lizard_tail` 是**纯数据**：前者靠 `host.rs::TAG_RETAIN_HAND`（
`hand_is_retained` 读它），后者靠 `STAT.DeathPrevention`（`status_bind::death_prevention` +
`exec::death_prevention_for` 读它，`Repeating: false` ⇒ 一次性 ⇒ 正好是 wiki 的 "works once"）。
两条规则以前都只有"内核一侧"，这一批是**第一次有内容去用**。

## `dead_branch` 为什么不在这一批

`node.createRandomCardInstance` 的 `Tag` 是**必填**（内核 `Missing("Tag")`），而
"随机一张牌"（StS 的口袋池）没有"任意"这种写法 ⇒ 它要一个小钩子（`Tag` 允许缺席 = 任意），
归到轻资产。
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


def event_bool(field):
    return {"kind": "event.bool", "value": {"FieldKey": field}}


def event_amount():
    return {"kind": "eventAmount", "value": {}}


def counter_get(counter):
    return {"kind": "combatantCounter",
            "value": {"Selector": sel_source(), "CounterId": counter}}


def counter_bump(counter):
    return n("setCombatantCounter", TargetSelector=sel_source(),
             CounterId={"value": counter}, Amount=const(1), Relative=True)


def counter_reset(counter):
    return n("setCombatantCounter", TargetSelector=sel_source(),
             CounterId={"value": counter}, Amount=const(0), Relative=False)


def compare(left, op, right):
    return {"kind": "compare", "value": {"Left": left, "Right": right, "Op": op}}


def multiply(left, right):
    return {"kind": "multiply", "value": {"Left": left, "Right": right}}


def conditional(condition, then):
    return n("conditional", Condition=condition, Then=then, Else=None)


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def gain_block(amount):
    return n("gainBlock", TargetSelector=sel_source(), Amount=amount, ResultKey=None)


def heal(amount):
    return n("heal", TargetSelector=sel_source(), Amount=const(amount), ResultKey=None)


def draw(count):
    return n("drawCards", TargetSelector=sel_source(), Count=const(count), ResultKey=None)


def hand_count():
    return {"kind": "combatantZoneCount",
            "value": {"Selector": sel_source(), "Zone": "Hand"}}


def buff(definition_id, name, text, triggers, modifiers=None, tags=None, death_prevention=None):
    row = {
        'Id': definition_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': text,
        'Polarity': 'Buff', 'UsesStacks': True, 'UsesDuration': False, 'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': tags or ['buff'],
        'PassiveModifiers': modifiers or [],
        'Triggers': triggers,
    }
    if death_prevention:
        row['DeathPrevention'] = death_prevention
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

    # ---- Self-Forming Clay：每次掉血攒 3 点格挡，下回合开始兑现
    #
    # 与 `art_of_war` 同一个"待决标记"形状：回合末/掉血那一刻**不能**直接给格挡（给的是
    # **下回合**的），所以攒起来、在 `TurnStarted` 兑现、然后清零。
    # 掉血两条路（伤害 / 失去生命）都要听，与 §267 的教训一致。
    add_status(buff(
        'standard.self_forming_clay', 'Self-Forming Clay',
        'Whenever you lose HP, gain 3 Block next turn.',
        [
            {'Event': 'DamageTaken', 'Program': program(conditional(
                compare(event_amount(), 'Greater', const(0)),
                counter_bump('self_forming_clay_pending')))},
            {'Event': 'HpLost', 'Program': program(counter_bump('self_forming_clay_pending'))},
            {'Event': 'TurnStarted', 'Program': program(seq(
                conditional(compare(counter_get('self_forming_clay_pending'), 'Greater', const(0)),
                            gain_block(multiply(counter_get('self_forming_clay_pending'),
                                                const(3)))),
                counter_reset('self_forming_clay_pending')))}]))

    # ---- Bird-Faced Urn：出一张 Power 牌 ⇒ 回 2 点
    add_status(buff(
        'standard.bird_faced_urn', 'Bird-Faced Urn',
        'Whenever you play a Power card, heal 2 HP.',
        [{'Event': 'CardPlayed', 'Program': program(conditional(
            event_bool("card.hasTag.power"), heal(2)))}]))

    # ---- Runic Pyramid：回合末不弃手牌 —— 整个规则就是那条**标签**
    add_status(buff(
        'standard.runic_pyramid', 'Runic Pyramid',
        'At the end of your turn, you no longer discard your hand.',
        [], tags=['buff', 'retain_hand']))

    # ---- Lizard Tail：致死时回到 50% 上限血，**一次性**
    #
    # `DeathPrevention` 的行由 `status_bind::death_prevention` 解，`exec::death_prevention_for`
    # 在"血落到 0 但还没 Downed"那一点读它；`Repeating: false` ⇒ 用掉就摘（wiki 的 "works once"）。
    add_status(buff(
        'standard.lizard_tail', 'Lizard Tail',
        'When you would die, heal to 50% of your Max HP instead (works once).',
        [], death_prevention={'SurvivingHealth': 0, 'Percent': 50, 'Repeating': False}))

    # ---- Unceasing Top：手牌空了就抽 1 张
    #
    # 时序：`CardPlayed` 在打出的牌**离开手牌之后**派发（落区在终态回调里，早于排空），
    # 所以"打掉最后一张"这一刻 `hand == 0` 成立 —— 也正是 wiki 要的那一刻。
    add_status(buff(
        'standard.unceasing_top', 'Unceasing Top',
        'Whenever you have no cards in hand during your turn, draw a card.',
        [{'Event': 'CardPlayed', 'Program': program(conditional(
            compare(hand_count(), 'Equal', const(0)), draw(1)))}]))

    # ---- 遗物行 ----
    ROWS = [
        ('self_forming_clay', 'Self-Forming Clay', 'Uncommon', ('hero', 'standard.self_forming_clay')),
        ('bird_faced_urn', 'Bird-Faced Urn', 'Rare', ('hero', 'standard.bird_faced_urn')),
        ('runic_pyramid', 'Runic Pyramid', 'Boss', ('hero', 'standard.runic_pyramid')),
        ('lizard_tail', 'Lizard Tail', 'Rare', ('hero', 'standard.lizard_tail')),
        ('unceasing_top', 'Unceasing Top', 'Rare', ('hero', 'standard.unceasing_top')),
        # `black_blood` 不需要状态：走既有的 `EndOfCombatHeal`。
        ('black_blood', 'Black Blood', 'Boss', ('none', None)),
    ]
    for rid, display, rarity, carrier in ROWS:
        relics[rid] = {
            'Id': rid, 'DisplayName': display, 'Rarity': rarity,
            'RunPrograms': None, 'CombatRules': None,
        }
        print('relic %-20s %-9s %s' % (rid, rarity, carrier))

    doc['Relics'] = [relics[k] for k in sorted(relics)]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: statuses %d, relics %d' % (len(doc['Statuses']), len(doc['Relics'])))


main()
