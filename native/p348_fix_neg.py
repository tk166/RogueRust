"""修 §348 负控③：把 `i32::MIN` 边界写进**真判据**，负控改成弄坏 `rd_run_exists`。

第一版把"通过"的断言**注入**测试里 —— 注入了也不红，因为注入的东西是对的。
负控必须弄坏**被测代码**，不能弄坏"检查"。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'
NEG = 'native/p348_negative.py'


def sub(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① 边界进真判据 ──────────────────────────────────────────────────────────
sub(RUN, '''        reset(7);
        assert_eq!(rd_run_exists(), 1, "a run exists");''',
    '''        // ④ P2-1 的边界：`i32::MIN` 是**合法 seed**（`rd_run_start` 不拒绝它），
        //    所以"有没有局"不能拿它当哨兵 —— 这一局必须被认成"有局"。
        assert_eq!(
            rd_run_start(i32::MIN, 0),
            0,
            "i32::MIN is a legal seed: {}",
            run_error_text()
        );
        assert_eq!(
            rd_run_exists(),
            1,
            "a run started with i32::MIN still EXISTS -- `noRun` must not use the seed"
        );
        assert_ne!(
            rd_run_boss_id_len(),
            -1,
            "…and it is a real run, not 'no run'"
        );

        reset(7);
        assert_eq!(rd_run_exists(), 1, "a run exists");''', 'boundary into test')

# ── ② 负控③ 重写 ──────────────────────────────────────────────────────────
t = io.open(NEG, encoding='utf-8').read()
start = t.index('# ③ P2-1')
end = t.index('# ④ P2-2')
NEW = '''# ③ P2-1：把"seed 哨兵"塞回 `rd_run_exists` —— 用 `i32::MIN` 开的那一局会被判成"没有局"。
ok &= case_rust(
    '③ `rd_run_exists` 退回 seed 哨兵（P2-1 的原 bug）',
    [("""pub extern "C" fn rd_run_exists() -> i32 {
    i32::from(run_slot().as_ref().is_some())
}""",
      """pub extern "C" fn rd_run_exists() -> i32 {
    run_slot()
        .as_ref()
        .map_or(0, |s| i32::from(s.state.seed() != i32::MIN))
}""")],
    'the_boss_id_names_the_actual_boss_not_the_pool_head',
    'still EXISTS',
)

'''
t = t[:start] + NEW + t[end:]
io.open(NEG, 'w', encoding='utf-8', newline='\n').write(t)
print('control ③ now breaks the export, not the check')
