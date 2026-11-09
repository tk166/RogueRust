"""§314 负控：两条判据各自抓什么。

1. **出招节奏**：给 Mugger 加一条"第 1 回合用 Lunge"的高优先级规则 ⇒
   `the_mugger_mugs_steals_fifteen_gold_and_escapes_with_it` 必须红。
   （这条正是"和 Looter 同一套"的唯一可观察证据 —— 少了它，规则表怎么改都没人管。）
2. **带钱跑**：把 `mugger.escape` 里的 `carryAwayStolenGold` 拿掉 ⇒ 同一判据必须红
   （`gold_carried_away` 停在 0）。

两处都要**同时**改 `Monsters` 与遭遇里的敌人记录副本 —— §313 的教训。
"""
import io
import json
import subprocess
import sys

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
BUILD = 'D:/Vibe/sts-tui/tools/contentc/build.py'
CARGO = 'C:/Users/TK11/.cargo/bin/cargo.exe'
MANIFEST = 'D:/Vibe/sts-tui/kernel/Cargo.toml'
TEST = 'the_mugger_mugs_steals_fifteen_gold_and_escapes_with_it'


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors='replace')


def mugger_records(doc):
    monster = next(m for m in doc['Monsters'] if m['Id'] == 'mugger')
    encounter = next(e for e in doc['Encounters'] if e['Id']['Value'] == 'enc_two_thieves')
    enemy = next(en for en in encounter['Enemies'] if en['Id'] == 'mugger')
    return monster, enemy


def wrong_pattern(doc):
    rule = {
        'Condition': {'kind': 'intent.allOf',
                      'value': {'Conditions': [
                          {'kind': 'intent.round', 'value': {'Op': 'Equal', 'Round': 1}}]}},
        'Priority': 99,
        'Action': {'value': 'mugger.lunge'},
    }
    for record in mugger_records(doc):
        record['IntentRules'] = [rule] + record['IntentRules']


def no_carry_away(doc):
    action = next(a for a in doc['EnemyActions'] if a['Id'] == 'mugger.escape')
    children = action['Program']['Root']['value']['Children']
    assert children[0]['kind'] == 'node.carryAwayStolenGold'
    action['Program']['Root']['value']['Children'] = [
        child for child in children if child['kind'] != 'node.carryAwayStolenGold']


CASES = [('第 1 回合改成 Lunge', wrong_pattern), ('Escape 不带走钱', no_carry_away)]


def main():
    original = io.open(CONTENT, encoding='utf-8').read()
    bad = 0
    try:
        for label, mutate in CASES:
            doc = json.loads(original)
            mutate(doc)
            io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
                json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
            built = run(['python', '-X', 'utf8', BUILD, '--package', 'sts'])
            if 'CONTENTC_BUILD OK' not in (built.stdout or '') + (built.stderr or ''):
                print('%-20s -> BUILD FAILED' % label)
                bad += 1
                continue
            out = run([CARGO, 'test', '-p', 'rd-wasm', '--manifest-path', MANIFEST, '--release',
                       '--', '--test-threads=1', 'the_mugger_mugs'])
            blob = (out.stdout or '') + (out.stderr or '')
            red = 'test result: FAILED' in blob or 'panicked' in blob or 'error[' in blob
            print('%-20s -> %s' % (label, 'RED (good)' if red else 'STILL GREEN (bad!)'))
            if not red:
                bad += 1
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
        run(['python', '-X', 'utf8', BUILD, '--package', 'sts'])
    print('负控完成：%d/%d 按预期变红' % (len(CASES) - bad, len(CASES)))
    sys.exit(1 if bad else 0)


main()
