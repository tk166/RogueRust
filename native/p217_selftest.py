"""§217 part 5: `--selftest` -- five adversarial fixtures for the scanner itself.

The review asked for this (P2-A: "加入 3–5 个覆盖矩阵自身的对抗性夹具，特别是'函数体仅出现 id 但未
执行行为'"). A coverage tool that is never tested is just another opinion, so each fixture here targets
one way the scanner could lie:

1. **nested directory**  -- a test one level down must be found (§217 walked `src/*.rs` only, which lost
   `rd-run/src/state/archive.rs`'s 8 tests);
2. **doc comment between `#[test]` and `fn`** -- must be found (`rd-wasm/src/run.rs:7041`);
3. **`#[test]` inside a comment** -- must NOT be counted as a test (there are 4 such mentions in the
   tree; miscounting them would inflate the number the gate prints);
4. **id only in a comment inside a test body** -- must NOT count as `TestNamed`;
5. **the declaration/`orphan` predicate** -- an entity that only "mentions itself" must still be
   reported as unreachable, and a stale `ORPHAN_OK` declaration must be red. (This was a real bug in
   §215: `everywhere` contained the entity's own definition table, so the predicate was always true.)

The fixtures build a throwaway tree in a temp dir; nothing here reads the real content.
"""
import io

