"""负控 2：把 hover 的命中半径换成"真 mesh 半径"，模拟旧的"两套几何"。

`enemyAtScreen(enemies, x, y, allowed, extraTouchRadius = 14)` 的最后一个参数就是接受半径的
额外余量。传 `-14` ⇒ 阈值变成 `max(24, r - 14)`，也就是**只有真的压在 mesh 轮廓内**才算命中 ——
正是旧实现里 R3F 射线的几何。此时"轮廓外、触摸半径内"那个点会让 hover 与合法目标分叉，
断言必须红。

用法：`python native/p1_negctl_hover.py apply|restore`
"""

import io
import sys

PATH = 'web-next/src/App.tsx'
GOOD = 'const underPointer = (x: number, y: number) => enemyAtScreen(layout.enemies, x, y, allEnemySlots());'
BAD = 'const underPointer = (x: number, y: number) =>\n      enemyAtScreen(layout.enemies, x, y, allEnemySlots(), -14);'

mode = sys.argv[1] if len(sys.argv) > 1 else 'apply'
t = io.open(PATH, encoding='utf-8').read()
if mode == 'apply':
    assert t.count(GOOD) == 1, '找不到正常版本（%d）' % t.count(GOOD)
    t = t.replace(GOOD, BAD)
    print('负控已装：hover 用 mesh 半径')
else:
    assert t.count(BAD) == 1, '找不到负控版本（%d）' % t.count(BAD)
    t = t.replace(BAD, GOOD)
    print('已恢复：hover 用触摸半径')
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
