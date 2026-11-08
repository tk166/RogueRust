"""§297 负控：三件的每一环各改坏一次。

`strike_dummy`（内容规则）：
  ① 去掉"来源卡标签"那道门 ⇒ `bash` 也 +3；
`velvet_choker`（内核规则）：
  ② 上限改成 99 ⇒ 第 7 张照打；③ `>=` 改成 `>` ⇒ 第 7 张还能打；
`runic_dome`（观测）：
  ④ 状态查**敌人**而不是英雄（这一轮真踩过的写法）⇒ 意图仍是真意图。
"""
import io
import json
import subprocess
import sys

PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
WASM_LIB = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'


def cargo_test(package, test):
    out = subprocess.run(
        [CARGO, 'test', '-p', package, '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


RUST_CASES = [
    ('velvet: 上限改成 99', PLAY, '''pub const VELVET_CHOKER_CAP: i32 = 6;''',
     '''pub const VELVET_CHOKER_CAP: i32 = 99;''',
     'rd-core', 'velvet_choker_stops_the_seventh_card_of_the_turn'),
    ('velvet: >= 改成 >', PLAY,
     '''    if state.cards_played_this_turn >= VELVET_CHOKER_CAP {''',
     '''    if state.cards_played_this_turn > VELVET_CHOKER_CAP {''',
     'rd-core', 'velvet_choker_stops_the_seventh_card_of_the_turn'),
    ('runic_dome: 查敌人而不是英雄', WASM_LIB,
     '''                .is_some_and(|hero| {
                    Self::combatant_has_status(&self.state, &hero, Self::RUNIC_DOME_STATUS)
                });''',
     '''                .is_some_and(|_hero| {
                    Self::combatant_has_status(&self.state, &id, Self::RUNIC_DOME_STATUS)
                });''',
     'rd-wasm', 'runic_dome_blinds_the_intent_observation'),
]


def build_content():
    out = subprocess.run([sys.executable, '-X', 'utf8',
                          'D:/Vibe/sts-tui/tools/contentc/build.py', '--package', 'sts'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return 'CONTENTC_BUILD_OK' in (out.stdout + out.stderr).replace(' ', '_')


def main():
    failures = 0
    originals = {}
    for _, path, _, _, _, _ in RUST_CASES:
        originals.setdefault(path, io.open(path, encoding='utf-8').read())
    try:
        for label, path, good, bad, package, test in RUST_CASES:
            text = originals[path]
            assert text.count(good) == 1, (label, text.count(good))
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(good, bad))
            passed, output = cargo_test(package, test)
            print('%-34s -> %s' % (label, 'RED as expected' if not passed
                                   else 'STILL GREEN (not watching)'))
            if passed:
                failures += 1
                print(output[-400:])
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    finally:
        for path, text in originals.items():
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text)

    # ④ 内容侧：`strike_dummy` 的 +3 去掉来源卡标签门 ⇒ `bash` 也 +3。
    content_original = io.open(CONTENT, encoding='utf-8').read()
    try:
        doc = json.loads(content_original)
        row = next(s for s in doc['Statuses'] if s['Id'] == 'standard.strike_dummy')
        modifier = row['PassiveModifiers'][0]
        assert modifier['RestrictSourceCardTag'] == {'value': 'strike'}
        modifier['RestrictSourceCardTag'] = None
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(doc, ensure_ascii=False, indent=2) + chr(10))
        assert build_content(), 'the broken content must build'
        passed, output = cargo_test('rd-core',
                                    'strike_dummy_only_boosts_cards_that_carry_the_strike_tag')
        print('%-34s -> %s' % ('strike_dummy: 去掉标签门',
                               'RED as expected' if not passed else 'STILL GREEN'))
        if passed:
            failures += 1
            print(output[-400:])
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(content_original)
        assert build_content(), 'restore must rebuild'

    for _, path, _, _, package, test in RUST_CASES:
        passed, _ = cargo_test(package, test)
        assert passed, 'restore failed for ' + test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
