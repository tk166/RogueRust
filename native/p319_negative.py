"""§319 负控：三条断言各在一处故意弄坏，看闸门是否**在预期位置**红，然后原样写回。"""

import io
import json
import subprocess
import sys

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
STATE = 'kernel/rd-run/src/state.rs'
EXPR = 'kernel/rd-core/src/run_expr.rs'


def run(argv, cwd=None):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return p.stdout + p.stderr


def check(label, needle, output):
    print('  %-46s %s' % (label, 'RED at the expected place' if needle in output else
                          'NO -- not caught: %r' % needle))
    return needle in output


ok = True

# ── 1. 内容：把 Skill 那条选项的效果改成删 Attack（条件不动）──────────────────────
raw = io.open(CONTENT, encoding='utf-8').read()
doc = json.loads(raw)
falling = next(n for n in doc['EventNodes'] if n['Id'] == 'falling')
falling['Options'][0]['Effects'][0]['Effect'] = 'remove_card_random:attack'
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
# ⚠️ 内容门第一条是“镜像与源码**同代**”（比 mtime）。只改 JSON 不重编 ⇒ 它红在 [0]，
# 于是配对的判据根本没跑 —— 那会把这个负控变成“闸门红了”的假证据。
run([sys.executable, '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'])
out = run([sys.executable, '-X', 'utf8', 'native/sts_content_check.py'])
ok &= check('内容：条件要 skill、效果删 attack', 'must be equal', out) or \
      check('内容：条件要 skill、效果删 attack', '必须逐个相等', out)
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
run([sys.executable, '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'])

# ── 2. 内核：删掉 `kind` 过滤（等于"删第一张"）────────────────────────────────────
raw = io.open(STATE, encoding='utf-8').read()
broken = raw.replace("""                    if facts.kind == kind {
                        eligible[found] = index as u8;""",
                     """                    if facts.kind == kind || true {
                        eligible[found] = index as u8;""")
assert broken != raw
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(broken)
out = run(['cargo', 'test', '-p', 'rd-run', '--release', 'falling'], cwd='kernel')
ok &= check('内核：忽略类型过滤', 'falling_removes_a_card_of_the_named_kind', out)
ok &= check('内核：忽略类型过滤（拒绝那条也该红）',
            'test result: FAILED', out)
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(raw)

# ── 3. 求值器：`card_tag` 恒真 ────────────────────────────────────────────────────
raw = io.open(EXPR, encoding='utf-8').read()
broken = raw.replace('"card_tag" => facts.deck_tags.contains(&id),',
                     '"card_tag" => true,')
assert broken != raw
io.open(EXPR, 'w', encoding='utf-8', newline='\n').write(broken)
out = run(['cargo', 'test', '-p', 'rd-core', '--release', 'every_kind'], cwd='kernel')
ok &= check('求值器：card_tag 恒真', 'test result: FAILED', out)
io.open(EXPR, 'w', encoding='utf-8', newline='\n').write(raw)

print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
