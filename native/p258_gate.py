"""§258：内容门的独立副本跟着「虱子一族 + 两条 A 数据」一起更新。

内容门这一次报了 10 条，每一条都是**它该报的**：
* `louse_green.bite` 的事实从 `damage 6` 变成 `damage ← roll.bite`（这正是修的机制）；
* `louse_green.grow` 不存在了（绿虱子没有 Grow）；
* `slaver_red.scrape` / `time_eater.head_slam` 多了档位；
* 绿虱子现在有 `Rolls`（`roll.wired` 那条提示要把它从 `INV_UNWIRED` 里**删掉**）；
* 新遭遇 `enc_two_louses` 要进 1 幕弱池的清单与敌人明细。
"""
import io

CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'

EDITS = [
    # ① 名册：红虱子两招、绿虱子两招
    ('    ("louse_red", 10, 15, ["louse_red.bite", "louse_red.grow", "louse_red.spit_web"]),\n'
     '    ("louse_green", 11, 16, ["louse_green.bite", "louse_green.grow"]),',
     '    # §258: the two louses had each other\'s move -- wiki says Red = Bite + Grow,\n'
     '    # Green = Bite + Spit Web.\n'
     '    ("louse_red", 10, 15, ["louse_red.bite", "louse_red.grow"]),\n'
     '    ("louse_green", 11, 16, ["louse_green.bite", "louse_green.spit_web"]),'),
    # ② 动作事实
    ('    "louse_red.spit_web": ("Debuff", [("status", "standard.weak", 2, "event")]),\n'
     '    "louse_green.bite": ("Attack", [("damage", 6, "event")]),\n'
     '    "louse_green.grow": ("Buff", [("status", "standard.strength", 3, "source")]),',
     '    # §258: Spit Web is the **Green** Louse\'s move (the id used to say `louse_red`), and the\n'
     '    # green Bite is the same spawn-time roll as the red one -- not a hard-coded 6.\n'
     '    "louse_green.spit_web": ("Debuff", [("status", "standard.weak", 2, "event")]),\n'
     '    "louse_green.bite": ("Attack", [("damage", ("counter", "roll.bite", "source"), "event")]),'),
    # ③ `louse_red.bite` 的伤害本来就是 roll（表里大概写的是 counter）—— 确认过就不用动。
    # ④ asc：删掉绿虱子 Grow 的 A17 档
    ("    'louse_green.grow': [(17, [('status', 'standard.strength', 4, 'source')])],\n", ''),
    # ⑤ `louse_green.spit_web` 没有升档（wiki 只给它 2 Weak，没有上标）
    ("    'louse_green.bite': 'wiki Louses: Bite is rolled at spawn (A2 changes the roll, §193)',",
     "    'louse_green.bite': 'wiki Louses: Bite is rolled at spawn (A2 changes the roll, §193)',\n"
     "    'louse_green.spit_web': 'wiki Green Louse: Spit Web is 2 Weak at every ascension',"),
    # ⑥ 绿虱子已经从"死内容"变成可遇到 ⇒ 摘掉它的两条
    ('INV_UNWIRED = {"louse_green.bite", "louse_green.grow"}',
     '# §258: the green louse now has `enc_two_louses`, so nothing is unwired any more.\n'
     'INV_UNWIRED = set()'),
]


def main():
    src = io.open(CHECK, encoding='utf-8').read()
    for old, new in EDITS:
        assert src.count(old) == 1, (src.count(old), old[:60])
        src = src.replace(old, new)
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src)
    print('gate patched: %d edits' % len(EDITS))


main()
