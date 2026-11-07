"""§277 负控：组合机制必须会红。

两处切口，都是"真会犯的错"：
1. **候选只写 `Id`**（不带 `Actions`/`IntentRules`）—— 组合出来的怪**没有招式**，
   而数量、类型、血量全都对，**只有行为错**。这正是第一版的错，判据里那条
   "`select_action` 必须给出选择"就是为它写的。
2. **固定在第一只候选上**（不掷骰）—— "组合"退化成固定组合，随机性没了。
"""
import io
import json
import subprocess
import sys

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
BUILD = 'D:/Vibe/sts-tui/tools/contentc/build.py'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'
TEST = 'the_composed_encounters_pick_from_their_candidates'


def build():
    out = subprocess.run([sys.executable, '-X', 'utf8', BUILD, '--package', 'sts'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return 'CONTENTC_BUILD OK' in (out.stdout + out.stderr)


def run_test():
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-wasm', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', TEST],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True, encoding='utf-8',
        errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def composed(doc):
    return [e for e in doc['Encounters']
            if any('Candidates' in enemy for enemy in e['Enemies'])]


def main():
    original = io.open(CONTENT, encoding='utf-8').read()
    failures = 0

    # ① 候选削成只有 Id —— 造出一只有血、有类型、但没招式的怪
    doc = json.loads(original)
    for encounter in composed(doc):
        for enemy in encounter['Enemies']:
            enemy['Candidates'] = [
                {'Id': c['Id'], 'Weight': c['Weight']} for c in enemy['Candidates']
            ]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    ok = build()
    passed, text = run_test() if ok else (True, 'build failed')
    red = ok and (not passed)
    print('%-20s -> %s  (candidates carry only Id)' % (
        'candidate shape', 'RED as expected' if red else 'STILL GREEN'))
    if not red:
        failures += 1
        print(text[-700:])
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)

    # ② 权重全压在第一只候选上
    doc = json.loads(original)
    for encounter in composed(doc):
        for enemy in encounter['Enemies']:
            for index, candidate in enumerate(enemy['Candidates']):
                candidate['Weight'] = 1000 if index == 0 else 0
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    ok = build()
    passed, text = run_test() if ok else (True, 'build failed')
    red = ok and (not passed)
    print('%-20s -> %s  (first candidate always wins)' % (
        'no randomness', 'RED as expected' if red else 'STILL GREEN'))
    if not red:
        failures += 1
        print(text[-700:])

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
    assert build(), 'restore must rebuild'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
