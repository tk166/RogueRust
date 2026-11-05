"""§216 checker: pin the new operation, drop Slow's trigger expectation, add INV_TIME_VARIABLES.

`INV_TIME_VARIABLES` exists because of the review's P1-B: the bug was not a missing number, it was
"the expression uses a variable with the right shape and the wrong meaning". Pinning the *facts*
(`repeat(expr divide) damage 5`) cannot see that — `turnNumber` and `roundNumber` produce identical
fact tuples. So the table pins **which time variable each program reads**, exhaustively: a program
that starts reading one, or switches, turns the gate red.
"""
import io

P = 'native/sts_content_check.py'
text = io.open(P, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


# 1) 运算名换了：Slow 的因子读的是本回合牌数，不是层数（§216）。
one('''    "standard.slow": [("DamageReceived", "ScalePercentPerStack", 10, 150, "Direct")],''',
    '''    # §216: the factor reads `state.cards_played_this_turn`, **not** the stacks. `Slow` resets at
    # end of turn (wiki), and stacks cannot express "present with count 0" here: `modifyStatusStacks`
    # to 0 deletes the instance (reference `StatusEffects.cs:830-838`) and then the `CardPlayed`
    # trigger never fires again.
    "standard.slow": [("DamageReceived", "ScalePercentPerCardPlayedThisTurn", 10, 150, "Direct")],''',
    'INV_STATUSES slow row')

# 2) Slow 不再是"每个 CardPlayed 涨一层"，所以它退出那张触发器白名单（并且必须退出：
#    留在元组里会去查一个已经不存在的期望）。
one('''                     "standard.stasis", "standard.slow", "standard.flying",''',
    '''                     "standard.stasis", "standard.flying",''',
    'trigger whitelist tuple')
one('''                        # §198: "whenever you play a card" -- Slow grows on CardPlayed.
                        "standard.slow": ["CardPlayed"],
''',
    '''                        # §216: Slow has **no** trigger any more -- the count lives in the kernel's
                        # `cards_played_this_turn`, so it is checked by `INV_TIME_VARIABLES` and by
                        # the modifier row (`INV_STATUSES`), not by a content trigger.
''',
    'trigger whitelist entry')

# 3) 新增：每个程序读的是哪个"时间变量"（穷尽）。
one('''INV_UNWIRED = {"louse_green.bite", "louse_green.grow"}''',
    '''INV_UNWIRED = {"louse_green.bite", "louse_green.grow"}

# §216: **每个程序读哪一个"时间变量"**，穷尽。这条表是被一次真 bug 逼出来的：
# `maw.nom_nom` 用的是 `turnNumber`，而那是**一轮内的行动者序号**（`turn.rs:970` 绕回时置 1）——
# 单怪场景里 Maw 出手时它恒为 2，于是 `ceil(turn/2)` **永远是 1 击**。wiki 说的是
# "Current turn, divided by two"，指**轮次**（`roundNumber`）。
#
# ⚠️ 为什么事实表挡不住它：`INV_ACTIONS` 把这条动作钉成
# `("repeat", ("expr", "divide"), "damage", 5, "event")` —— `turnNumber` 与 `roundNumber`
# 在事实层面**一模一样**。所以这里钉的是**变量名**，两个方向都查：
#   ① 表里声明的变量必须真的出现（改了内容就红）；
#   ② 程序里出现的变量必须在表里（新写一个读时间变量的动作也红）。
# 这条表的粒度是"哪个变量"，不是"哪个节点"：`turnNumber` 与 `roundNumber` 只差一个词，
# 而它们一个是轮内序号、一个是轮次。
TIME_VARIABLES = ("turnNumber", "roundNumber")
INV_TIME_VARIABLES = {
    "maw.nom_nom": ("roundNumber",),
}''',
    'INV_TIME_VARIABLES')


# 4) 检查函数：插在 `check_intent_history` 之前（同一个"内容语义"段）。
one('''def check_intent_history(doc):''',
    '''def check_time_variables(doc):
    """§216：每个敌人动作读哪一个时间变量 —— 穷尽两个方向。

    `turnNumber` = 一轮内的行动者序号（绕回置 1）；`roundNumber` = 第几轮。两者在**事实**层面
    长得一样（都是"一个整数字段"），所以只有钉变量名才能抓住"用对了形状、用错了含义"。
    """
    seen = {}
    for action in doc["EnemyActions"]:
        names = set()
        for program in [action.get("Program")] + list(action.get("ProgramAsc") or []):
            if program:
                collect_time_variables(program["Root"], names)
        if names:
            seen[action["Id"]] = tuple(sorted(names))
    for action_id in sorted(set(seen) | set(INV_TIME_VARIABLES)):
        expected = tuple(sorted(INV_TIME_VARIABLES.get(action_id, ())))
        actual = seen.get(action_id, ())
        if expected != actual:
            fail("action." + action_id,
                 "time variables %s, inventory says %s" % (list(actual), list(expected)))
    return len(INV_TIME_VARIABLES)


def collect_time_variables(node, out):
    if isinstance(node, dict):
        kind = node.get("kind")
        if kind in TIME_VARIABLES:
            out.add(kind)
        for value in node.values():
            collect_time_variables(value, out)
    elif isinstance(node, list):
        for value in node:
            collect_time_variables(value, out)


def check_intent_history(doc):''',
    'check_time_variables')

io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('checker patched (3 spots)')
