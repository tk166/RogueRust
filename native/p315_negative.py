"""§315 负控：证明"档位按怪物自己钉"和"A7/A8 真的分得开"。

1. **清单侧**：把 `INV_ASC_HP_LEVEL` 里的 sentry 三条删掉（回到"档位按池子推"），
   `sts_content_check.py` 必须红 —— 那正是 §311 记录的那条"两条不可能同时成立"。
2. **内容侧**：把 Act 2 那条记录改成 `{A7, 39}`（错档位），
   `the_sentry_keeps_one_hp_table_across_two_tiers` 必须红（A7 时血量会变成 39）。
"""
import io
import json
import subprocess
import sys

CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
BUILD = 'D:/Vibe/sts-tui/tools/contentc/build.py'
CARGO = 'C:/Users/TK11/.cargo/bin/cargo.exe'
MANIFEST = 'D:/Vibe/sts-tui/kernel/Cargo.toml'


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors='replace')


def main():
    bad = 0

    # ── 1. 清单侧：Sentry 的档位回到"按池子推" ──────────────────────────────────────────────
    original = io.open(CHECK, encoding='utf-8').read()
    try:
        stripped = original.replace('''INV_ASC_HP_LEVEL = {
    'sentry_1': 8,
    'sentry_2': 8,
    'sentry_3': 8,
}''', 'INV_ASC_HP_LEVEL = {}')
        assert stripped != original
        io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(stripped)
        out = run(['python', '-X', 'utf8', 'native/sts_content_check.py'])
        blob = (out.stdout or '') + (out.stderr or '')
        red = 'STS_CONTENT FAIL' in blob
        print('%-26s -> %s' % ('Sentry 档位按池子推', 'RED (good)' if red else 'STILL GREEN (bad!)'))
        if not red:
            bad += 1
    finally:
        io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(original)

    # ── 2. 内容侧：Act 2 的 Sentry 改成错档位 ───────────────────────────────────────────────
    original_content = io.open(CONTENT, encoding='utf-8').read()
    try:
        doc = json.loads(original_content)
        encounter = next(e for e in doc['Encounters']
                         if e['Id']['Value'] == 'enc_sentry_and_spheric')
        encounter['Enemies'][0]['MaxHealthAsc'] = [{'AscensionMin': 7, 'MaxHealth': 39}]
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
        built = run(['python', '-X', 'utf8', BUILD, '--package', 'sts'])
        assert 'CONTENTC_BUILD OK' in (built.stdout or '') + (built.stderr or '')
        out = run([CARGO, 'test', '-p', 'rd-wasm', '--manifest-path', MANIFEST, '--release',
                   '--', '--test-threads=1', 'the_sentry_keeps_one_hp_table'])
        blob = (out.stdout or '') + (out.stderr or '')
        red = 'test result: FAILED' in blob or 'panicked' in blob or 'error[' in blob
        print('%-26s -> %s' % ('Sentry 改成 A7 39', 'RED (good)' if red else 'STILL GREEN (bad!)'))
        if not red:
            bad += 1
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original_content)
        run(['python', '-X', 'utf8', BUILD, '--package', 'sts'])

    print('负控完成：%d/2 按预期变红' % (2 - bad))
    sys.exit(1 if bad else 0)


main()
