"""§308 字段清点（parser 修好版见下）：第一版把文档注释里的 `{` 当成花括号，
于是把 `Pending` / `inv` / `Cumulative` / `wiki` 当成字段名读了出来 ——
"解析器自坏"比"字段缺"更隐蔽，所以先把词法做对。

做法：**逐行**走，去掉行注释后再数花括号，只认 `depth == 1` 且形如 `name:` 的行。
"""
import io
import re
import sys

ROOT = 'D:/Vibe/sts-tui/'
STATE = ROOT + 'kernel/rd-run/src/state.rs'
ARCHIVE = ROOT + 'kernel/rd-run/src/state/archive.rs'
HASH = ROOT + 'kernel/rd-run/src/hash.rs'

NOT_HASHED = {
    # 三个容器的**长度**：指纹写的是切片本身（每张牌一行），长度由行数隐含。
    # 豁免的目的是不把同一事实写两遍 —— 也别忘了它意味着"这两个数天然一致"。
    'deck_len': '由 `deck()` 的行数隐含',
    'relics_len': '由 `relics()` 的行数隐含',
    'potions_len': '由 `potions()` 的行数隐含',
    # 同一个理由的第四个：`pickup_offer()` 就是 `pickup_offer` 的活动前缀。
    'pickup_offer_len': '由 `pickup_offer()` 的切片长度隐含',
}
NOT_ARCHIVED = {
    'pickup_offer_len': '存档写的是 `pickup_offer()` 的切片（长度紧跟在前面的字节里）',
}

FIELD = re.compile(r'^\s+(?:pub\(crate\) )?(?:pub )?(\w+):')


def code_part(line):
    """这一行的代码部分（去掉 `//` 之后的一切）。字符串里的 `//` 这里用不着担心。"""
    cut = line.find('//')
    return line if cut < 0 else line[:cut]


def struct_fields(text):
    lines = text.split('\n')
    start = next(i for i, line in enumerate(lines) if 'pub struct RunState {' in line)
    depth = 0
    fields = []
    for line in lines[start:]:
        code = code_part(line)
        before = depth
        depth += code.count('{') - code.count('}')
        if before == 1 and depth == 1:
            match = FIELD.match(code)
            if match:
                fields.append(match.group(1))
        elif before == 1 and depth == 0:
            break
    return fields


def main():
    state = io.open(STATE, encoding='utf-8').read()
    archive = io.open(ARCHIVE, encoding='utf-8').read()
    fingerprint = io.open(HASH, encoding='utf-8').read()
    fields = struct_fields(state)
    if not fields:
        print('STATE_FIELDS FAIL (parser found no fields)')
        sys.exit(1)

    problems = []
    for name in fields:
        in_archive = ('state.%s' % name) in archive
        in_hash = ('state.%s' % name) in fingerprint
        if not in_archive and name not in NOT_ARCHIVED:
            problems.append('存档缺: %s' % name)
        if not in_hash and name not in NOT_HASHED:
            problems.append('指纹缺: %s' % name)
        if '--check' not in sys.argv:
            print('  %-24s archive=%-5s hash=%s' % (name, in_archive, in_hash))
    for name in list(NOT_HASHED) + list(NOT_ARCHIVED):
        if name not in fields:
            problems.append('豁免表里的字段已不存在: %s' % name)

    if problems:
        for line in problems:
            print('!!', line)
        print('STATE_FIELDS FAIL (%d problems over %d fields)' % (len(problems), len(fields)))
        sys.exit(1)
    print('STATE_FIELDS PASS (%d fields, every one archived and in the fingerprint)' % len(fields))


main()
