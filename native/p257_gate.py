"""§257：把内容门那份**独立副本**更新到新语义。

内容门的两张表是手抄的 wiki 数字（`INV_ACTIONS` / `INV_ASC_VARIANTS`），所以内容一改它们立刻红。
这次红得对：改的正是阈值与两条新事实。四条改动：

1. `lagavulin.stunned` —— 新增的动作（`Intent.Kind = Unknown`，与 `sleep` 同形）。
2. `lagavulin.attack` / `siphon_soul` —— 末尾多了 `lagavulin_step` 的 3 阶循环计数器。
3. `book_of_stabbing.big_stab` —— 末尾多了 A18 的 N 递增计数器。
4. `blue_slaver.rake` —— 补 A17 档（8 伤害 + **2 层 Weak**）。
5. `nemesis.*` / `reptomancer.*` 的 `ProgramAsc` 阈值 4/19 → 3/18（Boss 档误抄成精英）。
"""
import io
import json

CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

EDITS = [
    # --- 新动作的 Intent ---
    ('''    "lagavulin.sleep": ("Unknown", []),''',
     '''    "lagavulin.sleep": ("Unknown", []),
    # §257: waking up by damage costs it a turn; the move itself only clears the "just woke" flag.
    "lagavulin.stunned": ("Unknown",
                          [("counter", "lagavulin_step", ("expr", "remainder"), False, "source")]),'''),
    # --- base facts：lagavulin 的两招 + book 的单刺 ---
    ('''    "lagavulin.attack": ("Attack", [("damage", 18, "event")]),''',
     '''    "lagavulin.attack": ("Attack",
                         [("damage", 18, "event"),
                          # §257：三阶出招循环（Attack / Attack / Siphon Soul）的计数器。
                          ("counter", "lagavulin_step", ("expr", "remainder"), False, "source")]),'''),
    ('''    "book_of_stabbing.big_stab": ("Attack", [("damage", 21, "event")]),''',
     '''    "book_of_stabbing.big_stab": ("Attack",
                                  [("damage", 21, "event"),
                                   # §257：A18 起 Single Stab 也推进 N（wiki 的第二颗星号）。
                                   ("counter", "book_stab_uses",
                                    ("counter", "book_stab_single_bump", "source"), True, "source")]),'''),
    # --- asc 阈值修正 + 新档位 ---
    ('''    'blue_slaver.rake': [(2, [('damage', 8, 'event'), ('status', 'standard.weak', 1, 'event')])],''',
     '''    'blue_slaver.rake': [(2, [('damage', 8, 'event'), ('status', 'standard.weak', 1, 'event')]),
                        (17, [('damage', 8, 'event'), ('status', 'standard.weak', 2, 'event')])],'''),
    ("""    'book_of_stabbing.big_stab': [(3, [('damage', 24, 'event')])],""",
     """    'book_of_stabbing.big_stab': [(3, [('damage', 24, 'event'),
                                      ('counter', 'book_stab_uses',
                                       ('counter', 'book_stab_single_bump', 'source'), True, 'source')])],"""),
    ("""    'nemesis.tri_attack': [(4, [""", """    'nemesis.tri_attack': [(3, ["""),
    ("""    'nemesis.tri_burn': [(19, [""", """    'nemesis.tri_burn': [(18, ["""),
    ("""    'reptomancer.big_bite': [(4, [""", """    'reptomancer.big_bite': [(3, ["""),
    ("""    'reptomancer.snake_strike': [(4, [""", """    'reptomancer.snake_strike': [(3, ["""),
    ("""    'reptomancer.spawn_dagger': [(19, [""", """    'reptomancer.spawn_dagger': [(18, ["""),
    # --- 无 A 档清单：`stunned` 也要登记 ---
    ("""    'lagavulin.sleep': 'wiki Lagavulin: Sleep does nothing',""",
     """    'lagavulin.sleep': 'wiki Lagavulin: Sleep does nothing',
    'lagavulin.stunned': 'wiki Lagavulin: Stunned does nothing (a lost turn, no numbers)',"""),
]


def main():
    src = io.open(CHECK, encoding='utf-8').read()
    for old, new in EDITS:
        assert src.count(old) == 1, (src.count(old), old[:70])
        src = src.replace(old, new)

    # `lagavulin.siphon_soul`：base 与 A18 两档都要加上 step 计数器。
    # 先看现状（gate 里是怎么写的）。
    needle = "    'lagavulin.siphon_soul': [(18, [('modify', 'standard.strength', -2, 'event'),"
    assert src.count(needle) == 1
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src)
    print('gate inventory patched (siphon_soul entry still needs its counter fact)')


main()
