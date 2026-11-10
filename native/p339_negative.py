"""§339 负控：五条，每条都必须让**指定的**判据红。

Rust 侧（`rd-core::content::tests::event_level_requirements_filter_the_pool_before_the_roll`）：

1. `RequiresAny` 恒成立（把 OR 组短路）⇒ "满血 + 无 Idol"那一格红 —— 证明 OR 组**真的在求值**，
   不是"因为 AND 组空所以放行"。
2. 跳过 AND 组 ⇒ tomb 的 `Offer all Gold`（`gold` + `relic lacks`）红 —— 证明 AND 组也真的在求值。

内容侧（`native/sts_content_check.py`）：

3. 把 `RequiresAny` 里的 `health_percent` 改成词表外的 `health_pct` ⇒ 内容门必须红在
   `the_moai_head.RequiresAny[0]` —— 证明**事件级**条件现在真的被检查（§339 之前没人查）。
4. 把 `RequiresAny` 改成空列表 ⇒ 必须红在 "non-empty list"。
5. 把 `relic_count` 从 python 的词表里删掉 ⇒ 必须红在 "词表外的条件" —— 这条钉住**两处词表同步**
   （§331 只加进了 Rust，漂了没人发现）。

⚠️ 两个坑，都是"负控没装到切口上"：

* **内容侧负控必须先重编镜像**。内容门在"源文档比镜像新"时直接 `exit 2`（前提缺失），
  于是它**根本走不到**那条检查 —— 第一版三条内容负控全是 `NOT CAUGHT`，而原因与条件无关。
* 每条都断言**具体的失败文本**，不是"退出了非零"：编译错也会让退出码非零。
"""

import io
import json
import subprocess
import sys

STATE = 'kernel/rd-core/src/run_expr.rs'
CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
GATE = 'native/sts_content_check.py'
TEST = 'event_level_requirements_filter_the_pool_before_the_roll'


def run_core(test_name):
    p = subprocess.run(['cargo', 'test', '-p', 'rd-core', '--release', test_name],
                       cwd='kernel', capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def build_image():
    p = subprocess.run([sys.executable, '-X', 'utf8', 'build.py', '--package', 'sts'],
                       cwd='tools/contentc', capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    out = p.stdout + p.stderr
    assert 'CONTENTC_BUILD OK' in out, out[-400:]


def run_gate():
    p = subprocess.run([sys.executable, '-X', 'utf8', GATE],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode, p.stdout + p.stderr


def case_rust(label, pairs, needle):
    raw = io.open(STATE, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(STATE, 'w', encoding='utf-8', newline='\n').write(broken)
        out = run_core(TEST)
        ok = needle in out
        print('  %-52s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'panicked' in line or 'error[' in line:
                    print('      ', line.strip()[:130])
                    break
    finally:
        io.open(STATE, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


def case_content(label, mutate, needle, gate_patch=None):
    raw = io.open(CONTENT, encoding='utf-8').read()
    gate_raw = io.open(GATE, encoding='utf-8').read()
    doc = json.loads(raw)
    mutate(doc)
    ok = False
    try:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
        if gate_patch:
            old, new = gate_patch
            assert gate_raw.count(old) == 1, '%s: gate 补丁命中 %d' % (label, gate_raw.count(old))
            io.open(GATE, 'w', encoding='utf-8', newline='\n').write(gate_raw.replace(old, new))
        # ★ 必须重编：否则内容门 exit 2（源比镜像新），走不到那条检查。
        build_image()
        code, out = run_gate()
        ok = code != 0 and needle in out
        print('  %-52s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            print('      exit=%d, 找 %r' % (code, needle))
            for line in out.splitlines():
                if 'FAIL' in line:
                    print('      ', line.strip()[:130])
                    break
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
        io.open(GATE, 'w', encoding='utf-8', newline='\n').write(gate_raw)
        build_image()
    return ok


def moai_entry(doc):
    for entry in doc['EventTables']['Events3']:
        if entry.get('Id') == 'the_moai_head':
            return entry
    raise AssertionError('moai')


ok = True

# ① OR 组恒成立
ok &= case_rust(
    '① RequiresAny 恒成立（OR 短路）',
    [('''    for term in any.iter().take(any_count) {
        let atom = NodeRef::new(content, *term);
        if atom_holds(content, atom, facts)? {
            return Ok(true);
        }
    }
    Ok(false)''',
      '''    let _ = (&any, any_count);
    Ok(true)''')],
    'full HP and no Idol',
)

# ② 跳过 AND 组
ok &= case_rust(
    '② 跳过 AND 组（Requires 不求值）',
    [('''    for term in terms.iter().take(count) {
        let atom = NodeRef::new(content, *term);
        if !atom_holds(content, atom, facts)? {
            return Ok(false);
        }
    }''',
      '''    let _ = (&terms, count);''')],
    'holding the mask: the offer is locked',
)

# ③ 事件级词表外 kind
def bad_kind(doc):
    moai_entry(doc)['RequiresAny'][0]['Kind'] = 'health_pct'


ok &= case_content('③ 事件级条件里的词表外 Kind', bad_kind, 'the_moai_head.RequiresAny[0]')

# ④ 空 OR 组
def empty_any(doc):
    moai_entry(doc)['RequiresAny'] = []


ok &= case_content('④ 空的 RequiresAny', empty_any, 'non-empty list')

# ⑤ 两处词表漂移
def keep_nloth(doc):
    found = [e for e in doc['EventTables']['Events2'] if e.get('Id') == 'nloth']
    assert found and found[0].get('Requires'), 'nloth 的 relic_count 条件不见了'


RELIC_COUNT_ENTRY = '''                  # §331：`relic_count` —— 身上有几件遗物（`N'loth` 的"至少 2 件才出现"）。
                  # ⚠️ 这一条是 §339 补的：§331 只把它加进了 `rd-core::run_expr` 的 `KINDS`，
                  # 这份手抄表漏了。当时没红，是因为这份表只查**选项级** `Requires`，
                  # 而 `relic_count` 只出现在**事件级** —— 见下面第 ② 条。
                  "relic_count")'''

ok &= case_content(
    '⑤ 词表漏了 relic_count（两处漂移）',
    keep_nloth,
    '词表外的条件',
    gate_patch=(RELIC_COUNT_ENTRY, '                  "floor")'),
)

out = run_core(TEST)
print('  还原后 rd-core：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
code, _ = run_gate()
print('  还原后内容门：%s' % ('green' if code == 0 else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
