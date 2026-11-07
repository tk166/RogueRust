"""§257 五个精英的**机制**收尾（内容侧）。

## 一、先修两处阈值错

`EACT.ProgramAsc` 的阈值规律在整个镜像里是干净的：普通怪 `A2`/`A17`、精英 `A3`/`A18`、
Boss `A4`/`A19`（Boss 另有 `A9` 档）。逐个怪数下来，**只有两个例外**，都是 +1：

| 怪 | 现在 | 应为（wiki 上标） |
|---|---|---|
| `nemesis.tri_attack` | A4 → 7×3 | **A3** |
| `nemesis.tri_burn` | A19 → 5 张 | **A18** |
| `reptomancer.big_bite` | A4 → 34 | **A3** |
| `reptomancer.snake_strike` | A4 → 16×2 | **A3** |
| `reptomancer.spawn_dagger` | A19 → 召 2 把 | **A18** |

数值本身都对，只是门槛错了一级 —— 这种错**在 A0 跑不出来**，只在 A3/A18 的边界上错一格。

## 二、`Lagavulin` 的"受伤即警醒"（wiki 的另一半）

wiki 原话：

> If it takes any damage, it will be stunned for one turn and then proceed to attack. If three turns
> pass without any damage taken, it will awake and immediately begin attacking. Once awoken, its
> Metallicize will be removed.

载体（**零内核改动**）：状态 `standard.lagavulin_asleep` 挂在它身上，两条触发器
—— `DamageTaken`（bearer = 挨打的那个，`eventAmount` = **实际掉血**）与 `TurnStarted`
（`roundNumber > 3`）。醒来的动作是三件事：摘掉 Metallicize、置 `lagavulin_woken`、
摘掉自己（状态一旦摘掉，触发器就不再响，天然只醒一次）。

"被打了才眩晕"这一点**必须**靠 `lagavulin_woken` 这条计数器区分：自己睡满 3 回合醒来
**不眩晕**、直接攻击（`AiNote` 早就写了这条，这里只是把它补成完整事实）。

顺带修掉**普通出招顺序**：原来 `Actions` 只有 `[siphon_soul, attack]`，靠 `(round-1) % 2`
轮流，醒来之后是 attack / siphon / attack / siphon —— 而 wiki 是 **Attack、Attack、Siphon Soul**。
改成三档计数器 `lagavulin_step`（0/1/2）后每次都 `(step+1) % 3`。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


# ---------------------------------------------------------------- 节点工厂
def n(kind, **value):
    return {"kind": "node." + kind, "value": value}


def const(v):
    return {"kind": "const", "value": {"Value": v}}


def sel_source():
    return {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def sel_target():
    return {"kind": "sel.eventTarget",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}


def seq(*children):
    return n("sequence", Children=list(children))


def damage(amount, target=None):
    return n("dealDamage", TargetSelector=target or sel_target(), Amount=amount,
             ResultKey=None, IgnoresBlock=False, Element=None)


def status(definition_id, stacks, target=None):
    return n("applyStatus", TargetSelector=target or sel_target(),
             StatusDefinitionId={"value": definition_id}, Stacks=stacks)


def modify(definition_id, delta, target=None):
    return n("modifyStatusStacks", TargetSelector=target or sel_target(),
             StatusDefinitionId={"value": definition_id}, Delta=delta, ResultKey=None)


def counter_get(counter, target=None):
    return {"kind": "combatantCounter", "value": {"Selector": target or sel_source(),
                                                  "CounterId": counter}}


def counter_set(counter, amount, relative, target=None):
    return n("setCombatantCounter", TargetSelector=target or sel_source(),
             CounterId={"value": counter}, Amount=amount, Relative=relative)


def repeat(count, body):
    return n("repeat", Count=count, Body=body, MaxCount=32)


def conditional(condition, then, otherwise=None):
    return n("conditional", Condition=condition, Then=then, Else=otherwise)


def compare(left, op, right):
    return {"kind": "compare", "value": {"Left": left, "Right": right, "Op": op}}


def add(left, right):
    return {"kind": "add", "value": {"Left": left, "Right": right}}


def remainder(dividend, divisor):
    return {"kind": "remainder", "value": {"Left": dividend, "Right": divisor}}


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def bookkeeping(code):
    """每招收尾：`prev_move ← last_move`、`last_move ← code`。

    这是镜像里 85 条动作的既有约定（`the_collector.fireball` / `slaver_red.scrape` 都这么写）。
    **必须先抄 `last_move` 再写 `last_move`** —— 顺序反了 `prev_move` 永远等于 `code`，
    "不连续两次"的规则就会变成"永远禁止"或"永远允许"。
    """
    return [
        counter_set("prev_move", counter_get("last_move"), relative=False),
        counter_set("last_move", const(code), relative=False),
    ]


def with_asc(variants):
    """`ProgramAsc`：`[(AscensionMin, root), …]`。"""
    return [{"AscensionMin": a, "Program": program(root)} for a, root in variants]


def action_programs(entry, base_root, asc_variants):
    """替换一条 EACT 的节目；**每个升阶变体都保留自己的本体**。"""
    entry['Program'] = program(base_root)
    if asc_variants:
        entry['ProgramAsc'] = with_asc(asc_variants)
    else:
        entry.pop('ProgramAsc', None)


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    monsters = {row['Id']: row for row in doc['Monsters']}
    actions = {row['Id']: row for row in doc['EnemyActions']}

    # ============================================================ 一、阈值修正
    fixes = {
        ('nemesis.tri_attack', 4): 3,
        ('nemesis.tri_burn', 19): 18,
        ('reptomancer.big_bite', 4): 3,
        ('reptomancer.snake_strike', 4): 3,
        ('reptomancer.spawn_dagger', 19): 18,
    }
    for (action_id, old), new in fixes.items():
        variants = actions[action_id].get('ProgramAsc') or []
        hits = [v for v in variants if v['AscensionMin'] == old]
        assert len(hits) == 1, (action_id, old, len(hits))
        hits[0]['AscensionMin'] = new
        print('threshold %-30s A%d -> A%d' % (action_id, old, new))

    # ============================================================ 二、Lagavulin
    # 出招顺序：Attack、Attack、Siphon Soul（`lagavulin_step` 0/1/2）。
    step_advance = counter_set(
        "lagavulin_step",
        remainder(add(counter_get("lagavulin_step"), const(1)), const(3)),
        relative=False,
    )
    attack_base = seq(damage(const(18)), step_advance)
    attack_a3 = seq(damage(const(20)), step_advance)
    action_programs(actions['lagavulin.attack'], attack_base, [(3, attack_a3)])

    siphon_base = seq(
        modify("standard.strength", const(-1)),
        modify("standard.dexterity", const(-1)),
        step_advance,
    )
    siphon_a18 = seq(
        modify("standard.strength", const(-2)),
        modify("standard.dexterity", const(-2)),
        step_advance,
    )
    action_programs(actions['lagavulin.siphon_soul'], siphon_base, [(18, siphon_a18)])

    # 醒来那一回合：什么都不做，只把"刚醒"的记号清掉。
    actions['lagavulin.stunned'] = {
        'Id': 'lagavulin.stunned',
        'Program': program(seq(counter_set("lagavulin_woken", const(0), relative=False))),
    }

    # 睡眠状态：两条触发器（挨打 / 自己睡满 3 回合）。
    wake = seq(
        modify("standard.metallicize", const(-8), target=sel_source()),
        counter_set("lagavulin_woken", const(1), relative=False, target=sel_source()),
        modify("standard.lagavulin_asleep", const(-1), target=sel_source()),
    )
    self_wake = seq(
        modify("standard.metallicize", const(-8), target=sel_source()),
        modify("standard.lagavulin_asleep", const(-1), target=sel_source()),
    )
    asleep = {
        'Id': 'standard.lagavulin_asleep', 'PackageId': 'sts',
        'NameKey': 'Asleep',
        'DescriptionKey': 'Lagavulin is asleep. Taking damage wakes it and stuns it for a turn.',
        'Polarity': 'Debuff', 'UsesStacks': True, 'UsesDuration': False, 'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance', 'Tags': ['debuff'],
        'PassiveModifiers': [],
        'Triggers': [
            {
                'Event': 'DamageTaken',
                # `eventAmount` 是**实际掉血**（不是"被打了"）：打在格挡上的那一击不算吵醒它。
                'Program': program(conditional(
                    compare({"kind": "eventAmount", "value": {}}, "Greater", const(0)),
                    wake)),
            },
            {
                'Event': 'TurnStarted',
                # 自己睡满三回合：第 4 回合开始时醒来，**不眩晕**（`lagavulin_woken` 不置）。
                'Program': program(conditional(
                    compare({"kind": "roundNumber", "value": {}}, "Greater", const(3)),
                    self_wake)),
            },
        ],
    }
    if not any(s['Id'] == asleep['Id'] for s in doc['Statuses']):
        doc['Statuses'].append(asleep)

    lagavulin = monsters['lagavulin']
    lagavulin['Actions'] = [{'value': a} for a in
                            ('lagavulin.siphon_soul', 'lagavulin.attack',
                             'lagavulin.sleep', 'lagavulin.stunned')]
    lagavulin['StartingStatuses'] = [
        {'StatusDefinitionId': {'value': 'standard.metallicize'}, 'Stacks': 8},
        {'StatusDefinitionId': {'value': 'standard.lagavulin_asleep'}, 'Stacks': 1},
    ]
    lagavulin['IntentRules'] = [
        # 被吵醒 ⇒ 眩晕一回合（比睡觉与出招都高）。
        {'Condition': {'kind': 'intent.selfHasCounter',
                       'value': {'Counter': {'value': 'lagavulin_woken'},
                                 'Op': 'GreaterOrEqual', 'Value': 1}},
         'Action': {'value': 'lagavulin.stunned'}, 'Priority': 90},
        # 睡觉：**同时**要求"还是前 3 回合"与"身上还挂着 asleep"（被打醒后不许再睡）。
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': [
            {'kind': 'intent.round', 'value': {'Op': 'LessOrEqual', 'Round': 3}},
            {'kind': 'intent.selfHasStatus',
             'value': {'Status': {'value': 'standard.lagavulin_asleep'}, 'MinStacks': 1}}]}},
         'Action': {'value': 'lagavulin.sleep'}, 'Priority': 60},
        {'Condition': {'kind': 'intent.selfHasCounter',
                       'value': {'Counter': {'value': 'lagavulin_step'},
                                 'Op': 'Equal', 'Value': 0}},
         'Action': {'value': 'lagavulin.attack'}, 'Priority': 50},
        {'Condition': {'kind': 'intent.selfHasCounter',
                       'value': {'Counter': {'value': 'lagavulin_step'},
                                 'Op': 'Equal', 'Value': 1}},
         'Action': {'value': 'lagavulin.attack'}, 'Priority': 50},
        {'Condition': {'kind': 'intent.selfHasCounter',
                       'value': {'Counter': {'value': 'lagavulin_step'},
                                 'Op': 'Equal', 'Value': 2}},
         'Action': {'value': 'lagavulin.siphon_soul'}, 'Priority': 50},
    ]
    lagavulin['AiNote'] = (
        '§257：wiki 数值（HP 109-111、Metallicize 8、Attack 18(A3:20)、Siphon Soul -1/-1(A18:-2/-2)）。'
        '三条规则：① 被**打掉血**即醒 ⇒ 摘 Metallicize + 眩晕一回合（`lagavulin_woken` 计数器，'
        '`lagavulin.stunned` 那一招清它）；② 自己睡满 3 回合（`roundNumber > 3` 的 TurnStarted 触发器）'
        '⇒ 摘 Metallicize、不眩晕、直接攻击；③ 出招顺序 Attack、Attack、Siphon Soul（`lagavulin_step` '
        '每招 (step+1)%3）。偏差：挨打后那一回合的眩晕是"整回合不做动作"，而参考是在**挨打当回合**'
        '就换意图 —— 差别只在界面那一个图标。'
    )
    print('lagavulin: wake-on-damage + self-wake + Attack/Attack/Siphon')

    # ============================================================ 三、Book of Stabbing
    book = monsters['book_of_stabbing']
    # wiki："N is equal to 2 plus the number of times Multi-Stab has been previously used" —— 原来写 3。
    multi = seq(
        repeat(add(counter_get("book_stab_hits_base"), counter_get("book_stab_uses")),
               damage(const(6))),
        counter_set("book_stab_uses", const(1), relative=True),
        *bookkeeping(1),
    )
    multi_a3 = seq(
        repeat(add(counter_get("book_stab_hits_base"), counter_get("book_stab_uses")),
               damage(const(7))),
        counter_set("book_stab_uses", const(1), relative=True),
        *bookkeeping(1),
    )
    book['Counters'] = [
        {'Key': 'book_stab_hits_base', 'Value': 2},
        # A18：连 Single Stab 也让 N 递增（wiki 的第二颗星号）。
        {'Key': 'book_stab_single_bump', 'Value': 0},
        {'Key': 'book_stab_single_bump', 'Value': 1, 'AscensionMin': 18},
    ]
    action_programs(actions['book_of_stabbing.multi_stab'], multi, [(3, multi_a3)])

    single = seq(
        damage(const(21)),
        counter_set("book_stab_uses", counter_get("book_stab_single_bump"), relative=True),
        *bookkeeping(2),
    )
    single_a3 = seq(
        damage(const(24)),
        counter_set("book_stab_uses", counter_get("book_stab_single_bump"), relative=True),
        *bookkeeping(2),
    )
    action_programs(actions['book_of_stabbing.big_stab'], single, [(3, single_a3)])
    book['IntentRules'] = [
        # 不能连用 Multi-Stab 三次（上一次与上上次都是 1）。
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': [
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': 1}},
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'prev_move'}, 'Op': 'Equal', 'Value': 1}}]}},
         'Action': {'value': 'book_of_stabbing.big_stab'}, 'Priority': 70},
        # 不能连用 Single Stab 两次。
        {'Condition': {'kind': 'intent.selfHasCounter',
                       'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': 2}},
         'Action': {'value': 'book_of_stabbing.multi_stab'}, 'Priority': 70},
        # 85% / 15%。
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': []}},
         'Priority': 10,
         'Choice': [{'Action': {'value': 'book_of_stabbing.multi_stab'}, 'Weight': 85},
                    {'Action': {'value': 'book_of_stabbing.big_stab'}, 'Weight': 15}]},
    ]
    book['AiNote'] = (
        '§257：wiki（HP 160-162 / A8 168-172、Multi-Stab 6×N / A3 7×N、Single Stab 21 / A3 24、'
        'Painful Stabs）。N = 2 + 已用次数（原来是 3，差一整下）；A18 起 Single Stab 也推进 N'
        '（`book_stab_single_bump` 计数器）。AI：85/15，不能连 Multi-Stab 三次、不能连 Single Stab 两次。'
    )
    print('book_of_stabbing: N off-by-one fixed, A18 bump, AI constraints')

    # ============================================================ 四、Nemesis
    tri = seq(damage(const(6)), damage(const(6)), damage(const(6)), *bookkeeping(1))
    tri_a3 = seq(damage(const(7)), damage(const(7)), damage(const(7)), *bookkeeping(1))
    action_programs(actions['nemesis.tri_attack'], tri, [(3, tri_a3)])

    burn = n("createCardInstance", CardDefinitionId={"value": "burn"}, Count=const(3),
             TargetSelector=sel_target(), ToZone="DiscardPile", ResultKey=None)
    burn_a18 = n("createCardInstance", CardDefinitionId={"value": "burn"}, Count=const(5),
                 TargetSelector=sel_target(), ToZone="DiscardPile", ResultKey=None)
    action_programs(actions['nemesis.tri_burn'], seq(burn, *bookkeeping(2)),
                    [(18, seq(burn_a18, *bookkeeping(2)))])

    action_programs(actions['nemesis.scythe'], seq(damage(const(45)), *bookkeeping(3)), [])

    monsters['nemesis']['IntentRules'] = [
        # 第一回合 50/50（Tri Burn 或 Tri Attack）。
        {'Condition': {'kind': 'intent.round', 'value': {'Op': 'Equal', 'Round': 1}},
         'Priority': 80,
         'Choice': [{'Action': {'value': 'nemesis.tri_burn'}, 'Weight': 50},
                    {'Action': {'value': 'nemesis.tri_attack'}, 'Weight': 50}]},
        # 不能连 Tri Attack 三次。
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': [
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': 1}},
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'prev_move'}, 'Op': 'Equal', 'Value': 1}}]}},
         'Priority': 70,
         'Choice': [{'Action': {'value': 'nemesis.tri_burn'}, 'Weight': 50},
                    {'Action': {'value': 'nemesis.scythe'}, 'Weight': 50}]},
        # 不能连 Tri Burn 两次。
        {'Condition': {'kind': 'intent.selfHasCounter',
                       'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': 2}},
         'Priority': 70,
         'Choice': [{'Action': {'value': 'nemesis.tri_attack'}, 'Weight': 54},
                    {'Action': {'value': 'nemesis.scythe'}, 'Weight': 46}]},
        # 不能连 Scythe 两次。
        {'Condition': {'kind': 'intent.selfHasCounter',
                       'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': 3}},
         'Priority': 70,
         'Choice': [{'Action': {'value': 'nemesis.tri_attack'}, 'Weight': 54},
                    {'Action': {'value': 'nemesis.tri_burn'}, 'Weight': 46}]},
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': []}},
         'Priority': 10,
         'Choice': [{'Action': {'value': 'nemesis.tri_burn'}, 'Weight': 35},
                    {'Action': {'value': 'nemesis.tri_attack'}, 'Weight': 35},
                    {'Action': {'value': 'nemesis.scythe'}, 'Weight': 30}]},
    ]
    monsters['nemesis']['AiNote'] = (
        '§257：wiki（HP 185 / A8 200、Tri Attack 6×3 / A3 7×3、Tri Burn 3 / A18 5、Scythe 45；'
        'Intangible 隔回合 = `phantom_veil`）。AI 三条禁令：Tri Burn 与 Scythe 各不连续两次、'
        'Tri Attack 不连续三次；首回合 Tri Burn/Tri Attack 各 50%。'
        '⚠️ 阈值原来是 A4/A19（Boss 的档），已改回 A3/A18。'
    )
    print('nemesis: AI constraints + threshold fix')

    # ============================================================ 五、Reptomancer
    spawn = seq(n("createCombatant", DefinitionId="dagger", TeamId="enemy",
                  Health=const(22)), *bookkeeping(1))
    spawn_a18 = seq(n("createCombatant", DefinitionId="dagger", TeamId="enemy",
                      Health=const(22)),
                    n("createCombatant", DefinitionId="dagger", TeamId="enemy",
                      Health=const(22)),
                    *bookkeeping(1))
    action_programs(actions['reptomancer.spawn_dagger'], spawn, [(18, spawn_a18)])

    bite = seq(damage(const(30)), *bookkeeping(2))
    bite_a3 = seq(damage(const(34)), *bookkeeping(2))
    action_programs(actions['reptomancer.big_bite'], bite, [(3, bite_a3)])

    snake = seq(damage(const(13)), damage(const(13)), status("standard.weak", const(1)),
                *bookkeeping(3))
    snake_a3 = seq(damage(const(16)), damage(const(16)), status("standard.weak", const(1)),
                   *bookkeeping(3))
    action_programs(actions['reptomancer.snake_strike'], snake, [(3, snake_a3)])

    monsters['reptomancer']['IntentRules'] = [
        # 匕首已满 4 把（Reptomancer + 4 = 5 个活着的敌人）⇒ 改打 Snake Strike。
        {'Condition': {'kind': 'intent.enemyAliveCount',
                       'value': {'Op': 'GreaterOrEqual', 'Value': 5}},
         'Action': {'value': 'reptomancer.snake_strike'}, 'Priority': 90},
        # 永远以 Spawn Dagger 开场。
        {'Condition': {'kind': 'intent.round', 'value': {'Op': 'Equal', 'Round': 1}},
         'Action': {'value': 'reptomancer.spawn_dagger'}, 'Priority': 85},
        # 不能连 Spawn Dagger 三次。
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': [
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': 1}},
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'prev_move'}, 'Op': 'Equal', 'Value': 1}}]}},
         'Priority': 70,
         'Choice': [{'Action': {'value': 'reptomancer.snake_strike'}, 'Weight': 50},
                    {'Action': {'value': 'reptomancer.big_bite'}, 'Weight': 50}]},
        # 不能连 Big Bite 两次。
        {'Condition': {'kind': 'intent.selfHasCounter',
                       'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': 2}},
         'Priority': 70,
         'Choice': [{'Action': {'value': 'reptomancer.snake_strike'}, 'Weight': 50},
                    {'Action': {'value': 'reptomancer.spawn_dagger'}, 'Weight': 50}]},
        # 不能连 Snake Strike 两次。
        {'Condition': {'kind': 'intent.selfHasCounter',
                       'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': 3}},
         'Priority': 70,
         'Choice': [{'Action': {'value': 'reptomancer.big_bite'}, 'Weight': 50},
                    {'Action': {'value': 'reptomancer.spawn_dagger'}, 'Weight': 50}]},
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': []}},
         'Priority': 10,
         'Choice': [{'Action': {'value': 'reptomancer.snake_strike'}, 'Weight': 34},
                    {'Action': {'value': 'reptomancer.big_bite'}, 'Weight': 33},
                    {'Action': {'value': 'reptomancer.spawn_dagger'}, 'Weight': 33}]},
    ]
    monsters['reptomancer']['AiNote'] = (
        '§257：wiki（HP 180-190 / A8 190-200、Spawn Dagger 1 / A18 2、上限 4、Big Bite 30 / A3 34、'
        'Snake Strike 13×2+Weak / A3 16×2）。上限用 `intent.enemyAliveCount >= 5`（§257 的新条件）'
        '在老招式选择层判掉，所以意图图标也是 Snake Strike。⚠️ 阈值原来是 A4/A19，已改回 A3/A18。'
    )
    print('reptomancer: dagger cap + A18 double spawn + AI constraints')

    # ============================================================ 六、Blue Slaver
    stab = seq(damage(const(12)), *bookkeeping(1))
    stab_a2 = seq(damage(const(13)), *bookkeeping(1))
    action_programs(actions['blue_slaver.stab'], stab, [(2, stab_a2)])

    rake = seq(damage(const(7)), status("standard.weak", const(1)), *bookkeeping(2))
    rake_a2 = seq(damage(const(8)), status("standard.weak", const(1)), *bookkeeping(2))
    rake_a17 = seq(damage(const(8)), status("standard.weak", const(2)), *bookkeeping(2))
    action_programs(actions['blue_slaver.rake'], rake, [(2, rake_a2), (17, rake_a17)])

    monsters['blue_slaver']['IntentRules'] = [
        # A17：绝不连用 Rake 两次。
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': [
            {'kind': 'intent.ascensionAtLeast', 'value': {'Value': 17}},
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': 2}}]}},
         'Action': {'value': 'blue_slaver.stab'}, 'Priority': 70},
        # 任何等级：同一种攻击不能连用三次。
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': [
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': 1}},
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'prev_move'}, 'Op': 'Equal', 'Value': 1}}]}},
         'Action': {'value': 'blue_slaver.rake'}, 'Priority': 60},
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': [
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': 2}},
            {'kind': 'intent.selfHasCounter',
             'value': {'Counter': {'value': 'prev_move'}, 'Op': 'Equal', 'Value': 2}}]}},
         'Action': {'value': 'blue_slaver.stab'}, 'Priority': 60},
        {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': []}},
         'Priority': 10,
         'Choice': [{'Action': {'value': 'blue_slaver.stab'}, 'Weight': 60},
                    {'Action': {'value': 'blue_slaver.rake'}, 'Weight': 40}]},
    ]
    monsters['blue_slaver']['AiNote'] = (
        '§257：wiki（HP 46-50 / A7 48-52、Stab 12/A2 13、Rake 7+Weak1 → A2 8、A17 Weak 2）。'
        'AI：60/40；同一种攻击不连用三次；A17 起绝不连用 Rake 两次。'
        '⚠️ 之前蓝皮强盗身上挂着 `standard.time_warp`（时间吞噬者的能力），已删。'
    )
    print('blue_slaver: A17 rule + A17 weak variant')

    # ---------------------------------------------------------------- 写回
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content written: statuses %d, enemy_actions %d'
          % (len(doc['Statuses']), len(doc['EnemyActions'])))


main()
