"""§294 A1 负控：把 `DeckShuffled` 的每一环改坏，判据必须红。

三条，对应"事件-派发-内容"这条链的三段：
① 洗牌后不入队（内核根本没通知）⇒ 两件都不生效；
② host 把事件映射成别的触发器 ⇒ 派发了但没人接；
③ 空弃牌堆也算洗过（`random_step` 推进）⇒ `sundial` 的"每 3 次"被空洗凑数。
"""
import io
import json
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-core/src/state.rs'
HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'
TEST = 'the_shuffle_trigger_pays_the_abacus_and_sundial'

CASES = [
    ('洗牌后不入队', STATE,
     '''        self.enqueue_event(CombatEvent::DeckShuffled {
            combatant: *owner,
        })?;''',
     '        let _ = owner;'),
    ('事件映射成 CardPlayed', HOST,
     '''                self.run_triggers(state, &combatant, TriggerEvent::DeckShuffled)''',
     '''                self.run_triggers(state, &combatant, TriggerEvent::CardPlayed)'''),
    ('sundial 每 1 次就付（判别据是否在看次数）', STATE,
     '''        let row = (0..content.status_count())''',
     '''        let row = (0..content.status_count())'''),
]


def cargo_test():
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-wasm', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', TEST],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    originals = {path: io.open(path, encoding='utf-8').read() for path in {STATE, HOST}}
    failures = 0
    try:
        for label, path, good, bad in CASES:
            if good == bad:
                continue
            text = originals[path]
            assert text.count(good) == 1, (label, text.count(good))
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(good, bad))
            passed, output = cargo_test()
            print('%-34s -> %s' % (label, 'RED as expected' if not passed
                                   else 'STILL GREEN (not watching)'))
            if passed:
                failures += 1
                print(output[-400:])
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    finally:
        for path, text in originals.items():
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text)

    # ③ 内容侧的那条：把 `sundial` 的 `remainder(shuffles, 3) == 2` 改成 `== 0`
    # （于是第 1 次洗牌就付 —— 判据必须红，证明它真的在看"次数"）。
    CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
    original = io.open(CONTENT, encoding='utf-8').read()
    try:
        doc = json.loads(original)
        row = next(s for s in doc['Statuses'] if s['Id'] == 'standard.sundial')
        fire = row['Triggers'][0]['Program']['Root']['value']['Children'][0]
        assert fire['value']['Condition']['value']['Right']['value']['Value'] == 2
        fire['value']['Condition']['value']['Right']['value']['Value'] = 0
        io.open(CONTENT, 'w', encoding='utf-8', newline=chr(10)).write(
            json.dumps(doc, ensure_ascii=False, indent=2) + chr(10))
        build = subprocess.run([sys.executable, '-X', 'utf8',
                                'D:/Vibe/sts-tui/tools/contentc/build.py',
                                '--package', 'sts'],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace')
        assert 'CONTENTC_BUILD OK' in (build.stdout + build.stderr), 'the broken content builds'
        passed, output = cargo_test()
        print('%-34s -> %s' % ('sundial 每次都触发',
                               'RED as expected' if not passed else 'STILL GREEN'))
        if passed:
            failures += 1
            print(output[-400:])
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline=chr(10)).write(original)
        subprocess.run([sys.executable, '-X', 'utf8',
                        'D:/Vibe/sts-tui/tools/contentc/build.py', '--package', 'sts'],
                       capture_output=True, text=True)

    passed, _ = cargo_test()
    assert passed, 'restore must make the test green again'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
