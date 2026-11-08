"""§286 内容门（续）：进入效果也要过**同一份**词表。

先有的词表检查是内联在"选项循环"里的。给进入效果另写一份词表 = §4.20 那种
"同一个词表被两处认识就一定漂"。所以这里把它抽成 `check_effects(...)`，
选项与段进入效果都调它；进入效果再多一条"不许改牌"。
"""
import io
import re

P = 'D:/Vibe/sts-tui/native/sts_content_check.py'

START = '''            for kind_label, key in (("", "Effects"), ("Asc", "EffectsAsc")):'''
END = '''            # ── §279：条件（`Requires`）────'''


def main():
    s = io.open(P, encoding='utf-8').read()
    start = s.index(START)
    end = s.index(END)
    block = s[start:end]
    # 块尾是 `if edits > 1: ...` 两句；它们留在调用侧。
    tail_start = block.index('                if edits > 1:')
    body = block[:tail_start]
    lines = body.split('\n')
    # 去掉第一行（for 循环头），其余按 4 空格反缩进，变成嵌套函数体
    inner = lines[1:]
    out = []
    for line in inner:
        if line.strip() == '':
            out.append('')
        else:
            assert line.startswith('    '), repr(line[:40])
            out.append(line[4:])
    body_text = '\n'.join(out).rstrip('\n')
    # `continue` 在 for 里没问题（它仍在 for 里）；只把 `where` 里的 label 保持原样。
    func = '''    def check_effects(label, effects, kind_label):
        """一条效果列表。返回**改牌效果**的条数（调用方判"两个"）。

        §286：抽出来是因为**段的进入效果**要用同一份词表。另写一份 = 两份词表漂。
        """
        if effects is None:
            effects = []
        if not isinstance(effects, list):
            fail(label, "not a list: %r" % (effects,))
            return 0
        if len(effects) > 4:
            fail(label, "more than 4 effects (the kernel's MAX_EVENT_EFFECTS)")
        edits = 0
''' + body_text.replace('        edits = 0\n', '') + '''
        return edits

'''
    call = '''            for kind_label, key in (("", "Effects"), ("Asc", "EffectsAsc")):
                edits = check_effects(label, option.get(key), kind_label)
                if edits > 1:
                    fail(label + kind_label,
                         "%d 个改牌效果（待答选牌只有一个位置）" % edits)
'''
    s = s[:start] + call + s[end:]
    # 嵌套函数插在 `node_ids = [...]` 之后（计数变量已经在上面定义）
    anchor = '''    reached = set()
'''
    assert s.count(anchor) == 1
    s = s.replace(anchor, anchor + '\n' + func, 1)

    # 进入效果：走同一个 check_effects，并禁止改牌
    old = '''        for key in ("Effects", "EffectsAsc"):
            entry = node.get(key)
            if entry is None:
                continue
            if not isinstance(entry, list) or not entry:
                fail("%s.%s" % (label_root, key), "must be a non-empty list")
                continue
            for index, spec in enumerate(entry):
                where = "%s.%s[%d]" % (label_root, key, index)
                if not isinstance(spec, dict):
                    fail(where, "must be an object {Effect, Amount}")
                    continue
                word = spec.get("Effect") or ""
                if word.split(":")[0] in ("remove_card", "upgrade_card", "transform_card"):
                    fail(where, "a step-entry effect cannot change the deck (the answer queue "
                                "has one slot and the option already used it)")'''
    new = '''        for kind_label, key in (("", "Effects"), ("Asc", "EffectsAsc")):
            entry = node.get(key)
            if entry is None:
                continue
            if not isinstance(entry, list) or not entry:
                fail("%s.%s" % (label_root, key), "must be a non-empty list")
                continue
            # 同一份词表（`check_effects`），外加一条：**进入效果不许改牌** ——
            # 改牌会变成待答问题，而问题队列只有一个位置，那个位置属于选项。
            edits = check_effects("%s.<entry>" % label_root, entry, kind_label)
            if edits:
                fail("%s.%s" % (label_root, key),
                     "a step-entry effect cannot change the deck (the answer queue has one "
                     "slot and the option already used it)")'''
    assert s.count(old) == 1
    s = s.replace(old, new)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('gate: entry effects share one vocabulary')


main()
