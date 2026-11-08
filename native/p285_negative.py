"""§285 负控：事件概率/区间/升级链，四条判据各自必须真的会红。

前两条改**内核**（随机流是内核的事），后两条改**内容**（升级链是内容的表）。
"""
import io
import json
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
BUILD = 'D:/Vibe/sts-tui/tools/contentc/build.py'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'


def rust(package, test):
    out = subprocess.run(
        [CARGO, 'test', '-p', package, '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def build():
    out = subprocess.run([sys.executable, '-X', 'utf8', BUILD, '--package', 'sts'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return 'CONTENTC_BUILD OK' in (out.stdout + out.stderr)


def main():
    failures = 0

    def mutate(path, label, old, new, package, test):
        nonlocal failures
        original = io.open(path, encoding='utf-8').read()
        assert original.count(old) == 1, ('anchor moved: ' + label, original.count(old))
        io.open(path, 'w', encoding='utf-8', newline='\n').write(original.replace(old, new))
        if path == CONTENT and not build():
            print('%-32s -> BUILD FAILED' % label)
            failures += 1
            io.open(path, 'w', encoding='utf-8', newline='\n').write(original)
            return
        passed, text = rust(package, test)
        print('%-32s -> %s' % (label, 'RED as expected' if not passed else 'STILL GREEN'))
        if passed:
            failures += 1
            print(text[-400:])
        io.open(path, 'w', encoding='utf-8', newline='\n').write(original)

    # ① 掷骰退化成"永远成功"
    mutate(STATE, 'roll always succeeds',
           '''                Some(if rolled < u32::from(roll.chance) {''',
           '''                Some(if true {''',
           'rd-run', 'an_event_roll_takes_both_branches')

    # ② 区间金币退化成下限常数
    mutate(STATE, 'gold_random is a constant',
           '''                let delta = low.saturating_add(roll as i32);''',
           '''                let delta = low;''',
           'rd-run', 'gold_random_stays_inside_its_range_and_covers_it')

    # ③ 升级链断掉：第 3 段与第 2 段相同（代价不再递增）
    def break_chain(text):
        doc = json.loads(text)
        steps = {n['Id']: n for n in doc['EventNodes']}
        steps['scrap_pile.try3']['Options'][0]['Effects'] = \
            list(steps['scrap_pile.try2']['Options'][0]['Effects'])
        return json.dumps(doc, ensure_ascii=False, indent=2) + '\n'

    original = io.open(CONTENT, encoding='utf-8').read()
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(break_chain(original))
    if not build():
        print('%-32s -> BUILD FAILED' % 'escalation broken')
        failures += 1
    else:
        passed, text = rust('rd-core', 'the_unknown_room_events_are_readable')
        print('%-32s -> %s' % ('escalation broken',
                               'RED as expected' if not passed else 'STILL GREEN'))
        if passed:
            failures += 1
            print(text[-400:])
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)

    # ④ 概率与失败边不成对（内容门必须红）
    doc = json.loads(original)
    for node in doc['EventNodes']:
        if node['Id'] == 'scrap_pile':
            node['Options'][0].pop('NextFail', None)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    if not build():
        print('%-32s -> BUILD FAILED' % 'Chance without NextFail')
        failures += 1
    else:
        out = subprocess.run([sys.executable, '-X', 'utf8',
                              'D:/Vibe/sts-tui/native/sts_content_check.py'],
                             capture_output=True, text=True, encoding='utf-8', errors='replace')
        text = out.stdout + out.stderr
        hit = out.returncode != 0 and 'must come together' in text
        print('%-32s -> %s' % ('Chance without NextFail',
                               'RED as expected' if hit else 'STILL GREEN'))
        if not hit:
            failures += 1
            print(text[-400:])
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)

    assert build(), 'restore must rebuild'
    for package, test in (('rd-run', 'an_event_roll_takes_both_branches'),
                          ('rd-run', 'gold_random_stays_inside_its_range_and_covers_it'),
                          ('rd-core', 'the_unknown_room_events_are_readable')):
        passed, _ = rust(package, test)
        assert passed, 'restore must make %s green again' % test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
