"""§278 负控：内容门对"事件树"的四条新判据必须真的会红。

每一条都是"没有症状"的错误 —— 镜像装得下、内核读得出、页面也画得出，只有玩家走不到/看不到：

1. **孤儿段**：`EventNodes` 里多一段谁都不指到它 ⇒ 一段看不见的剧情；
2. **坏 `Next`**：点下去事件该去的那段不存在 ⇒ 点下去没有反应（或落回第一段）；
3. **坏百分比**：`damage_pct:0` ⇒ 屏幕上写着"按上限 0% 受伤"而什么都没发生；
4. **入口段不存在**：`EV.Entry` 指向一个不在表里的 id ⇒ 房间只有标题、没有正文、没有按钮。

做法：改 JSON（结构化，不碰文本）→ 跑内容门 → 断言它**红**在这条判据上 → 还原。
⚠️ 判据是"红在这一处"，不是"红了几条"：一个坏改动若只是把断言打到别处，
它证明的不是这一条判据还活着。
"""
import io
import json
import subprocess
import sys

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'
BUILD = 'D:/Vibe/sts-tui/tools/contentc/build.py'


def build():
    """改完源文档**必须重编**：内容门第一件事就是拒绝一份比源文档旧的镜像
    （于是"守卫装在切口下游"的坑在这里被工具自己堵住了）。"""
    out = subprocess.run([sys.executable, '-X', 'utf8', BUILD, '--package', 'sts'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return 'CONTENTC_BUILD OK' in (out.stdout + out.stderr)


def check():
    out = subprocess.run([sys.executable, '-X', 'utf8', CHECK],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return out.returncode, out.stdout + out.stderr


def main():
    original = io.open(CONTENT, encoding='utf-8').read()
    failures = 0

    def run(name, mutate, expect):
        nonlocal failures
        doc = json.loads(original)
        mutate(doc)
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
        if not build():
            print('%-22s -> BUILD FAILED' % name)
            failures += 1
            return
        code, text = check()
        hit = expect in text and code != 0
        print('%-22s -> %s (exit %d)' % (name, 'RED as expected' if hit else 'STILL GREEN', code))
        if not hit:
            for line in text.split('\n'):
                if 'FAIL' in line or line.strip().startswith('EventNodes'):
                    print('   saw: ' + line[:150])
        if not hit:
            failures += 1
            print('   wanted %r in the failure list; tail:\n%s' % (expect, text[-500:]))

    def orphan(doc):
        doc['EventNodes'].append({
            'Id': 'golden_idol.orphan',
            'TextKey': 'A scene nobody can reach.',
            'Options': [
                {'Label': 'A', 'Effects': [{'Effect': 'nothing', 'Amount': 0}], 'Next': ''},
                {'Label': 'B', 'Effects': [{'Effect': 'nothing', 'Amount': 0}], 'Next': ''},
            ],
        })

    def bad_next(doc):
        for node in doc['EventNodes']:
            if node['Id'] == 'golden_idol':
                node['Options'][0]['Next'] = 'golden_idol.nowhere'

    def bad_percent(doc):
        for node in doc['EventNodes']:
            if node['Id'] == 'golden_idol.boulder':
                node['Options'][1]['Effects'][0]['Effect'] = 'damage_pct:0'

    def bad_entry(doc):
        for room in doc['UnknownRooms']:
            if room['Id'] == 'golden_idol':
                room['Entry'] = 'golden_idol.missing'

    run('orphan step', orphan, 'unreachable step(s): golden_idol.orphan')
    run('Next names nothing', bad_next, 'names \'golden_idol.nowhere\', which is not in EventNodes')
    run('percentage 0', bad_percent, '百分比 0 不在 1..=100')
    run('entry names nothing', bad_entry, 'which is not in EventNodes')

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
    code, text = check()
    assert code == 0 and 'STS_CONTENT PASS' in text, 'restore must pass'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
