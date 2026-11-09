"""§310（三）：内容侧 —— `standard.orange_pellets` 改成"清 Debuff"。

三处 `applyStatus(strength 3)` + `applyStatus(dexterity 3)` 的**成对**节点，换成一个
`node.removeDebuffs`。做法是文本手术（按花括号配对定位整段），而不是整份 JSON 重新序列化
—— 后者会把键序改掉，diff 从 6 行变成 6000 行。

**缩进不写死**：新节点的排版从被替换的旧节点里取（`TargetSelector` 那一段原样保留，
结尾两行 `}` 的缩进直接沿用）。写死空格是这里最容易出的错，而它只在 diff 里看得出来。
"""
import io
import json
import re

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
STATUS = 'standard.orange_pellets'


def match_object(text, start):
    """`text[start]` 必须是 `{`；返回它配对的 `}` 的下标（跳过字符串里的括号）。"""
    assert text[start] == '{', text[start]
    depth = 0
    index = start
    in_string = False
    while index < len(text):
        char = text[index]
        if in_string:
            if char == '\\':
                index += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise AssertionError('unbalanced braces')


def build_replacement(old_node):
    """把一个 `applyStatus` 对象改写成 `removeDebuffs` 对象（保留原排版）。"""
    kind = '"kind": "node.applyStatus"'
    assert old_node.count(kind) == 1
    node = old_node.replace(kind, '"kind": "node.removeDebuffs"', 1)

    selector_start = node.index('"TargetSelector":')
    brace = node.index('{', selector_start)
    selector_end = match_object(node, brace)
    # 旧节点尾部两行：value 的 `}` 与对象的 `}` —— 缩进直接沿用。
    lines = node.rsplit('\n', 2)
    value_close = lines[1]
    object_close = lines[2]
    return node[:selector_end + 1] + '\n' + value_close + '\n' + object_close


def main():
    text = io.open(PATH, encoding='utf-8').read()
    status_start = text.index('"Id": "%s"' % STATUS)
    next_status = re.compile(r'\n    \{\n      "Id": ')
    match = next_status.search(text, status_start + 1)
    assert match, 'the status is the last one'
    head, body, tail = text[:status_start], text[status_start:match.start()], text[match.start():]

    old_description = ('"DescriptionKey": "Whenever you play a Power, Attack, and Skill in the same '
                       'turn, gain 3 Strength and 3 Dexterity.",')
    new_description = ('"DescriptionKey": "Whenever you play a Power, Attack, and Skill in the same '
                       'turn, remove all debuffs.",')
    assert body.count(old_description) == 1
    body = body.replace(old_description, new_description)

    replaced = 0
    cursor = 0
    while True:
        marker = body.find('"kind": "node.applyStatus"', cursor)
        if marker < 0:
            break
        first_open = body.rindex('{', 0, marker)
        first_close = match_object(body, first_open)
        second_marker = body.index('"kind": "node.applyStatus"', first_close)
        second_close = match_object(body, body.rindex('{', 0, second_marker))
        pair = body[first_open:second_close + 1]
        assert pair.count('node.applyStatus') == 2, pair[:200]
        assert 'standard.strength' in pair and 'standard.dexterity' in pair
        replacement = build_replacement(body[first_open:first_close + 1])
        body = body[:first_open] + replacement + body[second_close + 1:]
        replaced += 1
        cursor = first_open + len(replacement)

    assert replaced == 3, replaced
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(head + body + tail)

    # ── 验：解析 + 计数 ───────────────────────────────────────────────────────────────────
    doc = json.load(io.open(PATH, encoding='utf-8'))
    status = next(s for s in doc['Statuses'] if s['Id'] == STATUS)
    assert status['DescriptionKey'].endswith('remove all debuffs.'), status['DescriptionKey']

    def count_kind(node, kind):
        total = 0
        if isinstance(node, dict):
            if node.get('kind') == kind:
                total += 1
            for value in node.values():
                total += count_kind(value, kind)
        elif isinstance(node, list):
            for item in node:
                total += count_kind(item, kind)
        return total

    counters_ok = all(('orange_pellets_' + kind) in json.dumps(status)
                      for kind in ('power', 'attack', 'skill'))
    print('removeDebuffs=%d applyStatus=%d counters ok=%s'
          % (count_kind(status, 'node.removeDebuffs'),
             count_kind(status, 'node.applyStatus'), counters_ok))
    assert count_kind(status, 'node.removeDebuffs') == 3
    assert count_kind(status, 'node.applyStatus') == 0
    print('document applyStatus occurrences = %d'
          % io.open(PATH, encoding='utf-8').read().count('"kind": "node.applyStatus"'))


main()
