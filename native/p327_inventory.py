"""§327：检查器的独立清单要跟上 wiki 的 Scouring Whip 升档。

原文：*"Deals 7 damage. Adds (1 Wound; **A2: 2**; **A18: 3** Wounds). (; **A18: Gains 1 Strength**.)"*

清单原来只有 `(3, [...wound 2...])` —— 值对、**档位错**（A3 而不是 A2），而且 A18 那一档
（3 Wound + 自身 1 Strength）整个缺着。这正是"清单抄的是当时的内容、不是 wiki"的形状。
"""

import io

PATH = 'native/sts_content_check.py'

OLD = """    'taskmaster.scouring_whip': [(3, [('damage', 7, 'event'), ('card', 'wound', 2, 'DiscardPile', 'event')])],"""

NEW = """    # §327：wiki `Taskmaster` —— "Adds (1 Wound; A2: 2; A18: 3 Wounds). (A18: Gains 1 Strength.)"
    # 原来记的是 `(3, …)`：值（2 Wound）对，**档位错**（A2 不是 A3），A18 那一档整条缺失。
    'taskmaster.scouring_whip': [
        (2, [('damage', 7, 'event'), ('card', 'wound', 2, 'DiscardPile', 'event')]),
        (18, [('damage', 7, 'event'), ('card', 'wound', 3, 'DiscardPile', 'event'),
              ('status', 'standard.strength', 1, 'source')]),
    ],"""


t = io.open(PATH, encoding='utf-8').read()
assert t.count(OLD) == 1, t.count(OLD)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(OLD, NEW))
print('inventory: taskmaster.scouring_whip A2/A18')
