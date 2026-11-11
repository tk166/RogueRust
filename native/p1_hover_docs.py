"""port-plan §354：UX-2 文字锚点 + hover 单源。"""

import io

PATH = 'docs/port-plan.md'
t = io.open(PATH, encoding='utf-8').read()
anchor = '''### 残留（参考包没修、审阅提了的）'''
assert t.count(anchor) == 1, '锚点命中 %d 次' % t.count(anchor)

addition = '''---

## §354 UX-2 文字锚点 + hover 单源（两条"同一个事实两个来源"）

### ① 紧凑态文字锚在**露出来那条**的中心

`TextOverlay` 把文字框放在 `screen.x`（牌心）。但叠放顺序是"右压左"，牌心可能被右邻盖住，
露出的是左边一条，其中心是 `hitX`。当前 33px 宽度下费用数字恰好还没被吃掉 —— **是运气**。

修法：紧凑态用 `hitX`，展开/抬起（整张都露着，此时 `hitX === x`）用牌心。
负控：退回牌心 ⇒ 闸门红，`drift` 实测 **18px**（阈值 2px）。

### ② hover 与合法目标统一到屏幕命中

原来"哪个敌人被指向"有两处：`Stage` 敌人的 `onPointerMove`（**R3F 射线**）写
`hoveredEnemySlot`，`App` 的 `window.pointermove`（**屏幕命中**，半径 `r+14`）写
`state.hoverSlot`。两者几何不同 ⇒ 敌人边缘会出现"绿环亮着但没有 hover 高亮"。

修法：
* `window.pointermove` **常驻**（不再只在按住时跑），一次算出
  `hoveredEnemy`（任意敌人，视觉）与 `state.hoverSlot`（**合法目标**，提交与绿环）——
  这是两个**不同的问题**，但都由**同一个** `enemyAtScreen` 回答（只是允许集合不同）；
* `Stage` 的敌人 `onPointerMove` / `onPointerOut` / `onPointerUp` 与背景板全部拆掉；
  R3F 现在只负责**卡片上的按下**（需要 `pointerId` / `pointerType` / `button`）；
* `hoverRef` 一并删除（落点统一由 `currentTarget` 算，没有第二个读者）。

**牙齿**：断言把指针放在**敌人轮廓外、触摸半径内**（`r + 10`）。中间点测不出来（旧实现在
中心也一致）；边缘点上旧实现必然矛盾。负控把命中半径换成"真 mesh 半径"（`r - 14`）⇒
闸门红：`{"hover":-1,"target":0}`，正是"两套几何"。

### ③ 顺带修掉：hover 抬牌不该改 z

参考包 hover 时把 `targetZ` 推到 1.32（为了盖住邻牌）。但手牌是 `depthTest=false` +
固定 `renderOrder` ⇒ **绘制顺序与 z 无关**；而透视下 z 变大 ⇒ 牌更大更低，"轻抬"变成
"放大并往下掉"，底边直接掉出视口（闸门版面断言实测 817 > 800）。

修法：hover **不改 z**；叠放顺序改用 **per-card `renderOrder`**（静止 `10+i`、hover 25、
抬起 30），DOM 文字层 `zIndex` 同步。这本来就是"谁盖谁"的正确表达，而不是借用三维深度。

### 守卫

闸门 25 从 57 → **67 条**断言，新增：hover 与合法目标同源（含边缘点）、无目标牌压在敌人上
"hover 命中但不是合法目标"、`Esc` 取消不提交且清空 hover、**点选路径**（按下牌→原地松开→
再点敌人；这条原来靠被拆掉的 `onPointerUp`，不测就是赌它没坏）、紧凑态文字锚点偏差 ≤ 2px。

### 数字

闸门 **27** 不变；`ui-next` 证据 `commits=6` → **`commits=7`**（点选路径贡献一次）；
units 1233、导出 234、四条对拍不动。

### 残留（参考包没修、审阅提了的）'''

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))
print('port-plan §354 added')
