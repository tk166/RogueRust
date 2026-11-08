"""§300 负控：三个原子各改坏一次（都改**内容**再重编）。

① `warped_tongs` 去掉 `Random` ⇒ 永远升级牌区第一张（"位置随 seed 变化"那条红）；
② `mummified_hand` 去掉 `Random` ⇒ 同上；
③ `nilrys_codex` 把 `Then` 删掉 ⇒ 退回 `ToHandFree`（"进抽牌堆顶"那条红）。
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

    def find(doc, status_id):
        return next(s for s in doc['Statuses'] if s['Id'] == status_id)

    def drop_random(doc, status_id, path):
        node = find(doc, status_id)['Triggers'][0]['Program']['Root']
        for step in path:
            node = node[step]
        assert node['value']['Random'] is True
        node['value']['Random'] = False

    def drop_then(doc):
        node = find(doc, 'standard.nilrys_codex')['Triggers'][0]['Program']['Root']
        assert node['value']['Then'] == 'ToDrawPileTop'
        del node['value']['Then']

    cases = [
        ('warped_tongs: 去掉 Random',
         lambda doc: drop_random(doc, 'standard.warped_tongs', []),
         'warped_tongs_upgrades_a_random_card_not_the_first_one'),
        ('mummified_hand: 去掉 Random',
         lambda doc: drop_random(doc, 'standard.mummified_hand', ['value', 'Then']),
         'mummified_hand_makes_one_random_card_free_after_a_power'),
        ('nilrys_codex: 去掉 Then', drop_then,
         'nilrys_codex_asks_at_turn_end_and_sends_the_pick_to_the_draw_pile'),
    ]

    for label, mutate, test in cases:
        doc = json.loads(original)
        mutate(doc)
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(doc, ensure_ascii=False, indent=2) + chr(10))
        ok, output = build()
        if not ok:
            print('%-32s -> BUILD FAILED (invalid control)' % label)
            print(output[-300:])
            failures += 1
            continue
        passed, output = cargo_test(test)
        print('%-32s -> %s' % (label, 'RED as expected' if not passed
                               else 'STILL GREEN (not watching)'))
        if passed:
            failures += 1
            print(output[-300:])

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
    ok, _ = build()
    assert ok, 'restore must rebuild'
    for _, _, test in cases:
        passed, _ = cargo_test(test)
        assert passed, 'restore failed for ' + test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
