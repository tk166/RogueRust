"""§344 负控：五条，每条都必须让**指定的**判据红。

| # | 弄坏什么 | 哪条判据该红 |
|---|---|---|
| ① | `run_end()` 不看血量 | `the_run_end_is_a_function_of_the_state`（Defeat 那格） |
| ② | `run_end()` 把前两幕的 `boss_beaten` 当成通关 | 同上（"clearing act 1 is not winning"） |
| ③ | `end_act()` 不检查 `reachable()` | `ending_an_act_requires_that_there_is_nothing_left_to_do` |
| ④ | `rd_run_rest_heal()` 只返回 30%（丢掉遗物加成） | `the_run_end_and_rest_heal_come_from_the_kernel` |
| ⑤ | 删掉 `BEAT_DESTROYED` 常量（改回 12） | `every_beat_kind_has_an_abi_constant` |

⚠️ 每条都断言**具体失败文本**：只断言"有测试红了"的话，一条编译错会让五条全部假装成功。
"""

import io
import subprocess
import sys

STATE = 'kernel/rd-run/src/state.rs'
RUN = 'kernel/rd-wasm/src/run.rs'
LIB = 'kernel/rd-wasm/src/lib.rs'


def run(pkg, test_name):
    args = ['cargo', 'test', '-p', pkg, '--release']
    if pkg == 'rd-wasm':
        args += ['--', '--test-threads=1']
    args.append(test_name)
    p = subprocess.run(args, cwd='kernel', capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def case(label, path, pkg, pairs, test_name, needle):
    raw = io.open(path, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(broken)
        out = run(pkg, test_name)
        ok = needle in out and test_name in out
        print('  %-50s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'panicked' in line or 'error[' in line or 'test result' in line:
                    print('      ', line.strip()[:140])
                    break
    finally:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

ok &= case(
    '① run_end 不看血量',
    STATE, 'rd-run',
    [('''        if self.health <= 0 {
            return RunEnd::Defeat;
        }''',
      '''        if false {
            return RunEnd::Defeat;
        }''')],
    'the_run_end_is_a_function_of_the_state',
    'zero health is a defeat',
)

ok &= case(
    '② run_end 把前两幕的 boss_beaten 当成通关',
    STATE, 'rd-run',
    [('''        if self.act >= MAX_ACT && self.boss_beaten {''',
      '''        if self.boss_beaten {''')],
    'the_run_end_is_a_function_of_the_state',
    'clearing act 1 is not winning the run',
)

ok &= case(
    '③ end_act 不检查 reachable()',
    STATE, 'rd-run',
    [('''        if !self.reachable().is_empty() {
            return Err(RunError::MapNotExhausted);
        }''',
      '''        if false {
            return Err(RunError::MapNotExhausted);
        }''')],
    'ending_an_act_requires_that_there_is_nothing_left_to_do',
    'assertion `left == right` failed',
)

ok &= case(
    '④ rest_heal 丢掉遗物加成',
    RUN, 'rd-wasm',
    [('''    run_slot().as_ref().map_or(-1, |s| s.state.rest_heal())''',
      '''    run_slot()
        .as_ref()
        .map_or(-1, |s| s.state.health_max() * 30 / 100)''')],
    'the_run_end_and_rest_heal_come_from_the_kernel',
    'regal_pillow adds 15',
)

ok &= case(
    '⑤ BEAT_DESTROYED 改回 12（漏掉 13）',
    LIB, 'rd-wasm',
    [('''pub const BEAT_DESTROYED: i32 = 13;''',
      '''pub const BEAT_DESTROYED: i32 = 12;''')],
    'every_beat_kind_has_an_abi_constant',
    'the ABI value must be its position',
)

out = run('rd-run', '')
print('  还原后 rd-run：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
