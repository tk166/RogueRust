"""合并参考包之后的布局收尾：手牌压操作栏、竖屏敌人标签互相压、提示气泡压 HUD。

## 三处都是**量出来的**，不是看截图猜的

`native/_dbg_layout.mjs` 打出的真实数字：

| 视口 | 中间那张牌的底边 | 视口高 | 结论 |
|---|---|---|---|
| 390×844 | 804 | 844 | 没出屏，但**压在底部操作栏**（790–830）下面 |
| 1280×800 | 817 | 800 | 真的超出 17px |

我原来的"装得下"是按 z=0 平面算的，而手牌在 z≈0.9（离相机更近）⇒ 透视下更大更低。
这就是"公式对、几何错"的典型：**投影不是线性的，别用另一个平面的比例去推**。

## 修法

1. 扇形 `y` 系数 0.72 → 0.67（两种视口各留约 20px 余量）；
2. 竖屏敌人间距上限 1.0 → 1.35 世界单位（两个敌人时标签会压在一起）；
3. 窄屏把提示气泡挪到 HUD 下方（原来 top:14px 正好盖住 BLK/EN）。
"""

import io

STAGE = 'web-next/src/stage/Stage.tsx'
FORMATION = 'web-next/src/stage/formation.ts'
CSS = 'web-next/src/styles.css'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


edit(
    STAGE,
    '''    y: -halfH * 0.72 + Math.abs(t) * halfH * 0.05,''',
    '''    // ⚠️ 0.72 会让中间那张牌的底边压到底部操作栏下面（390×844 实测卡底 804、操作栏 790 起）。
    // 手牌在 z≈0.9，比 z=0 平面更靠近相机 ⇒ 透视下更大更低，所以不能按 z=0 的比例推。
    y: -halfH * 0.67 + Math.abs(t) * halfH * 0.05,''',
    'fan y',
)

edit(
    FORMATION,
    '''    const gap = n < 2 ? 0 : Math.min(1.0, (top - bottom) / (n - 1));''',
    '''    // ⚠️ 上限 1.0 时两个敌人只隔约 114px（390 宽），而"名字+HP+意图"三行标签约 60px 高，
    // 会压到上面那个敌人身上。1.35 让 n=2 时也留得下标签；n 大时仍由区域高度约束。
    const gap = n < 2 ? 0 : Math.min(1.35, (top - bottom) / (n - 1));''',
    'portrait gap',
)

edit(
    CSS,
    '''@media (max-width: 600px) {
  .gesture-hint { font-size: 11px; padding: 5px 10px; }
}''',
    '''@media (max-width: 600px) {
  /* ⚠️ 窄屏的 HUD 是两行（HP/BLK/EN 会换行），高约 96px。气泡留在 top:14px 会正好盖住
     BLK 与 EN —— 截图上就是这么糊在一起的。宽屏 HUD 只有一行且靠左，气泡居中，不冲突。 */
  .gesture-hint { font-size: 11px; padding: 5px 10px; top: calc(env(safe-area-inset-top, 0px) + 100px); }
}''',
    'hint top',
)
print('layout fixes applied')
