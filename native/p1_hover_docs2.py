"""docs/ui-next-p1.md 补 §4d（文字锚点 + hover 单源）。"""

import io

PATH = 'docs/ui-next-p1.md'
t = io.open(PATH, encoding='utf-8').read()

old = '''## 5. 一条产品决策（与旧页面的**有意**分歧）'''
new = '''## 4d. 两条「同一个事实两个来源」（§354）

**文字锚点**：紧凑态的文字落在**露出来那条**的中心（`hitX`），不是牌心。叠放是右压左，牌心
可能被右邻盖住 —— 文字放牌心等于把费用数字塞到邻居底下。负控退回牌心 ⇒ 偏差 **18px**（阈值 2px）。

**hover 单源**：原来"哪个敌人被指向"有两处（R3F 射线 vs 屏幕命中，半径 `r+14`），边缘会
"绿环亮着但没有 hover 高亮"。现在 `window.pointermove` 常驻，一次算出「指针下是谁」（视觉）
与「是不是合法目标」（提交），两者由**同一个** `enemyAtScreen` 回答。R3F 只负责卡片上的按下。
闸门把指针放在**敌人轮廓外、触摸半径内**（`r+10`）来钉这条 —— 中间点测不出来（旧实现在
中心也一致）。

顺带修掉：hover 抬牌原来把 z 推到 1.32，而手牌 `depthTest=false` + 固定 `renderOrder` ⇒
**z 根本不影响叠放**，透视下只会让牌更大更低（底边掉出视口 817 > 800）。改成 per-card
`renderOrder`（静止 `10+i` / hover 25 / 抬起 30），hover 只抬 y。

## 5. 一条产品决策（与旧页面的**有意**分歧）'''

assert t.count(old) == 1, '命中 %d 次' % t.count(old)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))
print('p1 doc updated')
