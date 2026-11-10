"""§347 负控（第二版）：三条，精准打**顺序**与**互斥**，不打别的。

第一版的两条不合格，原因值得记下来：

* **① 兜底插在 SC-02b 前面**时，我把 `splice` 插在了 `RAW.length - 2` —— 那是 SC-02b 的位置，
  但同时让**兜底成了无条件命中**，于是它后面的场景全被吞掉（不止 SC-02b）。红是红了，
  但红在**别的**断言上（"panel fight 没有 begin_fight"）⇒ 不是这条负控该证明的事。
* **③ SC-03 去掉 `!inFight`** 根本红不了 —— 因为**互斥包装层**已经保证"SC-03b 命中时 SC-03
  不再命中"。这说明 `!inFight` 现在是**冗余的守卫**（留着是文档价值，不是判据价值）。
  换成"把 SC-03b 与 SC-03 换个位置" —— 那才是顺序本身。

三条现在的分工：

1. **把 SC-02（兜底）与 SC-02b 换位**（`ui-state-model.md` 旧表的那个错）⇒ SC-02b 的夹具红。
2. **去掉互斥包装层** ⇒ 手写条件之间的包含关系暴露（`cleared` 同时命中三个）。
3. **SC-03b 与 SC-03 换位**（"战斗中"排到"预备战斗"后面）⇒ SC-03b 的夹具红。
"""

import io
import subprocess
import sys

PANELS = 'web/ui_panels.js'


def run_ui():
    p = subprocess.run(['C:\\Program Files\\nodejs\\node.exe', 'web/ui_test.mjs'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode, p.stdout + p.stderr


def case(label, pairs, needle):
    raw = io.open(PANELS, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:70], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(PANELS, 'w', encoding='utf-8', newline='\n').write(broken)
        code, out = run_ui()
        ok = code != 0 and needle in out
        print('  %-54s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'FAIL' in line:
                    print('      ', line.strip()[:140])
                    break
    finally:
        io.open(PANELS, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

# ① 兜底与 SC-02b 换位（旧文档表的错：兜底排在幕尽头前面）
ok &= case(
    '① SC-02（兜底）与 SC-02b 换位',
    [('''    { id: "SC-02b", overlay: false, test: (s) => s.pending === 0 && !s.inFight && mapExhausted(s) },
    // 18 地图（兜底）：无条件 —— "前面一条都没命中"由包装层保证。
    { id: "SC-02", overlay: false, test: () => true },''',
      '''    // 18 地图（兜底）：无条件 —— "前面一条都没命中"由包装层保证。
    { id: "SC-02", overlay: false, test: () => true },
    { id: "SC-02b", overlay: false, test: (s) => s.pending === 0 && !s.inFight && mapExhausted(s) },''')],
    # 换位被**顺序字面量**当场抓住（比夹具更早）—— 这正是"顺序即语义"的意思。
    'SCENES order drifted',
)

# ② 去掉互斥包装层
ok &= case(
    '② 去掉互斥包装层（SCENES = RAW）',
    [('''  const SCENES = RAW.map((entry, index) => {''',
      '''  const SCENES = RAW;
  const _UNUSED = RAW.map((entry, index) => {''')],
    'base scenes must be unique',
)

# ③ 顺序：SC-03b 排到 SC-03 后面
ok &= case(
    '③ SC-03b 与 SC-03 换位（战斗后排到预备战斗后）',
    [('''    { id: "SC-03b", overlay: false, test: (s) => !!s.inFight },''',
      '''    { id: "SC-03b-x", overlay: false, test: () => false },'''),
     ('''    { id: "SC-03", overlay: false, test: (s) => s.pending === 0 && !s.inFight && preFight(s) },''',
      '''    { id: "SC-03", overlay: false, test: (s) => s.pending === 0 && !s.inFight && preFight(s) },
    { id: "SC-03b", overlay: false, test: (s) => !!s.inFight },''')],
    'SCENES order drifted',
)

# ④ **语义碰撞**：把 SC-04 的条件放宽到 pending 5（事件）—— 顺序没变，所以顺序字面量看不见。
#
#    ⚠️ 它红在**面板测试**上（`panel "event"`），不是场景夹具上 —— 因为 `describe()` 现在就是
#    按分类器分派的（§347 的目的）。两层判据在这里**故意重叠**：面板测试问"这一屏画对了没"，
#    场景夹具问"这个快照属于哪个场景"。碰撞会先撞上面板测试。
ok &= case(
    '④ SC-04 的条件放宽到 pending 5（语义碰撞）',
    [('''    { id: "SC-04", overlay: false, test: (s) => s.pending === 4 },''',
      '''    { id: "SC-04", overlay: false, test: (s) => s.pending === 4 || s.pending === 5 },''')],
    'panel "event"',
)

code, _ = run_ui()
print('  还原后 ui_test：%s' % ('green' if code == 0 else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
