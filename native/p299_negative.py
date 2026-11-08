"""§299 负控：三件纯内容程序的三环各改坏一次（都改**内容**再重编）。

① `enchiridion` 的 `CostZero` 改成 false ⇒ 那张牌不再免费；
② `dead_branch` 的池子 tag 从 `*` 改成 `power` ⇒ 加进来的不是"任意牌"（而且必然漏掉大多数）；
③ `orange_pellets` 的判据只看两个计数器（去掉第三条）⇒ 两类就付。
"""
import io
import json
import subprocess
import sys

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'


def build():
    out = subprocess.run([sys.executable, '-X', 'utf8',
                          'D:/Vibe/sts-tui/tools/contentc/build.py', '--package', 'sts'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return 'CONTENTC_BUILD OK' in (out.stdout + out.stderr), out.stdout + out.stderr


def cargo_test(test):
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-core', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    original = io.open(CONTENT, encoding='utf-8').read()
    failures = 0

    def case(label, mutate, test):
        nonlocal failures
        doc = json.loads(original)
        mutate(doc)
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(doc, ensure_ascii=False, indent=2) + chr(10))
        ok, output = build()
        if not ok:
            print('%-30s -> BUILD FAILED (negative control is invalid)' % label)
            print(output[-300:])
            failures += 1
            return
        passed, output = cargo_test(test)
        print('%-30s -> %s' % (label, 'RED as expected' if not passed
                               else 'STILL GREEN (not watching)'))
        if passed:
            failures += 1
            print(output[-300:])

    def find(doc, status_id):
        return next(s for s in doc['Statuses'] if s['Id'] == status_id)

    def no_cost_zero(doc):
        row = find(doc, 'standard.enchiridion')
        root = row['Triggers'][0]['Program']['Root']['value']['Children'][0]['value']['Then']
        assert root['value']['CostZero'] is True
        root['value']['CostZero'] = False

    def power_only_pool(doc):
        row = find(doc, 'standard.dead_branch')
        root = row['Triggers'][0]['Program']['Root']
        assert root['value']['Tag'] == '*'
        root['value']['Tag'] = 'power'

    def two_counters_only(doc):
        row = find(doc, 'standard.orange_pellets')
        # 三支里的第三支（skill）去掉整个"付钱"判断 ⇒ 两类齐了就付。
        children = row['Triggers'][0]['Program']['Root']['value']['Children']
        assert len(children) == 3
        paid = children[2]['value']['Then']['value']['Children'][1]
        children[2]['value']['Then']['value']['Children'][1] = {
            'kind': 'node.conditional',
            'value': {
                'Condition': {
                    'kind': 'compare',
                    'value': {
                        'Left': {'kind': 'const', 'value': {'Value': 1}},
                        'Right': {'kind': 'const', 'value': {'Value': 1}},
                        'Op': 'Equal',
                    },
                },
                'Then': paid['value']['Then'],
                'Else': None,
            },
        }

    try:
        case('enchiridion: 不免费', no_cost_zero, 'enchiridion_adds_a_free_power_card')
        case('dead_branch: 池子只要 power', power_only_pool, 'dead_branch_adds_a_random_base_card')
        case('orange_pellets: 只看两个计数器', two_counters_only,
             'orange_pellets_pays_once_all_three_card_kinds')
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
        ok, _ = build()
        assert ok, 'restore must rebuild'

    for test in ('enchiridion_adds_a_free_power_card',
                 'dead_branch_adds_a_random_base_card',
                 'orange_pellets_pays_once_all_three_card_kinds'):
        passed, _ = cargo_test(test)
        assert passed, 'restore failed for ' + test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
