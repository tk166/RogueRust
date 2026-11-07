"""§279 负控：条件机制的四条判据必须真的会红。

前三条走**内容门**（改 JSON → 重编 → 跑门），第四条走**镜像里那一条真条件**
（把 `relic` 换成一条数值条件，`rd-core` 的"两侧"判据必须红，因为无遗物的那一侧
现在会变成"可选"）。

⚠️ 判据是"**红在这一处**"，不是"红了几条"：一个坏改动若只是把断言打到别处，
它证明的不是这一条判据还活着。
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


def rust(name):
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-core', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', name],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    original = io.open(CONTENT, encoding='utf-8').read()
    failures = 0

    def option(doc):
        node = [n for n in doc['EventNodes'] if n['Id'] == 'forgotten_altar'][0]
        return node['Options'][0]

    def run_gate(name, mutate, expect):
        nonlocal failures
        doc = json.loads(original)
        mutate(doc)
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
        if not build():
            print('%-24s -> BUILD FAILED' % name)
            failures += 1
            return
        code, text = check()
        hit = expect in text and code != 0
        print('%-24s -> %s (exit %d)' % (name, 'RED as expected' if hit else 'STILL GREEN', code))
        if not hit:
            failures += 1
            for line in text.split('\n'):
                if 'FAIL' in line or 'Requires' in line:
                    print('   saw: ' + line[:150])

    def unknown_kind(doc):
        option(doc)['Requires'][0]['Kind'] = 'no_such_kind'

    def wrong_op(doc):
        option(doc)['Requires'][0]['Op'] = 'at_least'   # `relic` 没有 at_least

    def percent_zero(doc):
        option(doc)['Requires'][0] = {'Kind': 'health_percent', 'Op': 'at_most', 'Amount': 0}

    run_gate('unknown kind', unknown_kind, '词表外的条件')
    run_gate('op does not fit kind', wrong_op, "does not fit Kind")
    run_gate('percentage 0', percent_zero, 'outside 1..=100')

    # ── 第四条：把那条真条件换成一条**在这个 fixture 上不成立**的数值条件，内核的
    # "两侧"判据必须红（因为"无遗物"那一侧现在会变成可选 —— 于是两测一样）。
    doc = json.loads(original)
    option(doc)['Requires'][0] = {'Kind': 'gold', 'Op': 'at_least', 'Amount': 0}
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    if not build():
        print('%-24s -> BUILD FAILED' % 'condition always true')
        failures += 1
    else:
        passed, text = rust('the_image_carries_a_real_requirement')
        red = not passed
        print('%-24s -> %s' % ('condition always true', 'RED as expected' if red else 'STILL GREEN'))
        if not red:
            failures += 1
            print(text[-600:])

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
    assert build(), 'restore must rebuild'
    code, text = check()
    assert code == 0 and 'STS_CONTENT PASS' in text, 'restore must pass the gate'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
