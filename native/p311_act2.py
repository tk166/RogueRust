"""§311 Act 2 的普通遭遇池：3 → 11 条（wiki 的 13 条里，11 条已能做）。

wiki（`The_City` 页，两处来源交叉核对）：

| 池 | 遭遇 | 权重 | 组成 |
|---|---|---|---|
| Easy | Spheric Guardian | 2 | 1 |
| Easy | Chosen | 2 | 1 |
| Easy | Shelled Parasite | 2 | 1 |
| Easy | 3 Byrds | 2 | 3 |
| Easy | 2 Thieves | 2 | 1 Looter（左）+ 1 Mugger（右） |
| Hard | Chosen and Byrds | 2 | 1 Chosen + **1** Byrd |
| Hard | Cultist and Chosen | 3 | 1 各 |
| Hard | Sentry and Spheric Guardian | 2 | 1 各 |
| Hard | Snake Plant | 6 | 1 |
| Hard | Snecko | 4 | 1 |
| Hard | Centurion and Mystic | 6 | 1 各 |
| Hard | 3 Cultists | 3 | 3 |
| Hard | Shelled Parasite and Fungi | 3 | 1 各 |

这一轮做 **11 条**：新增 `spheric_guardian` 一个怪物（其余用现有怪物拼）。
剩两条要新机制，记在 `docs/sts-wiki-gap.md` §D.3：
* `snake_plant` —— 需要 `standard.malleable`（"受到攻击伤害时获得格挡，且越挨越多"）；
* `centurion` + `mystic` —— 需要"指定**某一只**友军"的选择器（Protect 给 Mystic 挂格挡）。

⚠️ 顺手修一个**内容 bug**：`enc_byrds` 只有 **1 只** byrd，而 wiki 的 "3 Byrds" 是三只。
这条同时影响第三幕的池子。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def ident(value):
    return {'value': value}


def enc_ident(value):
    """遭遇表的 `Id` 用的是**大写**包装（与节点的 `{"value": …}` 不同一种拼写）。"""
    return {'Value': value}


def sel_source():
    return {'kind': 'sel.source',
            'value': {'Cardinality': 'ZeroOrOne',
                      'RequiredContextCapabilities': 'Source'}}


def sel_event():
    return {'kind': 'sel.eventTarget',
            'value': {'Cardinality': 'ZeroOrOne',
                      'RequiredContextCapabilities': 'EventTarget'}}


def const(value):
    return {'kind': 'const', 'value': {'Value': value}}


def counter(counter_id):
    return {'kind': 'combatantCounter',
            'value': {'Selector': sel_source(), 'CounterId': counter_id}}


def damage(amount, target='event'):
    return {'kind': 'node.dealDamage',
            'value': {'TargetSelector': sel_event() if target == 'event' else sel_source(),
                      'Amount': const(amount), 'ResultKey': None, 'IgnoresBlock': False,
                      'Element': None}}


def block(amount):
    return {'kind': 'node.gainBlock',
            'value': {'TargetSelector': sel_source(), 'Amount': const(amount),
                      'ResultKey': None}}


def status(definition, stacks):
    return {'kind': 'node.applyStatus',
            'value': {'TargetSelector': sel_event(), 'StatusDefinitionId': ident(definition),
                      'Stacks': const(stacks), 'Duration': None, 'ResultKey': None}}


def set_counter(counter_id, amount, relative=False):
    return {'kind': 'node.setCombatantCounter',
            'value': {'TargetSelector': sel_source(), 'CounterId': ident(counter_id),
                      'Amount': const(amount) if isinstance(amount, int) else amount,
                      'Relative': relative}}


def history(move):
    """`prev_move = last_move; last_move = move` —— 与既有怪物同一套记账（§195.5）。"""
    return [set_counter('prev_move', counter('last_move')),
            set_counter('last_move', move)]


def program(children):
    return {'Id': ident('(unnamed)'),
            'Root': {'kind': 'node.sequence', 'value': {'Children': children}},
            'MaxNodeDepth': 64, 'MaxProgramSteps': 1024}


def action(action_id, name, intent_kind, label, children, asc_children=None, asc_min=2):
    row = {
        'Id': action_id,
        'PackageId': 'sts',
        'NameKey': name,
        'DescriptionKey': label,
        'Intent': {'Kind': intent_kind, 'Label': label},
        'Program': program(children),
    }
    if asc_children is not None:
        row['ProgramAsc'] = [{'AscensionMin': asc_min, 'Program': program(asc_children)}]
    return row


def rule(conditions, priority, action_id=None, choice=None):
    row = {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': conditions}},
           'Priority': priority}
    if action_id is not None:
        row['Action'] = ident(action_id)
    if choice is not None:
        row['Choice'] = [{'Action': ident(a), 'Weight': w} for a, w in choice]
    return row


def round_is(n):
    return {'kind': 'intent.round', 'value': {'Op': 'Equal', 'Round': n}}


def last_move_is(n):
    return {'kind': 'intent.selfHasCounter',
            'value': {'Counter': ident('last_move'), 'Op': 'Equal', 'Value': n}}


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    monsters = {m['Id']: m for m in doc['Monsters']}
    actions = {a['Id']: a for a in doc['EnemyActions']}
    encounters = {e['Id']['Value']: e for e in doc['Encounters']}

    # ── 1. `enc_byrds` 修成 3 只 ────────────────────────────────────────────────────────────
    byrds = encounters['enc_byrds']
    assert len(byrds['Enemies']) == 1, len(byrds['Enemies'])
    template = byrds['Enemies'][0]
    byrds['Enemies'] = [dict(template, Position=None) for _ in range(3)]

    # ── 2. `spheric_guardian` 的四招 ───────────────────────────────────────────────────────
    # wiki：Activate 得 25 Block；Debuff Attack 10 伤害 + 5 Frail；Slam 10×2；Harden 10 伤害
    # + 15 Block。A2 起伤害 +1（与既有怪物同一条升档规矩）。
    new_actions = [
        action('spheric_guardian.activate', 'Activate', 'Defend', 'Activate — 25 Block',
               [block(25)] + history(1)),
        action('spheric_guardian.debuff_attack', 'Debuff Attack', 'Attack',
               'Debuff Attack — 10 damage, 5 Frail',
               [damage(10), status('standard.frail', 5)] + history(2),
               asc_children=[damage(11), status('standard.frail', 5)] + history(2)),
        action('spheric_guardian.slam', 'Slam', 'Attack', 'Slam — 10×2 damage',
               [damage(10), damage(10)] + history(3),
               asc_children=[damage(11), damage(11)] + history(3)),
        action('spheric_guardian.harden', 'Harden', 'Attack', 'Harden — 10 damage, 15 Block',
               [damage(10), block(15)] + history(4),
               asc_children=[damage(11), block(15)] + history(4)),
    ]
    for row in new_actions:
        assert row['Id'] not in actions, row['Id']

    spheric_rules = [
        rule([round_is(1)], 96, 'spheric_guardian.activate'),
        rule([round_is(2)], 95, 'spheric_guardian.debuff_attack'),
        # 之后 Slam / Harden 交替（`last_move` 记账，与 snecko 同一条）。
        rule([last_move_is(3)], 90, 'spheric_guardian.harden'),
        rule([last_move_is(4)], 89, 'spheric_guardian.slam'),
        rule([], 10, 'spheric_guardian.slam'),
    ]
    monster = {
        'Id': 'spheric_guardian',
        'NameKey': 'Spheric Guardian',
        'HpMin': 20,
        'HpMax': 20,
        'MaxHealth': 20,
        # wiki `Powers`：Artifact 3 / Block 40 / Barricade —— Block 走 encounter 的
        # `StartingBlock`（§208），另外两条是状态。
        'Actions': [ident('spheric_guardian.activate'),
                    ident('spheric_guardian.debuff_attack'),
                    ident('spheric_guardian.slam'),
                    ident('spheric_guardian.harden')],
        'StartingStatuses': [
            {'StatusDefinitionId': ident('standard.artifact'), 'Stacks': 3},
            {'StatusDefinitionId': ident('standard.barricade'), 'Stacks': 1},
        ],
        'IntentRules': spheric_rules,
        'Tier': 'Normal',
        'InvRef': 'wiki:The_City#Hard_Pool',
        'AiNote': ('wiki 的 `Powers` 列是 Artifact 3 / Block 40 / Barricade；Block 走'
                   ' `StartingBlock`（§208），不是状态。模式：Activate → Debuff Attack → '
                   'Slam/Harden 交替（§311）。'),
        'Counters': [],
        'Spawn': True,
    }
    assert monster['Id'] not in monsters
    monsters[monster['Id']] = monster

    # ── 3. 六个新遭遇（enemy 行从怪物表现拼）────────────────────────────────────────────
    def enemy_of(monster_id, position, max_health=None, starting_block=None):
        source = monsters[monster_id]
        row = {
            'Id': monster_id,
            'MaxHealth': source['MaxHealth'] if max_health is None else max_health,
            'Actions': source['Actions'],
            'StartingStatuses': source.get('StartingStatuses', []),
            'Position': position,
            'IntentRules': source.get('IntentRules', []),
            'DisplayName': source['NameKey'],
            'Rolls': source.get('Rolls', []),
            'Counters': source.get('Counters', []),
            'Spawn': True,
        }
        if source.get('MaxHealthAsc'):
            row['MaxHealthAsc'] = source['MaxHealthAsc']
        if starting_block is not None:
            row['StartingBlock'] = starting_block
        return row

    def encounter(encounter_id, enemies, display=None):
        return {
            'Id': enc_ident(encounter_id),
            'Enemies': enemies,
            'HeroResources': [{'Resource': ident('standard.energy'), 'Current': 3, 'Max': 3}],
            'HeroStartingStatuses': [],
            'TriggeredEffects': [],
            'HeroDisplayName': display,
            'CardsDrawnPerTurn': None,
        }

    new_encounters = [
        # Hard：Chosen and Byrds = 1 Chosen + **1** Byrd（wiki 的 Details 列）。
        encounter('enc_chosen_and_byrd',
                  [enemy_of('chosen', 0), enemy_of('byrd', 1)]),
        encounter('enc_cultist_and_chosen',
                  [enemy_of('cultist', 0), enemy_of('chosen', 1)]),
        encounter('enc_three_cultists',
                  [enemy_of('cultist', None), enemy_of('cultist', None),
                   enemy_of('cultist', None)]),
        # Hard：Shelled Parasite and Fungi。
        encounter('enc_parasite_and_fungi',
                  [enemy_of('shelled_parasite', 0), enemy_of('fungi_beast', 1)]),
        # Easy：Spheric Guardian（开局 40 Block，wiki 的 `Powers` 列）。
        encounter('enc_spheric_guardian',
                  [enemy_of('spheric_guardian', None, starting_block=40)]),
        # Hard：Sentry and Spheric Guardian。
        encounter('enc_sentry_and_spheric',
                  [enemy_of('sentry_1', 0),
                   enemy_of('spheric_guardian', 1, starting_block=40)]),
    ]
    for row in new_encounters:
        assert row['Id']['Value'] not in encounters, row['Id']['Value']

    # ── 4. `Weak2` 池：wiki 的权重（×5 保整数），缺的两条权重先不占位 ─────────────────────
    pool = [
        # Easy（wiki 权重 2）
        ('enc_spheric_guardian', 10), ('enc_chosen', 10),
        ('enc_shelled_parasite', 10), ('enc_byrds', 10),
        # Hard
        ('enc_chosen_and_byrd', 10), ('enc_cultist_and_chosen', 15),
        ('enc_sentry_and_spheric', 10), ('enc_snecko', 20),
        ('enc_three_cultists', 15), ('enc_parasite_and_fungi', 15),
    ]
    doc['EncounterTables']['Weak2'] = [{'Id': i, 'Weight': w} for i, w in pool]

    # ── 5. 写回（indent=2 与盘上逐字节同一种排版 —— 实测 `dumps` == 原文）───────────────
    doc['EnemyActions'].extend(new_actions)
    doc['Monsters'].append(monster)
    doc['Encounters'].extend(new_encounters)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('monsters %d actions %d encounters %d weak2 %d'
          % (len(doc['Monsters']), len(doc['EnemyActions']), len(doc['Encounters']),
             len(doc['EncounterTables']['Weak2'])))


main()
