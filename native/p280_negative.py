"""§280 负控：条件变体/千分/付钱，四条判据各自必须真的会红。

前三条走内容门（改 JSON → 重编 → 跑门），第四条走内核（把 `RequiresAsc` 删掉 ⇒
A15 上那个按钮变成"永远可选"，而 `the_a15_requirement_variant_gates_the_cleric_price`
必须红）。
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
        [CARGO, 'test', '-p', 'rd-wasm', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', name],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    original = io.open(CONTENT, encoding='utf-8').read()
    failures = 0

    def cleric(doc):
        node = [n for n in doc['EventNodes'] if n['Id'] == 'the_cleric'][0]
        return node['Options'][1]        # Purify：50 / A15 75

    def moai(doc):
        node = [n for n in doc['EventNodes'] if n['Id'] == 'the_moai_head'][0]
        return node['Options'][0]        # Jump Inside：12.5% / A15 18%

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
                if 'FAIL' in line or 'RequiresAsc' in line or 'gold_cost' in line:
                    print('   saw: ' + line[:150])

    def asc_equals_base(doc):
        # 条件变体与基础**一模一样** ⇒ 那一档什么都没变（与 `EffectsAsc` 同一条规矩）。
        option = cleric(doc)
        option['RequiresAsc'] = list(option['Requires'])

    def bad_percent(doc):
        moai(doc)['Effects'][1]['Effect'] = 'max_hp_pct:12.55'

    def bad_cost(doc):
        cleric(doc)['Effects'][0]['Effect'] = 'gold_cost:0'

    run_gate('RequiresAsc == base', asc_equals_base, 'the A15 list equals the base')
    run_gate('two-decimal percent', bad_percent, '不是 1..=100 的百分数')
    run_gate('gold_cost:0', bad_cost, '必须是正整数金币')

    # ── 内核：删掉 `RequiresAsc` ⇒ A15 的 60 金币局里 Purify 会变成"可选"（错误）。
    doc = json.loads(original)
    cleric(doc).pop('RequiresAsc')
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    if not build():
        print('%-24s -> BUILD FAILED' % 'no A15 requirement')
        failures += 1
    else:
        passed, text = rust('the_a15_requirement_variant_gates_the_cleric_price')
        print('%-24s -> %s' % ('no A15 requirement',
                               'RED as expected' if not passed else 'STILL GREEN'))
        if passed:
            failures += 1
            print(text[-500:])

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
    assert build(), 'restore must rebuild'
    code, text = check()
    assert code == 0 and 'STS_CONTENT PASS' in text, 'restore must pass the gate'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
