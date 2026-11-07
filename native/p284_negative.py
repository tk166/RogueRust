"""§284 负控：两条新判据各自必须真的会红。

① **内容门**：把 `snecko_eye` 的触发器改回 `sel.eventTarget` ⇒ `[6g]` 必须红
   （这正是 §283 真踩的坑：状态静默没挂上）；
② **内核**：`TurnStarted` 触发器里的 `combatantCounter(sel.source)` **真的读到**拥有者的
   计数器 —— 判据是"第二回合不再重挂 Confused"（若读数恒 0，条件恒真、会重挂）。
   手法：把条件里的 `== 0` 改成 `== 999`（永远不成立）⇒ 首回合就不该挂上 ⇒ 判据红；
   再把它改回 `== 0` ⇒ 绿。
"""
import io
import json
import subprocess
import sys

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'
BUILD = 'D:/Vibe/sts-tui/tools/contentc/build.py'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'


def build():
    out = subprocess.run([sys.executable, '-X', 'utf8', BUILD, '--package', 'sts'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return 'CONTENTC_BUILD OK' in (out.stdout + out.stderr)


def check():
    out = subprocess.run([sys.executable, '-X', 'utf8', CHECK],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return out.returncode, out.stdout + out.stderr


def rust(test):
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-wasm', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def eye(doc):
    return [x for x in doc['Statuses'] if x['Id'] == 'standard.snecko_eye'][0]


def main():
    failures = 0
    original = io.open(CONTENT, encoding='utf-8').read()

    # ① 内容门：无目标触发器里用 sel.eventTarget
    doc = json.loads(original)
    root = eye(doc)['Triggers'][0]['Program']['Root']
    apply_node = root['value']['Children'][0]['value']['Then']
    assert apply_node['kind'] == 'node.applyStatus'
    apply_node['value']['TargetSelector'] = {
        'kind': 'sel.eventTarget',
        'value': {'Cardinality': 'ZeroOrOne',
                  'RequiredContextCapabilities': 'EventTarget'},
    }
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    if not build():
        print('%-34s -> BUILD FAILED' % 'eventTarget in a targetless trigger')
        failures += 1
    else:
        code, text = check()
        hit = code != 0 and 'no target' in text
        print('%-34s -> %s' % ('eventTarget in targetless trigger',
                               'RED as expected' if hit else 'STILL GREEN'))
        if not hit:
            failures += 1
            for line in text.split('\n'):
                if 'FAIL' in line or 'targetless' in line:
                    print('   saw: ' + line[:150])
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)

    # ② 内核：把条件改成永假 ⇒ 首回合就不挂 Confused ⇒ 判据红
    doc = json.loads(original)
    root = eye(doc)['Triggers'][0]['Program']['Root']
    compare = root['value']['Children'][0]['value']['Condition']['value']
    assert compare['Right']['value']['Value'] == 0, compare
    compare['Right']['value']['Value'] = 999
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    if not build():
        print('%-34s -> BUILD FAILED' % 'counter condition never true')
        failures += 1
    else:
        passed, text = rust('snecko_eye_draws_two_more_and_confuses_at_the_start')
        print('%-34s -> %s' % ('counter condition never true',
                               'RED as expected' if not passed else 'STILL GREEN'))
        if passed:
            failures += 1
            print(text[-400:])

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
    assert build(), 'restore must rebuild'
    code, text = check()
    assert code == 0 and 'STS_CONTENT PASS' in text, 'restore must pass the gate'
    passed, _ = rust('snecko_eye_draws_two_more_and_confuses_at_the_start')
    assert passed, 'restore must make the kernel test green'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
