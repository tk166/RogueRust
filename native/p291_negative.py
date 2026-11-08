"""§291 负控：金币门槛被忽略 / 门槛被无条件满足 / G1 判据失效。"""
import io
import json
import shutil
import subprocess
import sys

CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'
GATE = 'D:/Vibe/sts-tui/native/sts_content_check.py'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
BUILD = 'D:/Vibe/sts-tui/tools/contentc/build.py'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'


def rust(test):
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-core', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def build():
    out = subprocess.run([sys.executable, '-X', 'utf8', BUILD, '--package', 'sts'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return 'CONTENTC_BUILD OK' in (out.stdout + out.stderr)


def main():
    failures = 0
    # 开始时拷一份**原样**内容：恢复时"重打补丁"等于第二份合同（这一轮真踩了）。
    pristine = CONTENT + ".pristine"
    shutil.copyfile(CONTENT, pristine)

    # ① `MinGold` 被忽略 ⇒ 50 金币时也会出现（判据红）
    original = io.open(CORE, encoding='utf-8').read()
    old = '''                || gold < min_gold'''
    assert original.count(old) == 1
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(original.replace(old, '                || false'))
    passed, text = rust('the_unknown_room_events_are_readable')
    print('%-40s -> %s' % ('MinGold ignored', 'RED as expected' if not passed else 'STILL GREEN'))
    if passed:
        failures += 1
        print(text[-300:])
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(original)

    # ② 押注项的 `Requires` 被删掉 ⇒ 内容门 G1 必须红
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    for node in doc['EventNodes']:
        if node['Id'] == 'the_joust.offer':
            for option in node['Options']:
                option.pop('Requires', None)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    assert build(), 'the broken content must still build'
    out = subprocess.run([sys.executable, '-X', 'utf8',
                          'D:/Vibe/sts-tui/native/sts_content_check.py'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    hit = out.returncode != 0 and 'the button would be drawn and then refused' in text
    print('%-40s -> %s' % ('Requires removed (gate G1)',
                           'RED as expected' if hit else 'STILL GREEN'))
    if not hit:
        failures += 1
        print(text[-300:])

    # ③ G1 关掉 ⇒ ② 那份坏内容就绿了（证明 ② 是 G1 抓的，不是别的东西）
    g = io.open(GATE, encoding='utf-8').read()
    marker = '''                    if not covered:'''
    assert g.count(marker) == 1
    io.open(GATE, 'w', encoding='utf-8', newline='\n').write(
        g.replace(marker, '''                    if False and not covered:'''))
    out = subprocess.run([sys.executable, '-X', 'utf8',
                          'D:/Vibe/sts-tui/native/sts_content_check.py'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    still = out.returncode == 0
    print('%-40s -> %s' % ('G1 disabled on the same content',
                           'GREEN as expected (G1 is the only detector)' if still
                           else 'STILL RED (something else caught it)'))
    if not still:
        failures += 1
        print(text[-300:])
    io.open(GATE, 'w', encoding='utf-8', newline='\n').write(g)

    shutil.copyfile(pristine, CONTENT)
    import os
    os.remove(pristine)
    assert build(), 'restore must rebuild'
    passed, _ = rust('the_unknown_room_events_are_readable')
    assert passed, 'restore must make the core test green again'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


def doc_from_disk_original():
    # `git` 里那份是权威：从工作树重新读会拿到我刚写的坏内容，所以用 `git show`。
    out = subprocess.run([r'C:\Program Files\Git\cmd\git.exe', 'show',
                          'HEAD:tools/contentc/packages/sts/sts.roguedeck.json'],
                         cwd='D:/Vibe/sts-tui', capture_output=True, text=True,
                         encoding='utf-8', errors='replace')
    return json.loads(out.stdout)


main()
