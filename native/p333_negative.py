"""§333 负控：这条机制的两个半边各弄坏一次。

1. **过期时刻**：把 `host.expire_one_shot_turn_start(...)` 从抽牌之后删掉
   ⇒ 状态不会消失，第二次回合还会加成（红在"状态真的消失"或"回到基础值"）。
2. **只下一回合**：把 `draw_card_next_turn` 的 `one_shot_turn_start` 标签删掉
   ⇒ 变成"每回合 +3 抽"，红在"回到基础值"。

第 2 条是这条机制的核心：只测"生效一次"的话，"每回合都 +X"照样绿。
"""

import io
import json
import subprocess
import sys

TURN = 'kernel/rd-core/src/turn.rs'
CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'


def build_content():
    subprocess.run(['python', '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')


def run():
    p = subprocess.run(
        ['cargo', 'test', '-p', 'rd-core', '--release', '--', '--test-threads=1',
         'the_one_shot_turn_start'],
        cwd='kernel', capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


ok = True

# ── ① 删掉过期调用 ───────────────────────────────────────────────────────────
raw = io.open(TURN, encoding='utf-8').read()
needle = """    host.expire_one_shot_turn_start(state, &actor);
    if stopped(state) {
        return Ok(());
    }
"""
assert raw.count(needle) == 1, 'expire call'
try:
    io.open(TURN, 'w', encoding='utf-8', newline='\n').write(raw.replace(needle, '', 1))
    out = run()
    hit = 'is spent' in out or 'back to the plain refill' in out
    print('  ① 删掉"抽牌后过期" -> %s' % ('RED' if hit else 'NOT CAUGHT'))
    ok &= hit
finally:
    io.open(TURN, 'w', encoding='utf-8', newline='\n').write(raw)

# ── ② 去掉 one_shot 标签（变成每回合）───────────────────────────────────────
raw = io.open(CONTENT, encoding='utf-8').read()
doc = json.loads(raw)
target = [s for s in doc['Statuses'] if s['Id'] == 'standard.draw_card_next_turn'][0]
assert 'one_shot_turn_start' in target['Tags']
try:
    target['Tags'] = [tag for tag in target['Tags'] if tag != 'one_shot_turn_start']
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    build_content()
    out = run()
    hit = 'is spent' in out or 'back to the plain refill' in out or 'and the plain five cards' in out
    print('  ② 去掉 one_shot 标签（变成每回合） -> %s' % ('RED' if hit else 'NOT CAUGHT'))
    ok &= hit
finally:
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
    build_content()

out = run()
print('  还原后：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
