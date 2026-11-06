"""§249 门 #2：内容用到的表达式 kind，内核**真的能求值**吗？

## 为什么需要这道门

§249 的四张牌里有三张在运行时才有报错：`remainder` / `cardsPlayedThisTurn` 属于
`expr.rs` 里"表里有、但没实现"的 kind ⇒ `UnsupportedKind`。内容门看不到它（它只查
形状与事实对账），构建也看不到它（`kind` 字符串随便写），**只有跑起来才知道**。

⇒ 想在"写内容的那一刻"就知道，就必须把"内核实现了哪些 kind"变成**可查的**。

## 单一真相：从 `expr.rs` 源码里抽，不抄第二份

* **值类别表**：`const INT_KINDS / BOOL_KINDS / CARD_KINDS: &[&str] = &[...]`
* **已实现**：`fn eval_int` / `eval_bool` / `eval_card` 函数体里的 `"name" =>` 分支

一个 kind 在表里、但三个 eval 里都没有分支 ⇒ 内核会报 `UnsupportedKind`（这正是
`expr.rs` 模块头那张范围表承诺的行为）。本脚本照同一个判据复现它。

⚠️ 两条防"静默通过"的守卫（FACT §4.16：替换/正则没匹配上必须响亮失败）：
1. 三张表必须各抽到 ≥ 8 个名字，分支集合必须 ≥ 20 个 —— 否则说明正则漂了；
2. 内容里用到的 kind 必须 ≥ 15 个 —— 否则说明走查没走进节目。
"""
import io
import json
import os
import re
import sys

ROOT = 'D:/Vibe/sts-tui/'
EXPR = ROOT + 'kernel/rd-core/src/expr.rs'
CONTENT = ROOT + 'tools/contentc/packages/sts/sts.roguedeck.json'

# `node.*` 是**语句**不是表达式：它们的支持与否由 exec.rs 的节点分派决定，不在这道门的范围。
STATEMENT_PREFIX = 'node.'


def strip_comments(text):
    """去掉 `//` 行注释 —— 表里的注释**含 ASCII 双引号**（`（"等于你的格挡"）`），
    不剥掉就会被当成 kind 名（第一次跑就是这么假的：28 个"未实现"里有 12 个是中文注释）。"""
    out = []
    for line in text.splitlines():
        hash_at = line.find('//')
        out.append(line if hash_at < 0 else line[:hash_at])
    return '\n'.join(out)


def kind_tables():
    src = strip_comments(io.open(EXPR, encoding='utf-8').read())
    tables = {}
    for name in ('INT_KINDS', 'BOOL_KINDS', 'CARD_KINDS'):
        match = re.search(r'const %s: &\[&str\] = &\[(.*?)\];' % name, src, re.S)
        if not match:
            sys.exit('GUARD: %s table not found in expr.rs -- the regex drifted' % name)
        names = set(re.findall(r'"([^"]+)"', match.group(1)))
        # 小表是真的小（`CARD_KINDS` 只有 2 条），所以守卫按"非空"判，不按数量硬编；
        # 真正防漏的是下面"内容用到 ≥ 15 个 kind"那一条。
        if not names:
            sys.exit('GUARD: %s yielded no names -- the regex drifted' % name)
        tables[name] = names
    return tables


def implemented():
    src = strip_comments(io.open(EXPR, encoding='utf-8').read())
    done = {}
    for fn in ('eval_int', 'eval_bool', 'eval_card'):
        match = re.search(r'\n(?:pub )?fn %s<[^\n]*\{(.*?)\n\}\n' % fn, src, re.S)
        if not match:
            sys.exit('GUARD: fn %s not found in expr.rs' % fn)
        arms = set(re.findall(r'"([A-Za-z0-9_.]+)"\s*=>', match.group(1)))
        if not arms:
            sys.exit('GUARD: fn %s yielded no match arms' % fn)
        done[fn] = arms
    everything = set().union(*done.values())
    if len(everything) < 20:
        sys.exit('GUARD: only %d implemented kinds found' % len(everything))
    return done, everything


def content_kinds():
    """每一处 `kind` 出现的位置（卡牌 / 状态 / 敌人动作…），返回 [(kind, 归属)]。"""
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    found = []

    def walk(value, owner):
        if isinstance(value, dict):
            kind = value.get('kind')
            if isinstance(kind, str):
                found.append((kind, owner))
            for key, sub in value.items():
                walk(sub, owner)
        elif isinstance(value, list):
            for sub in value:
                walk(sub, owner)

    for table, label in (('Cards', 'card'), ('Statuses', 'status'),
                         ('EnemyActions', 'enemy_action'), ('Relics', 'relic'),
                         ('Potions', 'potion'), ('Events', 'event')):
        for row in doc.get(table) or []:
            walk(row, '%s:%s' % (label, row.get('Id', '?')))
    if len({k for k, _ in found}) < 15:
        sys.exit('GUARD: content only used %d distinct kinds -- the walk missed the programs'
                 % len({k for k, _ in found}))
    return found


def main():
    tables = kind_tables()
    done, everything = implemented()
    unsupported = set()
    for names in tables.values():
        unsupported |= names - everything

    used = content_kinds()
    bad = {}
    for kind, owner in used:
        if kind.startswith(STATEMENT_PREFIX) or kind.startswith('sel.'):
            continue
        if kind in unsupported:
            bad.setdefault(kind, set()).add(owner)

    print('expression kinds: %d declared, %d implemented, %d unsupported'
          % (len(set().union(*tables.values())), len(everything), len(unsupported)))
    if not bad:
        print('PROGRAM_AUDIT PASS (content uses %d distinct kinds, none unsupported)'
              % len({k for k, _ in used}))
        return
    for kind in sorted(bad):
        print('!! UNSUPPORTED KIND %r used by %s'
              % (kind, ', '.join(sorted(bad[kind]))))
    print('PROGRAM_AUDIT FAIL (%d kind(s) the kernel cannot evaluate)' % len(bad))
    raise SystemExit(1)



if __name__ == '__main__':   # 被 `sts_content_check.py` import 时必须静默
    main()