P = 'native/coverage_matrix.py'
text = io.open(P, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


# ── 把"声明检查"抽成函数，夹具才能直接问它 ──────────────────────────────────────────────────
one('''    # 声明过的孤儿必须**仍然是孤儿**，且 id 仍然存在（否则这条声明已经烂了）。
    reachable_ids = {row_id for kind in entities for row_id, info in entities[kind].items()
                     if info['reachable']}
    known_ids = {row_id for kind in entities for row_id in entities[kind]}
    for ident, reason in sorted(ORPHAN_OK.items()):
        if ident not in known_ids:
            problems.append('`ORPHAN_OK` 声明的 `%s` 在内容里不存在（声明烂了）' % ident)
        elif ident in reachable_ids:
            problems.append('`%s` 已经被引用了，`ORPHAN_OK` 里那一条声明该删掉' % ident)
''',
    '''    problems.extend(declaration_problems(entities))
''',
    'declaration check extracted')

one('''def render(rows, summary, meta):''',
    '''def declaration_problems(entities):
    """`ORPHAN_OK` 每一条都要**仍然成立**：id 还在、而且**仍然**没人引用。

    抽成函数是为了让 `--selftest` 能直接问它（夹具 5）—— 这条检查是"恒真谓词"的反面，
    必须能被证明会红。
    """
    reachable_ids = {row_id for kind in entities for row_id, info in entities[kind].items()
                     if info['reachable']}
    known_ids = {row_id for kind in entities for row_id in entities[kind]}
    problems = []
    for ident in sorted(ORPHAN_OK):
        if ident not in known_ids:
            problems.append('`ORPHAN_OK` 声明的 `%s` 在内容里不存在（声明烂了）' % ident)
        elif ident in reachable_ids:
            problems.append('`%s` 已经被引用了，`ORPHAN_OK` 里那一条声明该删掉' % ident)
    return problems


def render(rows, summary, meta):''',
    'declaration_problems')

# ── 自检本体 ──────────────────────────────────────────────────────────────────────────────────
one('''def main():''',
    '''def selftest():
    """五个夹具，逐条打"扫描器能骗自己"的一种方式。任何一条不过 ⇒ 退出码 1。"""
    import tempfile

    failures = []

    def check(name, got, expected):
        if got != expected:
            failures.append('%s: got %r, expected %r' % (name, got, expected))

    root = tempfile.mkdtemp(prefix='coverage-selftest-')
    crate = os.path.join(root, 'rd-core', 'src')
    nested = os.path.join(crate, 'deep')
    os.makedirs(nested)

    io.open(os.path.join(crate, 'top.rs'), 'w', encoding='utf-8', newline=chr(10)).write(
        '#[test]' + chr(10) + 'fn top_level() {' + chr(10) +
        '    let _ = "spiker";' + chr(10) + '}' + chr(10) + chr(10) +
        '#[test]' + chr(10) + '/// doc comment between attribute and fn' + chr(10) +
        'fn behind_a_doc_comment() {' + chr(10) + '}' + chr(10) + chr(10) +
        '/// this one had lost its `#[test]` (a comment mention)' + chr(10) +
        '/// it mentions #[test] twice: #[test]' + chr(10) + 'fn not_a_test() {' + chr(10) + '}' +
        chr(10) + chr(10) +
        '#[test]' + chr(10) + 'fn id_only_in_a_comment() {' + chr(10) +
        '    // "chosen" is only mentioned here, never used' + chr(10) +
        '    assert!(true);' + chr(10) + '}' + chr(10))

    io.open(os.path.join(nested, 'deep.rs'), 'w', encoding='utf-8', newline=chr(10)).write(
        '#[test]' + chr(10) + 'fn nested_one() {' + chr(10) +
        '    let _ = "chosen";' + chr(10) + '}' + chr(10))

    found = tests(kernel_root=root, crates=['rd-core'])
    names = sorted(fn for _crate, fn, _body in found)
    # 夹具 1 / 2 / 3
    check('nested', 'nested_one' in names, True)
    check('doc comment between attribute and fn', 'behind_a_doc_comment' in names, True)
    check('a #[test] inside a comment is not a test', 'not_a_test' in names, False)
    check('exactly four real tests', len(names), 4)

    # 夹具 4：id 只出现在**注释**里 ⇒ 不算 TestNamed
    by_test = tests_by_entity(found)
    check('id in a comment is not a reference', 'chosen' in by_test, False)
    check('id in a string literal is a reference', 'spiker' in by_test, True)

    # 夹具 5：自己提到自己不算"可达"；过时的声明必须红
    entities = {
        'monster': {
            'ghost': {'reachable': False, 'why': 'nothing applies it', 'record': {}},
            'real': {'reachable': True, 'why': 'encounter roster', 'record': {}},
        },
        'action': {'declared': {'reachable': True, 'why': 'declared unwired', 'record': {},
                                'owner': None}},
        'card': {}, 'status': {}, 'relic': {}, 'potion': {}, 'encounter': {}, 'event': {},
    }
    saved = dict(ORPHAN_OK)
    try:
        ORPHAN_OK.clear()
        ORPHAN_OK['ghost'] = 'declared, and still an orphan'
        check('declared orphan is fine', declaration_problems(entities), [])
        ORPHAN_OK['real'] = 'no longer an orphan'
        problems = declaration_problems(entities)
        check('stale declaration is red', any('已经' in problem for problem in problems), True)
        ORPHAN_OK.clear()
        ORPHAN_OK['missing'] = 'the id is gone'
        problems = declaration_problems(entities)
        check('declaration for a missing id is red',
              any('不存在' in problem for problem in problems), True)
    finally:
        ORPHAN_OK.clear()
        ORPHAN_OK.update(saved)

    if failures:
        for failure in failures:
            print('  !! selftest ' + failure)
        die(1, 'MATRIX FAIL: 自检 %d 条不通过' % len(failures))
    print('COVERAGE_MATRIX SELFTEST PASS (5 fixtures)')


def main():''',
    'selftest body')

one('''    parser.add_argument('--check', action='store_true', help='只校验，不写盘')
    args = parser.parse_args()''',
    '''    parser.add_argument('--check', action='store_true', help='只校验，不写盘')
    parser.add_argument('--selftest', action='store_true',
                        help='先跑扫描器自己的对抗性夹具（闸门里也跑）')
    args = parser.parse_args()

    if args.selftest:
        selftest()''',
    'cli flag')

io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('selftest added')
