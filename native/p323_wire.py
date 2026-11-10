"""§323 收尾：把三名 Bandits 接进内核的事件池跳表，并补 `INV_ACTIONS` / 两条变体事实 / 计数。

内容门最后指出的三件事：
1. `EncounterTables.MaskedBandits` 内核里**没有 hop 拼写** —— 事件池名在
   `rd-core::content` 的两张跳表里是**字面量**（`MysteriousSphere` 就是那样登记的），
   所以加一条与它同形的分支（这不是"声明成文档"，是"真的接上"）。
2. `INV_ACTIONS` 是 wiki 数字的独立副本，七条新动作要逐条钉住。
3. `repeat` 摊平写成 `('repeat', n, ...)`，`-2 敏捷` 是 `modify`（不是 `status`）。
"""

import io

CONTENT_RS = 'kernel/rd-core/src/content.rs'
CHECK = 'native/sts_content_check.py'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(CONTENT_RS, encoding='utf-8').read()
t = sub(t, """            "MysteriousSphere" => "EncounterTables.MysteriousSphere",""",
        """            "MysteriousSphere" => "EncounterTables.MysteriousSphere",
            // §323：`Masked Bandits` 的 `[Fight!]` 用事件自己的池（三名 bandit）。
            "MaskedBandits" => "EncounterTables.MaskedBandits",""",
        'hop spelling', count=2)
io.open(CONTENT_RS, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-core hop table: MaskedBandits')

t = io.open(CHECK, encoding='utf-8').read()

# ── INV_ACTIONS：七条新动作 ─────────────────────────────────────────────────────
t = sub(t, """INV_ACTIONS = {""",
        """INV_ACTIONS = {
    # §323：Masked Bandits。Pointy 5×2；Romeo Mock 什么都不做 → Agonizing（10 + 2 Weak）/
    # Cross（15）交替；Bear Bear Hug（-2 敏捷）→ Lunge（9 + 9 格挡）/ Maul（18）交替。
    "pointy.special": ("Attack", [("repeat", 2, "damage", 5, "event")]),
    "romeo.mock": ("Unknown", []),
    "romeo.agonizing_slash": ("Attack", [("damage", 10, "event"),
                                         ("status", "standard.weak", 2, "event")]),
    "romeo.cross_slash": ("Attack", [("damage", 15, "event")]),
    "bear.bear_hug": ("Debuff", [("modify", "standard.dexterity", -2, "event")]),
    "bear.lunge": ("AttackDefend", [("damage", 9, "event"), ("block", 9, "source")]),
    "bear.maul": ("Attack", [("damage", 18, "event")]),""",
        'INV_ACTIONS')

# ── 变体事实：repeat / modify 的正确摊平写法 ───────────────────────────────────
t = sub(t, """    'pointy.special': [(2, [('damage', 6, 'event'), ('damage', 6, 'event')])],""",
        """    'pointy.special': [(2, [('repeat', 2, 'damage', 6, 'event')])],""",
        'pointy facts')
t = sub(t, """    'bear.bear_hug': [(17, [('status', 'standard.dexterity', -4, 'event')])],""",
        """    'bear.bear_hug': [(17, [('modify', 'standard.dexterity', -4, 'event')])],""",
        'bear hug facts')

# ── 计数 ────────────────────────────────────────────────────────────────────────
t = sub(t, """    "monsters": 58,""",
        """    # §323: +3（Masked Bandits 的 Pointy / Romeo / Bear —— 册外敌人）。
    "monsters": 61,""",
        'monster count')
io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(t)
print('sts_content_check: INV_ACTIONS / facts / counts')
