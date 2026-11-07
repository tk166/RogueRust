"""§281 负控：随机流的三条判据各自必须真的会红。

⚠️ 手法与其它负控不同：这里改的是**内核源码**（不是内容），因为"随机流坏了"不是内容能
表达的一件事。每次改一处 → 跑一条判据 → 还原，并断言"还原后确实又绿了"（否则后面几条
判据都是在半改的文件上跑）。
"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-core/src/state.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'


def rust(package, name):
    out = subprocess.run(
        [CARGO, 'test', '-p', package, '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', name],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    original = io.open(STATE, encoding='utf-8').read()
    failures = 0

    def mutate(name, old, new, package, test, label):
        nonlocal failures
        assert original.count(old) == 1, ('the anchor moved: ' + label, original.count(old))
        io.open(STATE, 'w', encoding='utf-8', newline='\n').write(original.replace(old, new))
        passed, text = rust(package, test)
        red = not passed
        print('%-28s -> %s' % (label, 'RED as expected' if red else 'STILL GREEN'))
        if not red:
            failures += 1
            print(text[-500:])
        io.open(STATE, 'w', encoding='utf-8', newline='\n').write(original)

    # ① 永远返回下限（"随机"退化成常数）
    mutate('min-always',
           '''        let value = crate::rng::draw_u32(self.random_seed, self.random_step);''',
           '''        let value = 0u32;''',
           'rd-core', 'a_draw_covers_its_whole_range_and_advances_one_step',
           'always the low end')

    # ② 不推进 step（两次抽取给同一个数）
    mutate('no-step',
           '''        self.random_step = self.random_step.saturating_add(1);''',
           '''        // negative control: step frozen''',
           'rd-core', 'a_draw_covers_its_whole_range_and_advances_one_step',
           'step never advances')

    # ③ 只读 seed、忽略 step（抽取与洗牌分家）
    mutate('seed-only',
           '''        let value = crate::rng::draw_u32(self.random_seed, self.random_step);''',
           '''        let value = crate::rng::draw_u32(self.random_seed, 0);''',
           'rd-core', 'a_draw_sequence_replays_from_its_seed',
           'seed only, step ignored')

    # ④ 显示侧不读绝对覆盖（价格"看起来随机"但屏幕上不变）
    lib = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
    lib_original = io.open(lib, encoding='utf-8').read()
    old = '''            if let Some(absolute) = override_cost {
                cost = absolute.max(0);
            } else if cost > 0 {'''
    assert lib_original.count(old) == 1
    io.open(lib, 'w', encoding='utf-8', newline='\n').write(
        lib_original.replace(old, '''            if false {
                cost = 0;
            } else if cost > 0 {'''))
    passed, text = rust('rd-wasm', 'the_price_roll_is_reproducible_and_costs_one_step_per_card')
    print('%-28s -> %s' % ('display ignores override',
                           'RED as expected' if not passed else 'STILL GREEN'))
    if passed:
        failures += 1
        print(text[-500:])
    io.open(lib, 'w', encoding='utf-8', newline='\n').write(lib_original)

    # 还原后必须又绿（否则上面几条的"红"可能来自一个半改的文件）
    for package, test in (
        ('rd-core', 'a_draw_covers_its_whole_range_and_advances_one_step'),
        ('rd-wasm', 'the_price_roll_is_reproducible_and_costs_one_step_per_card'),
    ):
        passed, _ = rust(package, test)
        assert passed, 'restore must make %s green again' % test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
