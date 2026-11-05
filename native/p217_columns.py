"""§217 part 2: honest column names, and a self-test with five adversarial fixtures.

Columns now say exactly what they measure:

    Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence

`TestNamed` = "this id is a **string literal** inside a test body" (a reference, not an assertion);
`HarnessOnly` = "no named reference, but a generic layer iterates the whole table"; `SourceTie` =
"a wiki dump or the hand-copied spec inventory pins a number here". The header says out loud that no
column claims behaviour.
"""
import io

P = 'native/coverage_matrix.py'
text = io.open(P, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


# ── 对账修正（用 cargo 的 `--list` 当 ground truth，不靠 grep 行数） ────────────────────────────
one('''    对账：源码里 `#[test]` 共 906 处，其中 **4 处是注释里提到的**（`content.rs:4731` 等），
    真实 902；修前扫到 893（缺 9 = 8 + 1），修后 902。''',
    '''    对账（ground truth 是 `cargo test -p <crate> -- --list`，不是 grep 的行数）：

    ```text
    cargo --list    rd-core 704 + rd-run 108 + rd-wasm 94 = 906   （其中 2 条 #[ignore]）
    修前扫描器      893   （缺 9：8 条在嵌套目录 + 1 条被 doc 注释挡住）
    修后扫描器      906   == cargo 的清单
    ```

    （grep 得到的"906 行含 `#[test]`"里另有 4 处是**注释里提到的** `#[test]` —— 它们本来就不是
    测试，扫描器用 `strip_rust` 的位置检查把它们排除了。第一版按行数推"真实 902"是错的，
    因为同一行里可能出现两个属性。）''',
    'reconciliation')

# ── 行组装：把 RuntimeTested 拆成 TestNamed / HarnessOnly，WikiVerified 改名 SourceTie ─────────
one('''            names = []
            for _crate, fn in by_test.get(eid, []):
                if fn not in names:
                    names.append(fn)
            if names:
                runtime = 'test:' + ', '.join(names[:2])
                if len(names) > 2:
                    runtime += ' …(+%d)' % (len(names) - 2)
                stats['test'] += 1
            elif kind in HARNESS:
                runtime = 'harness:' + HARNESS[kind]
                stats['harness'] += 1
            elif kind in sweeps:
                runtime = 'harness:' + sweeps[kind][0]
                if len(sweeps[kind]) > 1:
                    runtime += ' …(+%d)' % (len(sweeps[kind]) - 1)
                stats['harness'] += 1
            elif kind == 'status' and eid in refs:
                runtime = 'harness:' + '+'.join(sorted(
                    {'CARD_DIFF' if where == 'card' else 'ENEMY_DIFF' for where in refs[eid]}))
                stats['harness'] += 1
            else:
                runtime = '—'
                stats['none'] += 1''',
    '''            names = []
            for _crate, fn in by_test.get(eid, []):
                if fn not in names:
                    names.append(fn)
            # `TestNamed`：这个 id 以**字符串字面量**出现在某条测试的函数体里。
            # ⚠️ 它是"被引用"，不是"行为被断言"：`assert_eq!(id, "spiker")` 与"真打一场 spiker"
            # 在这一列里长得一模一样（审阅 P2-A 的原话，这也是列名从 `RuntimeTested` 改过来的原因）。
            test_named = '—'
            harness = '—'
            if names:
                test_named = ', '.join(names[:2])
                if len(names) > 2:
                    test_named += ' …(+%d)' % (len(names) - 2)
                stats['named'] += 1
            elif kind in HARNESS:
                harness = HARNESS[kind]
                stats['harness'] += 1
            elif kind in sweeps:
                harness = sweeps[kind][0]
                if len(sweeps[kind]) > 1:
                    harness += ' …(+%d)' % (len(sweeps[kind]) - 1)
                stats['harness'] += 1
            elif kind == 'status' and eid in refs:
                harness = '+'.join(sorted(
                    {'CARD_DIFF' if where == 'card' else 'ENEMY_DIFF' for where in refs[eid]}))
                stats['harness'] += 1
            else:
                stats['none'] += 1''',
    'named / harness split')

one('''            tied = table_of.get(eid, set())
            wiki = None
            if kind == 'monster' and eid in wiki_of:
                wiki = 'wiki:%s' % wiki_of[eid]
                if not (tied & WIKI_TIE['monster']):
                    wiki += ' (未钉数字)'
            elif kind == 'action':
                owner = info['owner']
                if owner and owner in wiki_of:
                    wiki = 'wiki:%s' % wiki_of[owner]
                    if not (tied & WIKI_TIE['action']):
                        # §190 之后的升档表才是“招式对上 wiki”的证据；只有 INV_ACTIONS 时，钉的是**基础值**。
                        wiki += ' (仅基础值)' if 'INV_ACTIONS' in tied else ' (未钉数字)'
            if wiki and wiki.startswith('wiki:'):
                stats['wiki'] += 1
            elif tied:
                wiki = 'spec:' + '+'.join(sorted(tied))
                stats['spec'] += 1
            else:
                wiki = '—\'''',
    '''            tied = table_of.get(eid, set())
            source = None
            if kind == 'monster' and eid in wiki_of:
                source = 'wiki:%s' % wiki_of[eid]
                if not (tied & WIKI_TIE['monster']):
                    source += ' (未钉数字)'
            elif kind == 'action':
                owner = info['owner']
                if owner and owner in wiki_of:
                    # §217：**写明"继承"** —— 动作的页面来自所属怪物，不是这条动作自己核过
                    # （`maw.nom_nom` 就是反例：有 wiki 标签、时间变量却是错的）。
                    source = 'wiki:%s (via %s)' % (wiki_of[owner], owner)
                    if not (tied & WIKI_TIE['action']):
                        # §190 之后的升档表才是“招式对上 wiki”的证据；只有 INV_ACTIONS 时，钉的是**基础值**。
                        source += ' · 仅基础值' if 'INV_ACTIONS' in tied else ' · 未钉数字'
            if source and source.startswith('wiki:'):
                stats['wiki'] += 1
            elif tied:
                source = 'spec:' + '+'.join(sorted(tied))
                stats['spec'] += 1
            else:
                source = '—\'''',
    'source tie')

one('''            rows.append({'kind': kind, 'id': eid, 'implemented': implemented,
                         'runtime': runtime, 'wiki': wiki, 'deviation': deviation,
                         'evidence': '/'.join(evidence) or '—'})''',
    '''            rows.append({'kind': kind, 'id': eid, 'implemented': implemented,
                         'named': test_named, 'harness': harness, 'source': source,
                         'deviation': deviation, 'evidence': '/'.join(evidence) or '—'})''',
    'row dict')

one('''        stats = {'rows': 0, 'test': 0, 'harness': 0, 'none': 0, 'wiki': 0, 'spec': 0,
                 'dev': 0, 'orphan': 0}''',
    '''        stats = {'rows': 0, 'named': 0, 'harness': 0, 'none': 0, 'wiki': 0, 'spec': 0,
                 'dev': 0, 'orphan': 0}''',
    'stats keys')

io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('columns patched (rows)')
