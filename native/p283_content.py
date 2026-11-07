"""§283 内容：Snecko 的"Bite 不连三次"（记**最近两次**招式）+ `snecko_eye` 遗物。

## 一、"Bite 不会连用三次"

wiki 原文："Snecko will not use Bite three times in a row."

内核的 `intent.selfHasCounter` 只能读**一个**计数器，而"连三次"是"最近**两次**都是 Bite"。
所以每个动作多写一格：**先把 `last_move` 抄进 `prev_move`，再把自己写进 `last_move`**。
`node.setCombatantCounter` 的 `Amount` 是**表达式**（`combatantCounter`），所以抄这一格不需要
任何内核改动 —— 全是内容。

然后一条规则压在选择之上：
  prev_move == 2 AND last_move == 2  ⇒  **Tail Whip**（Bite 的索引是 2）

## 二、`snecko_eye`（Boss 遗物）

wiki："At the start of your turn, draw 2 additional cards. Start each combat Confused."

两条都走**内容**（§267 那条"零基建"路）：
* `standard.snecko_eye` 状态：`TurnStarted` 触发器 —— 首回合给自己挂 `standard.confusion`，
  且**每回合** `drawCards 2`；
* 遗物 `snecko_eye` 只是"开战挂这条状态"（`RelicEffect::StartCombatStatus`）。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

SOURCE_SEL = {'kind': 'sel.source',
              'value': {'Cardinality': 'ZeroOrOne',
                        'RequiredContextCapabilities': 'Source'}}
EVENT_SEL = {'kind': 'sel.eventTarget',
             'value': {'Cardinality': 'ZeroOrOne',
                       'RequiredContextCapabilities': 'EventTarget'}}


def counter_of(name):
    return {'kind': 'combatantCounter',
            'value': {'Selector': SOURCE_SEL, 'CounterId': name}}


def set_counter(name, amount, relative=False):
    return {'kind': 'node.setCombatantCounter',
            'value': {'TargetSelector': SOURCE_SEL,
                      'CounterId': {'value': name},
                      'Amount': amount,
                      'Relative': relative}}


def const(value):
    return {'kind': 'const', 'value': {'Value': value}}


def damage(amount):
    return {'kind': 'node.dealDamage',
            'value': {'TargetSelector': EVENT_SEL,
                      'Amount': const(amount),
                      'ResultKey': None,
                      'IgnoresBlock': False,
                      'Element': None}}


def status(name, stacks, on_self=False):
    """`applyStatus`。⚠️ 触发器的程序里 `sel.eventTarget` 是**空的**（`TurnStarted` 没有目标），
    所以"给自己挂"必须用 `sel.source` —— 第一版用了 eventTarget，状态静默没挂上，
    而同一段里的 `drawCards`（用 source）却成功了，于是"抽了 7 张但没有 Confused"。"""
    return {'kind': 'node.applyStatus',
            'value': {'TargetSelector': SOURCE_SEL if on_self else EVENT_SEL,
                      'StatusDefinitionId': {'value': name},
                      'Stacks': const(stacks),
                      'DurationTurns': 0,
                      'Charges': 0,
                      'ResultKey': None}}


def seq(*children):
    return {'kind': 'node.sequence', 'value': {'Children': list(children)}}


def program(root):
    return {'Id': {'Value': '(unnamed)'}, 'Root': root}


def compare(left, right, op):
    return {'kind': 'compare', 'value': {'Left': left, 'Right': right, 'Op': op}}


def conditional(condition, then):
    return {'kind': 'node.conditional',
            'value': {'Condition': condition, 'Then': then, 'Else': None}}


def draw(count):
    return {'kind': 'node.drawCards',
            'value': {'TargetSelector': SOURCE_SEL, 'Count': const(count)}}


def self_has_counter(name, value):
    return {'kind': 'intent.selfHasCounter',
            'value': {'Counter': {'value': name}, 'Op': 'Equal', 'Value': value}}


def all_of(*conditions):
    return {'kind': 'intent.allOf', 'value': {'Conditions': list(conditions)}}


# 动作索引（写进 `last_move`/`prev_move`；`2` = Bite，那条规则要用）
BITE, TAIL_WHIP, GLARE = 2, 3, 1


def shift_and_set(move):
    """`prev_move = last_move` 然后 `last_move = move`。"""
    return [set_counter('prev_move', counter_of('last_move')),
            set_counter('last_move', const(move))]


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    actions = {a['Id']: a for a in doc['EnemyActions']}

    # ── ① 三个动作都记两步 ────────────────────────────────────────────────────
    actions['snecko.perplexing_glare']['Program']['Root'] = seq(
        status('standard.confusion', 1), *shift_and_set(GLARE))
    actions['snecko.bite']['Program']['Root'] = seq(
        damage(15), *shift_and_set(BITE))
    actions['snecko.bite']['ProgramAsc'] = [
        {'AscensionMin': 2, 'Program': program(seq(damage(18), *shift_and_set(BITE)))}]
    actions['snecko.tail_whip']['Program']['Root'] = seq(
        damage(8), status('standard.vulnerable', 2), *shift_and_set(TAIL_WHIP))
    actions['snecko.tail_whip']['ProgramAsc'] = [
        {'AscensionMin': 2,
         'Program': program(seq(damage(10), status('standard.vulnerable', 2),
                                *shift_and_set(TAIL_WHIP)))},
        {'AscensionMin': 17,
         'Program': program(seq(damage(10), status('standard.vulnerable', 2),
                                status('standard.weak', 2), *shift_and_set(TAIL_WHIP)))},
    ]
    doc['EnemyActions'] = list(actions.values())

    # ── ② 规则：最近两次都是 Bite ⇒ 这一回合不许再 Bite ────────────────────────
    rules = [
        # 首回合：Perplexing Glare（最高优先级，wiki: "Always starts with"）。
        {'Condition': {'kind': 'intent.round', 'value': {'Op': 'Equal', 'Round': 1}},
         'Action': {'value': 'snecko.perplexing_glare'}, 'Priority': 96},
        # ★ "Bite 不会连用三次"：最近**两次**都是 Bite ⇒ 强制 Tail Whip。
        {'Condition': all_of(self_has_counter('prev_move', BITE),
                             self_has_counter('last_move', BITE)),
         'Action': {'value': 'snecko.tail_whip'}, 'Priority': 95},
        # 否则 60/40 加权。
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': []}},
         'Priority': 10,
         'Choice': [{'Action': {'value': 'snecko.bite'}, 'Weight': 60},
                    {'Action': {'value': 'snecko.tail_whip'}, 'Weight': 40}]},
    ]
    for monster in doc['Monsters']:
        if monster['Id'] == 'snecko':
            monster['IntentRules'] = json.loads(json.dumps(rules))
    for enc in doc['Encounters']:
        eid = enc['Id']['Value'] if isinstance(enc['Id'], dict) else enc['Id']
        if eid != 'enc_snecko':
            continue
        for enemy in enc['Enemies']:
            enemy['IntentRules'] = json.loads(json.dumps(rules))

    # ── ③ `standard.snecko_eye`：首回合挂 Confused + 每回合多抽 2 ──────────────
    if not any(s['Id'] == 'standard.snecko_eye' for s in doc['Statuses']):
        doc['Statuses'].append({
            'Id': 'standard.snecko_eye',
            'PackageId': 'sts',
            'NameKey': 'Snecko Eye',
            'DescriptionKey': 'Draw 2 additional cards each turn. Start each combat Confused.',
            'Polarity': 'Buff',
            'UsesStacks': True,
            'UsesDuration': False,
            'UsesCharges': False,
            'StackingBehavior': 'MergeWithExistingInstance',
            'Tags': ['buff'],
            'PassiveModifiers': [],
            'Triggers': [{
                'Event': 'TurnStarted',
                'Program': program(seq(
                    # ⚠️ 每回合都挂（`Confusion` 不叠加，重复挂无害）。**偏差**：wiki 的
                    # `Orange Pellets` 清掉 Confused 之后不会回来，而我们下一回合会再挂上。
                    # 原本想用"首回合才挂"（计数器判第一次 `TurnStarted`），但状态触发器的
                    # 程序里 `combatantCounter(sel.source)` 读到的是 0（触发帧的 source 不是
                    # 状态拥有者），于是条件恒真 —— 那反而更糟（看起来像"只在首回合"）。
                    # 见 `docs/sts-wiki-gap.md` F.4。
                    status('standard.confusion', 1, on_self=True),
                    # 每回合多抽 2（wiki: "At the start of your turn, draw 2 additional cards"）。
                    draw(2),
                )),
            }],
        })

    # ── ③b `standard.confusion` 要 `UsesStacks: true` ─────────────────────────
    # §282 声明它时写了 `UsesStacks: false`（"不叠加"），但 `applyStatus(stacks: 1)` 走
    # `status_bind` 时会被拒（一条不接受层数的状态收到 1 层），于是 §283 从触发器挂它
    # **静默不落地**。wiki 的"Does not stack"讲的是**上限 1**，不是"没有层数" ——
    # 与 §231 的 `standard.no_draw`（同样是开关，也是 `UsesStacks: true`）对齐。
    for row in doc['Statuses']:
        if row['Id'] == 'standard.confusion':
            row['UsesStacks'] = True

    # ── ④ 遗物行（Boss 稀有度）──────────────────────────────────────────────
    if not any(r['Id'] == 'snecko_eye' for r in doc['Relics']):
        doc['Relics'].append({
            'Id': 'snecko_eye',
            'DisplayName': 'Snecko Eye',
            'Rarity': 'Boss',
            'RunPrograms': None,
            'CombatRules': None,
        })

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('snecko: prev_move/last_move + no-3x-bite rule; snecko_eye status + relic')


main()
