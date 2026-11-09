"""§316 Act 3 的普通池：按 wiki 重排，加 Shapes（Repulsor / Exploder）+ Jaw Worm Horde。

wiki（`The_Beyond` 的 Easy / Hard 两张表）：

| 池 | 遭遇 | 权重 | 组成 |
|---|---|---|---|
| Easy | 3 Darklings | 2 | 3 |
| Easy | Orb Walker | 2 | 1 |
| Easy | 3 Shapes | 2 | 从 2×Repulsor / 2×Exploder / 2×Spiker 里挑 3 |
| Hard | 4 Shapes | 1 | 同上挑 4 |
| Hard | The Maw | 1 | 1 |
| Hard | Spheric Guardian + 2 Shapes | 1 | 1 + 2 |
| Hard | 3 Darklings | 1 | 3 |
| Hard | Spire Growth | 1 | 1 |
| Hard | Transient | 1 | **不做**（见下） |
| Hard | Jaw Worm Horde | 1 | 3 |

顺手修两个**内容 bug**（与 §311 的 `enc_byrds` 同一类）：
* `enc_darklings` 只有 **2** 只 Darkling，wiki 是 **3**；
* `enc_byrds` 挂在**第三幕**池子里 —— wiki 的第三幕回归名单里没有 Byrd（它是第二幕的）。
  现在第二幕有 `enc_city_byrds`（§311 已经复制过），所以这条删掉。

⚠️ **Transient 不做**：它是"5 回合后自动消失 + 每回合伤害递增"的怪（HP 999），需要
`Fading`（层数就是时钟、到 0 自己消失）与"伤害随回合涨"两条，属于新机制；
先记在 `docs/sts-wiki-gap.md` §D.5。

⚠️ **Shapes 的"从袋子里挑"**：wiki 是"2×Repulsor / 2×Exploder / 2×Spiker 的袋子里抽 3（不放回）"，
我们的组合槽（§277 `Candidates`）是**逐槽独立按权重挑** ⇒ 会出现"3 只同一个"。记成已知偏差。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

DAZE, R_ATTACK = 1, 2
E_ATTACK, E_EXPLODE = 1, 2


def ident(value):
    return {'value': value}


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
                      'Amount': const(amount), 'ResultKey': None,
                      'IgnoresBlock': False, 'Element': None}}


def card_to(card_id, count, zone):
    return {'kind': 'node.createCardInstance',
            'value': {'CardDefinitionId': ident(card_id), 'Count': const(count),
                      'TargetSelector': sel_event(), 'ToZone': zone, 'ResultKey': None}}


def destroy_self():
    return {'kind': 'node.destroyCombatant', 'value': {'TargetSelector': sel_source()}}


def set_counter(counter_id, amount, relative=False):
    return {'kind': 'node.setCombatantCounter',
            'value': {'TargetSelector': sel_source(), 'CounterId': ident(counter_id),
                      'Amount': amount if isinstance(amount, dict) else const(amount),
                      'Relative': relative}}


def history(move):
    return [set_counter('prev_move', counter('last_move')),
            set_counter('last_move', move)]


def sequence(children):
    return {'kind': 'node.sequence', 'value': {'Children': children}}


def program(root):
    return {'Id': ident('(unnamed)'), 'Root': root, 'MaxNodeDepth': 64, 'MaxProgramSteps': 1024}


def action(action_id, name, intent_kind, label, root, asc=()):
    row = {'Id': action_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': label,
           'Intent': {'Kind': intent_kind, 'Label': label}, 'Program': program(root)}
    if asc:
        row['ProgramAsc'] = [{'AscensionMin': level, 'Program': program(root_at)}
                             for level, root_at in asc]
    return row


def rule(conditions, priority, action_id=None, choice=None):
    row = {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': conditions}},
           'Priority': priority}
    if action_id is not None:
        row['Action'] = ident(action_id)
    if choice is not None:
        row['Choice'] = [{'Action': ident(a), 'Weight': w} for a, w in choice]
    return row


def last_move_is(n):
    return {'kind': 'intent.selfHasCounter',
            'value': {'Counter': ident('last_move'), 'Op': 'Equal', 'Value': n}}


def round_at_most(n):
    return {'kind': 'intent.round', 'value': {'Op': 'LessOrEqual', 'Round': n}}


def enemy_row(monster, position=None):
    row = {
        'Id': monster['Id'],
        'MaxHealth': monster['MaxHealth'],
        'Actions': monster['Actions'],
        'StartingStatuses': monster.get('StartingStatuses', []),
        'Position': position,
        'IntentRules': monster['IntentRules'],
        'DisplayName': monster['NameKey'],
        'Rolls': [],
        'Counters': [],
        'Spawn': True,
    }
    if monster.get('MaxHealthAsc'):
        row['MaxHealthAsc'] = monster['MaxHealthAsc']
    return row


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    monsters = {m['Id']: m for m in doc['Monsters']}
    assert 'repulsor' not in monsters and 'exploder' not in monsters

    # ── 1. Repulsor / Exploder ────────────────────────────────────────────────────────────
    repulsor_actions = [
        # Daze：往**抽牌堆**塞 2 张 Dazed（wiki 原话 "into your draw pile"）。
        action('repulsor.daze', 'Daze', 'Debuff', 'Daze — 2 Dazed into your draw pile',
               sequence([card_to('dazed', 2, 'DrawPile')] + history(DAZE))),
        action('repulsor.attack', 'Attack', 'Attack', 'Attack - 11 damage',
               sequence([damage(11)] + history(R_ATTACK)),
               asc=[(2, sequence([damage(13)] + history(R_ATTACK)))]),
    ]
    repulsor_rules = [
        # "Cannot use Attack twice in a row" —— 上一次是 Attack ⇒ 这回合只能 Daze。
        rule([last_move_is(R_ATTACK)], 95, 'repulsor.daze'),
        rule([], 10, choice=[('repulsor.daze', 80), ('repulsor.attack', 20)]),
    ]
    repulsor = {
        'Id': 'repulsor',
        'NameKey': 'Repulsor',
        'HpMin': 29,
        'HpMax': 35,
        'MaxHealth': 29,
        'MaxHealthAsc': [{'AscensionMin': 7, 'MaxHealth': 31}],
        'Actions': [ident('repulsor.daze'), ident('repulsor.attack')],
        'StartingStatuses': [],
        'IntentRules': repulsor_rules,
        'Tier': 'Normal',
        'InvRef': 'wiki:Shapes#Repulsor',
        'AiNote': ('wiki：HP 29-35（A7 31-38）；Daze 往抽牌堆塞 2 张 Dazed / Attack 11（A2 13）；'
                   '80% Daze、20% Attack，且 Attack 不能连两次（§316）。'),
        'Counters': [],
        'Spawn': True,
    }

    exploder_actions = [
        action('exploder.attack', 'Attack', 'Attack', 'Attack - 9 damage',
               sequence([damage(9)] + history(E_ATTACK)),
               asc=[(2, sequence([damage(11)] + history(E_ATTACK)))]),
        # Explode：30 点伤害后**自己死**（wiki："Deals 30 damage. Dies."）。
        action('exploder.explode', 'Explode', 'Unknown', 'Explode - 30 damage, dies',
               sequence([damage(30), destroy_self()] + history(E_EXPLODE))),
    ]
    exploder_rules = [
        # "Always uses this pattern: Attack, Attack, Explode" ⇒ 前两回合打，第三回合炸。
        rule([round_at_most(2)], 90, 'exploder.attack'),
        rule([], 80, 'exploder.explode'),
    ]
    exploder = {
        'Id': 'exploder',
        'NameKey': 'Exploder',
        'HpMin': 30,
        'HpMax': 30,
        'MaxHealth': 30,
        'Actions': [ident('exploder.attack'), ident('exploder.explode')],
        'StartingStatuses': [],
        'IntentRules': exploder_rules,
        'Tier': 'Normal',
        'InvRef': 'wiki:Shapes#Exploder',
        'AiNote': ('wiki：HP **30**（A7 那列是 30-35，下界仍是 30 ⇒ 不钉升阶行）；'
                   '固定 Attack / Attack / Explode（9 点，A2 11；爆炸 30 点后自己死）。'
                   '"Explosive 3" 这条 power 不单独建模 —— 固定序列就是它的可观察行为（§316）。'),
        'Counters': [],
        'Spawn': True,
    }

    # ── 2. 遭遇 ──────────────────────────────────────────────────────────────────────────
    def find(eid):
        return next(e for e in doc['Encounters'] if e['Id']['Value'] == eid)

    # 2a. `enc_darklings` 修成 3 只，并给硬池克隆一条（内核要求"一条遭遇只属于一个池"）。
    darklings = find('enc_darklings')
    assert len(darklings['Enemies']) == 2
    template = darklings['Enemies'][0]
    darklings['Enemies'] = [dict(template, Position=None) for _ in range(3)]
    hard_darklings = json.loads(json.dumps(darklings))
    hard_darklings['Id'] = {'Value': 'enc_darklings_hard'}

    # 2b. Jaw Worm Horde（3 只，wiki 的 Hard 池）。
    jaw = find('enc_jaw_worm')
    jaw_enemy = json.loads(json.dumps(jaw['Enemies'][0]))
    horde = {
        'Id': {'Value': 'enc_jaw_worm_horde'},
        'Enemies': [dict(jaw_enemy, Position=None) for _ in range(3)],
        'HeroResources': [{'Resource': ident('standard.energy'), 'Current': 3, 'Max': 3}],
        'HeroStartingStatuses': [],
        'TriggeredEffects': [],
        'HeroDisplayName': None,
        'CardsDrawnPerTurn': None,
    }

    # 2c. Shapes：组合槽（§277）。每个槽的候选是三条**完整的敌人记录**。
    shapes = [repulsor, exploder, monsters['spiker']]

    def shape_slot(position):
        return {
            'Position': position,
            'Candidates': [enemy_row(monster) for monster in shapes],
        }

    def encounter(encounter_id, enemies):
        return {
            'Id': {'Value': encounter_id},
            'Enemies': enemies,
            'HeroResources': [{'Resource': ident('standard.energy'), 'Current': 3, 'Max': 3}],
            'HeroStartingStatuses': [],
            'TriggeredEffects': [],
            'HeroDisplayName': None,
            'CardsDrawnPerTurn': None,
        }

    spheric = find('enc_spheric_guardian')['Enemies'][0]
    new_encounters = [
        hard_darklings,
        horde,
        encounter('enc_three_shapes', [shape_slot(0), shape_slot(1), shape_slot(2)]),
        encounter('enc_four_shapes',
                  [shape_slot(0), shape_slot(1), shape_slot(2), shape_slot(3)]),
        encounter('enc_spheric_and_two_shapes',
                  [dict(spheric, Position=0), shape_slot(1), shape_slot(2)]),
    ]

    # 2d. 删掉挂在第三幕的 `enc_byrds`（第二幕已有 `enc_city_byrds`）。
    doc['Encounters'] = [e for e in doc['Encounters'] if e['Id']['Value'] != 'enc_byrds']

    # ── 3. 池子（wiki 权重 ×10：Easy 2 → 20、Hard 1 → 10）───────────────────────────────
    doc['EncounterTables']['Weak3'] = [
        {'Id': 'enc_darklings', 'Weight': 20},
        {'Id': 'enc_orb_walker', 'Weight': 20},
        {'Id': 'enc_three_shapes', 'Weight': 20},
        {'Id': 'enc_four_shapes', 'Weight': 10},
        {'Id': 'enc_maw', 'Weight': 10},
        {'Id': 'enc_spheric_and_two_shapes', 'Weight': 10},
        {'Id': 'enc_darklings_hard', 'Weight': 10},
        {'Id': 'enc_spire_growth', 'Weight': 10},
        {'Id': 'enc_jaw_worm_horde', 'Weight': 10},
    ]

    doc['EnemyActions'].extend(repulsor_actions + exploder_actions)
    doc['Monsters'].extend([repulsor, exploder])
    doc['Encounters'].extend(new_encounters)

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('monsters %d actions %d encounters %d weak3 %d'
          % (len(doc['Monsters']), len(doc['EnemyActions']), len(doc['Encounters']),
             len(doc['EncounterTables']['Weak3'])))


main()
