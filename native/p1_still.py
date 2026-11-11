"""`?still`：冻结动画，让证据截图**确定性**。

## 问题

闸门每次跑都会重写 `docs/ui-next-p1/*.png`，因为英雄呼吸、卡牌回弹都用 `clock.getElapsedTime()`
—— 同一段代码跑两次像素不同 ⇒ 提交后工作区又变脏（`git status` 里三个 PNG 永远是 M）。

## 修法

查询串里有 `still` 时：呼吸时间固定为 0、卡牌直接吸附到目标位（`k = 1`）。
闸门用 `?debug&still`，于是同一份代码跑两次的截图**逐字节相同**，工作区保持干净。
副作用是好的：截图里不再有"恰好拍到动画中间态"的运气成分。

⚠️ `still` 只冻结**视觉插值**，不冻结状态机：拖拽/目标高亮/模态隔离的断言照样走真事件。
"""

import io

STAGE = 'web-next/src/stage/Stage.tsx'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


edit(
    STAGE,
    '''  const { camera, size, pointer } = useThree();''',
    '''  const { camera, size, pointer } = useThree();
  // `?still`：冻结呼吸与插值，让证据截图逐字节可复现（见文件头）。
  const still = typeof window !== "undefined" && window.location.search.includes("still");''',
    'still flag',
)

edit(
    STAGE,
    '''  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();''',
    '''  useFrame(({ clock }) => {
    const t = still ? 0 : clock.getElapsedTime();''',
    'still time',
)

edit(
    STAGE,
    '''      // 指数趋近：既跟随又不会抖动。抬起的牌跟得快，回落跟得慢一点（回弹手感）。
      const k = lifted ? 0.45 : 0.3;''',
    '''      // 指数趋近：既跟随又不会抖动。抬起的牌跟得快，回落跟得慢一点（回弹手感）。
      // `still` 下直接吸附（k = 1）：截图不该拍到"恰好走到一半"的位置。
      const k = still ? 1 : lifted ? 0.45 : 0.3;''',
    'still lerp',
)

edit(
    'native/ui_next_check.mjs',
    '''  query: "debug",''',
    '''  query: "debug&still",''',
    'gate query',
)
print('?still added')
