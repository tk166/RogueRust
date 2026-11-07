"""§257：内容门的**独立副本**跟着新语义走（第二遍，逐条断言）。"""
import io

CHK = 'D:/Vibe/sts-tui/native/sts_content_check.py'

EDITS = [
    # 条件清单
    ('INTENT_CONDITIONS = ("intent.healthPercent", "intent.round", "intent.selfHasStatus",\n'
     '                     "intent.opponentHasStatus", "intent.selfHasCounter", "intent.selfResource",\n'
     '                     "intent.opponentCardsPlayed", "intent.allOf", "intent.anyOf", "intent.not")',
     'INTENT_CONDITIONS = ("intent.healthPercent", "intent.round", "intent.selfHasStatus",\n'
     '                     "intent.opponentHasStatus", "intent.selfHasCounter", "intent.selfResource",\n'
     '                     "intent.opponentCardsPlayed", "intent.allOf", "intent.anyOf", "intent.not",\n'
     '                     # §187 / §257：本移植自己的两条。`ascensionAtLeast` 早就在用，清单里一直\n'
     '                     # 漏着 —— 这条清单是"内核认识哪些条件"的副本，漏一条就等于给内容开了个\n'
     '                     # 不受检的口子。\n'
     '                     "intent.ascensionAtLeast", "intent.enemyAliveCount")'),
    # 状态计数
    ('    # §256: +1 (`painful_stabs`).\n    "statuses": 66,',
     '    # §256: +1 (`painful_stabs`).\n    # §257: +1 (`lagavulin_asleep`).\n    "statuses": 67,'),
    # `stunned` 的事实：清 `lagavulin_woken`
    ('    "lagavulin.stunned": ("Unknown",\n'
     '                          [("counter", "lagavulin_step", ("expr", "remainder"), False, "source")]),',
     '    "lagavulin.stunned": ("Unknown",\n'
     '                          [("counter", "lagavulin_woken", 0, False, "source")]),'),
    # A3 档的 attack 也要 step 计数器
    ("    'lagavulin.attack': [(3, [('damage', 20, 'event')])],",
     "    'lagavulin.attack': [(3, [('damage', 20, 'event'),\n"
     "                              ('counter', 'lagavulin_step', ('expr', 'remainder'), False,\n"
     "                               'source')])],"),
]


def main():
    src = io.open(CHK, encoding='utf-8').read()
    for old, new in EDITS:
        assert src.count(old) == 1, (src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(CHK, 'w', encoding='utf-8', newline='\n').write(src)
    print('gate patched: %d edits' % len(EDITS))


main()
