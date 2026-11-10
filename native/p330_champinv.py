"""§330：检查器清单同步（Champ 的 6 条动作多了 `champ_exec` 这一格）。

照抄检查器报出来的 facts —— 那份清单的职责是"内容当前是什么"；"这是不是 wiki 说的"
由 `[7]`（阈值/值与 `INV_ASC_VARIANTS` 比）与 §328 的 `[7b]` 负责。
"""

import io

PATH = 'native/sts_content_check.py'

PAIRS = [
    # (旧片段, 新片段)
    ('    "the_champ.heavy_slash": ("Attack", [("damage", 16, "event")]),',
     '''    # §330：`champ_exec` 是二阶段"两招一次 Execute"的循环计数器（相对 +1），见 port-plan §330。
    "the_champ.heavy_slash": ("Attack", [("damage", 16, "event"),
                                         ("counter", "champ_exec", 1, True, "source")]),'''),
    ('    "the_champ.execute": ("Attack", [("damage", 10, "event"), ("damage", 10, "event")]),',
     '''    "the_champ.execute": ("Attack", [("damage", 10, "event"), ("damage", 10, "event"),
                                     ("counter", "champ_exec", 0, False, "source")]),'''),
]

t = io.open(PATH, encoding='utf-8').read()
for old, new in PAIRS:
    assert t.count(old) == 1, old[:60]
    t = t.replace(old, new)

# face_slap / gloat / defensive_stance / anger 用逐条替换太长，改成按 id 定位后整行替换。
import re

def rewrite(t, action_id, extra_facts, base_anchor):
    """把 `"<id>": ("Type", [...])` 整条换掉，facts 前缀保持原样、末尾补 extra。"""
    pattern = re.compile(r'    "%s": \("[A-Za-z]+", \[(.*?)\]\),\n' % re.escape(action_id), re.S)
    m = pattern.search(t)
    assert m, action_id
    body = m.group(1)
    assert body.rstrip().endswith(base_anchor), (action_id, body[-80:])
    new_body = body.rstrip() + ',\n' + ''.join(
        '                                        %s' % f for f in extra_facts) + ']),\n'
    return t[:m.start()] + '    "%s": ("%s", [%s' % (
        action_id, re.search(r'"%s": \("([A-Za-z]+)"' % re.escape(action_id), t).group(1), new_body
    ) + t[m.end():]


t = rewrite(t, 'the_champ.face_slap',
            ['("counter", "champ_exec", 1, True, "source")'],
            '("status", "standard.vulnerable", 2, "event")')
t = rewrite(t, 'the_champ.gloat',
            ['("counter", "champ_exec", 1, True, "source")'],
            '("status", "standard.strength", 2, "source")')
t = rewrite(t, 'the_champ.defensive_stance',
            ['("counter", "champ_exec", 1, True, "source")'],
            '("status", "standard.metallicize", 5, "source")')

# anger：`champ_exec` 从 0 变成 -1。
# anger： 0 -> -1（按 id 定位，避免撞上 execute 那条同样的 0）
idx = t.index('"the_champ.anger"')
head, tail = t[:idx], t[idx:]
old_anger = '("counter", "champ_exec", 0, False, "source")'
assert tail.count(old_anger) == 1, tail.count(old_anger)
tail = tail.replace(old_anger, '("counter", "champ_exec", -1, False, "source")', 1)
t = head + tail

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('inventory: champ actions updated')
