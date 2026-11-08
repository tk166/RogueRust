"""§295 负控：把 `BlockBroken` 的每一环改坏，判据必须红。

四条对应四个真会犯的错：
① 不看"原本有格挡" ⇒ 每次攻击都加易伤；
② 不看"打穿了" ⇒ 只擦掉一点也加；
③ 不看 `source != target` ⇒ 自己打自己也加；
④ 内容里把目标槽写成 `sel.source` ⇒ 易伤落在英雄身上（**最难发现的一种**：
   它有"效果"，只是落在了错的人身上）。
"""
import io
import json
import subprocess
import sys

EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'
TEST = 'breaking_a_block_applies_vulnerable_on_the_target_only'


def cargo_test():
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-core', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', TEST],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def build_content():
    out = subprocess.run([sys.executable, '-X', 'utf8',
                          'D:/Vibe/sts-tui/tools/contentc/build.py', '--package', 'sts'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return 'CONTENTC_BUILD_OK' in (out.stdout + out.stderr).replace(' ', '_')


CASES = [
    ('不看"原本有格挡"', '''    if !ignores_block && block_before > 0 && blocked == block_before {''',
     '''    if !ignores_block && blocked == block_before {'''),
    ('不看"打穿了"', '''    if !ignores_block && block_before > 0 && blocked == block_before {''',
     '''    if !ignores_block && block_before > 0 {'''),
    ('不看 source != target', '''            if source != *target {''',
     '''            if true {'''),
]


def main():
    original = io.open(EXEC, encoding='utf-8').read()
    failures = 0
    try:
        for label, good, bad in CASES:
            assert original.count(good) == 1, (label, original.count(good))
            io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(original.replace(good, bad))
            passed, output = cargo_test()
            print('%-30s -> %s' % (label, 'RED as expected' if not passed
                                   else 'STILL GREEN (not watching)'))
            if passed:
                failures += 1
                print(output[-400:])
            io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(original)
    finally:
        io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(original)

    # ④ 内容侧：把目标槽从 `sel.eventTarget` 换成 `sel.source`（易伤落到英雄身上）。
    content_original = io.open(CONTENT, encoding='utf-8').read()
    try:
        doc = json.loads(content_original)
        status = next(s for s in doc['Statuses'] if s['Id'] == 'standard.hand_drill')
        root = status['Triggers'][0]['Program']['Root']['value']
        assert root['TargetSelector']['kind'] == 'sel.eventTarget'
        root['TargetSelector'] = {
            'kind': 'sel.source',
            'value': {'Cardinality': 'ZeroOrOne',
                      'RequiredContextCapabilities': 'Source'},
        }
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(doc, ensure_ascii=False, indent=2) + chr(10))
        assert build_content(), 'the broken content must build'
        passed, output = cargo_test()
        print('%-30s -> %s' % ('内容里目标槽写成 sel.source',
                               'RED as expected' if not passed else 'STILL GREEN'))
        if passed:
            failures += 1
            print(output[-400:])
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(content_original)
        assert build_content(), 'restore must rebuild'

    passed, _ = cargo_test()
    assert passed, 'restore must make the test green again'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
