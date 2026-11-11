"""P1 收尾的文档更新：README（闸门数、新目录、新文档）+ port-plan §351。

只改必须改的几处，不重写别人的段落。
"""

import io

README = 'README.md'
PLAN = 'docs/port-plan.md'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


edit(
    README,
    '''| `tools/acceptance.ps1` | **聚合验收**：24 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state` 与 `ui-abi`），一道红就整体红 |''',
    '''| `tools/acceptance.ps1` | **聚合验收**：25 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi` 与 `ui-next`），一道红就整体红 |''',
    'readme gate count',
)

edit(
    README,
    '''**`ui-state-model.md`**（**场景 × 层 × 字段 × 接口**''',
    '''**`ui-next-p1.md`**（**P1 的 R3F PoC 实测**：中文可读性三档与不变量、字形图集体积（156 字形 / 微软雅黑 64 KB woff2 / DOM 覆盖层 0 字节）、1.85 MB→692 KB gzip 的体积账、闸门 25 抓到的五处"看起来对"与三处假绿；闸门 25 由 `native/ui_next_check.mjs` 守，`web-next/dist/` 入库所以不需要 npm）、**`ui-state-model.md`**（**场景 × 层 × 字段 × 接口**''',
    'readme ui-next doc',
)

# port-plan：§351
t = io.open(PLAN, encoding='utf-8').read()
anchor = '数字不变：闸门 **24**、units **1233**、导出 234。'
assert t.count(anchor) == 1, 'port-plan 锚点命中 %d 次' % t.count(anchor)
addition = anchor + '''

---

## §351 P1：R3F 技术 PoC（`web-next/`，**不动 Rust**）

新建 `web-next/`（Vite + TS + React 19 + R3F 9 + three 0.187 + uikit 1.0.78），Mock 局面
（10 张手牌 / 2 个敌人 / 英雄），把"选中 → 指向 → 释放 / 回弹 / 触摸"整条链在**真浏览器**里
跑通。闸门 **25 `ui-next`**（`native/ui_next_check.mjs`，CDP 派发真鼠标与真触摸事件，
判据读 `window.__p1` 探针）。**这一节一行 Rust 都没改。**

### 三条结论

1. **3D 这条路可以走**，但中文可读性**不是**靠"把牌做大"解决的：390×844 上 10 张牌的
   stride 只有约 33px，物理上放不下 10 个中文标题。方案是**三维牌身 + DOM 文字覆盖层 +
   三档可读性**（手牌只显示费用 / 选中 15+12px / 详情 20+14px）。
2. **字形图集代价量出来了**：玩家词汇 156 字形 ⇒ 微软雅黑子集 **64 KB woff2**、
   黑体 **20 KB woff2**（完整字体 19.7 MB / 9.7 MB）。DOM 覆盖层增量 **0 字节**。
   uikit 默认字体 Inter 有 423 KB 且**零中文字形** ⇒ HUD 只放数字与拉丁字母。
3. **体积 1 854 870 B / 691 923 B gzip**，其中 **284 KB gzip 只是为了 HUD 的 HP/EN/TURN
   付的 Inter** —— P2 最容易砍的一块。

### 闸门 25 抓到的五处（都是"看起来对、实际错"）

| 症状 | 根因 | 修法 |
|---|---|---|
| 按第 3 张却打出第 2 张 / 被拖起的牌挡住敌人 | **视觉网格自己接收射线**，回弹动画途中的牌挡路 | 视觉 `raycast=null`，每个槽位一块**静止**的不可见命中面 |
| 390px 宽下 4 张牌出界 | `handSpread` 是 `useMemo([layout.width])`，而 `layout.width` 原地变异 ⇒ memo 永不重算 | 扇形宽度每帧从 `size` 算 |
| 中间那张牌看不见也点不到 | 扇形 z 写成 `0.9 + \\|t\\| * 0.12`（对称），中间牌 z 最小被完全盖住 | 叠放顺序**单调**（右压左），布局暴露 `hitX` |
| 牌只剩一条边线 / 下半截消失 | 牌色暗过背景；**地台水平面延伸到相机前**，挡住牌的下半截 | 提亮 + `depthTest=false` + `renderOrder`（手牌是 UI） |

**三处闸门自己的假绿**（比代码 bug 更值得记）：只看"提交数变没变"（没抓住牌与被拒绝分不开）、
只查"卡牌中心在视口内"（牌身被裁掉也通过）、"选中态"先释放再截图（牌早回位）。
现在分别用"断言 `phase/handSlot`"、"断言**露出的宽度**与不变量"、`mouseHold` 按住不放修掉。

### 一条与旧页面的有意分歧

旧 `actionFor()` 在 `list.length === 1` 时"拖到哪儿都算它"，把"无目标牌"与"定向牌但只剩一个
敌人"合并了。P1 改成**有目标的牌必须落在合法目标上**（空白一律回弹，不看场上剩几个敌人）。
这是**输入层**语义，不动内核；闸门里有一条专门守它。

### 数字

闸门 24 → **25**；`rd-core 819 / rd-run 225 / rd-wasm 189`、units **1233**（本节不动 Rust）；
导出 234；四条对拍不动。`web-next/dist/` 入库（1.8 MB），所以闸门 25 不需要 npm 与网络。

### 残留

- 真机性能没测（headless 软件光栅的 60 fps 什么都不能说明）；
- uikit 里没有中文（要显示中文就得付字体账，或继续用 DOM 覆盖层）；
- 敌人槽位稳定性、同名卡、X 费、0 费牌这些 Mock→WASM 的坑留给 P2。'''
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))
print('README + port-plan §351 updated')
