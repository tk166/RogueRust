"""§283 负控：两条新判据各自必须真的会红。

① "Bite 不连三次"——把规则从内容里**删掉** ⇒ 判据必须红（否则那条判据只是在验
   "`select_action` 能跑"，那它一个字都没证明）；
② Snecko Eye——把遗物的映射**去掉** ⇒ 抽 7 张那条必须红。
"""
import io
import json
import subprocess
import sys

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
BUILD = 'D:/Vibe/sts-tui/tools/contentc/build.py'
STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'


def build():
    out = subprocess.run([sys.executable, '-X', 'utf8', BUILD, '--package', 'sts'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return 'CONTENTC_BUILD OK' in (out.stdout + out.stderr)


def rust(test):
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-wasm', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    failures = 0
    original = io.open(CONTENT, encoding='utf-8').read()

    # ① 删掉"连两次 Bite ⇒ Tail Whip"那条规则
    doc = json.loads(original)
    for monster in doc['Monsters']:
        if monster['Id'] == 'snecko':
            monster['IntentRules'] = [r for r in monster['IntentRules']
                                      if r.get('Priority') != 95]
    for enc in doc['Encounters']:
        eid = enc['Id']['Value'] if isinstance(enc['Id'], dict) else enc['Id']
        if eid == 'enc_snecko':
            for enemy in enc['Enemies']:
                enemy['IntentRules'] = [r for r in enemy['IntentRules']
                                        if r.get('Priority') != 95]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    if not build():
        print('%-30s -> BUILD FAILED' % 'no-3x-bite rule removed')
        failures += 1
    else:
        passed, text = rust('snecko_never_bites_three_times_in_a_row')
        print('%-30s -> %s' % ('no-3x-bite rule removed',
                               'RED as expected' if not passed else 'STILL GREEN'))
        if passed:
            failures += 1
            print(text[-400:])
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)

    # ② 遗物映射删掉（`snecko_eye` 不再挂状态）
    state_original = io.open(STATE, encoding='utf-8').read()
    anchor = '''            "snecko_eye" => Some(RelicEffect::StartCombatStatus("standard.snecko_eye", 1)),'''
    assert state_original.count(anchor) == 1
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(
        state_original.replace(anchor, '            // negative control: no mapping'))
    passed, text = rust('snecko_eye_draws_two_more_and_confuses_at_the_start')
    print('%-30s -> %s' % ('no relic mapping',
                           'RED as expected' if not passed else 'STILL GREEN'))
    if passed:
        failures += 1
        print(text[-400:])
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(state_original)

    assert build(), 'restore must rebuild'
    for test in ('snecko_never_bites_three_times_in_a_row',
                 'snecko_eye_draws_two_more_and_confuses_at_the_start'):
        passed, _ = rust(test)
        assert passed, 'restore must make %s green again' % test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
