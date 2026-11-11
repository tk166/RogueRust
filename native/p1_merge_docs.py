"""文档：合并参考包（§353）+ 更新 P1 文档里的版面与手势说明。"""

import io

PLAN = 'docs/port-plan.md'
P1DOC = 'docs/ui-next-p1.md'
README = 'README.md'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── port-plan §353 ─────────────────────────────────────────────────────────
t = io.open(PLAN, encoding='utf-8').read()
anchor = '''### 数字

闸门 25 → **26**；`ui-next` 证据 `commits=4` → **`commits=6`**；units 1233、导出 234、四条对拍不动。'''
assert t.count(anchor) == 1
addition = '''### 数字

闸门 25 → **26**；`ui-next` 证据 `commits=4` → **`commits=6`**；units 1233、导出 234、四条对拍不动。

---

## §353 合并第十三轮参考包：左右战场布局 + 手势反馈

先合并设计、再把修复套在新结构上（避免"修一遍、合并后重做一遍"）。参考包 47 条锚点里
**46 条**直接命中，唯一不兼容的是 `Stage.props`（本仓库的 `}` 与 `export function Stage` 之间
有一个空行）；合并脚本只对这一条做容差，**不做全局模糊匹配** —— 全局容差会把"锚点对不上"
这个真信号吃掉。

### 拿进来的

| 文件 | 内容 |
|---|---|
| `stage/formation.ts`（新） | 纯函数队形：我方永远在左；竖屏右侧单列（≤6，按密度缩放）；横屏两行 `ceil/floor`、每行 ≤3；**业务 slot 原样带出**；>6 或重复 slot ⇒ `RangeError`（不静默截掉可攻击目标） |
| `input/hitTest.ts`（新） | 屏幕空间命中：`enemyAtScreen`（合法集合 + 触摸半径）/ `cardAtScreen`（按**露出条** `hitX`）。读 Stage 的投影，不复制相机数学 |
| `pointerMachine.ts` | `resultSeq`（§352 P1-A）、无目标牌 `targetSlot: chosen.slot`（§352 P1-B）、新增 `dismiss`（长按看详情与出牌互斥） |
| `Stage.tsx` | 队形接入；hover 轻抬；选中牌停在**预览位**（不粘手指，不挡敌人）；瞄准连线；面向相机的轮廓环（青=可选 / 绿=当前目标 / 红=非法）；`1-exp(-λ·dt)` 插值 |
| `App.tsx` | 唯一 `activePointer`（第二根手指不能偷牌）；**真实位移**（8px 阈值终于有牙）；`pointercancel`/`blur`/Esc 统一 `cancel`；长按 450ms 开详情；右键详情；`?debug&enemies=N` |
| `TextOverlay.tsx` / `styles.css` | hover 标题可读；详情**可见关闭按钮**；手势提示条（文字冗余，不只靠颜色） |

**合并后 P1-A/P1-B 的修复来自参考包的 `resultSeq` / `finish` 归一**，我上一节自己写的那份
补丁（`native/p1_review13_ab.py`）已删除 —— 同一件事留两份实现必然漂。

### 合并后自己动手改的三处（都是**量出来**的）

`native/_dbg_layout.mjs` 打出真实数字后发现：

| 现象 | 真实数字 | 修法 |
|---|---|---|
| 手牌压底部操作栏 | 390×844 中间那张卡底 804、操作栏 790 起；1280×800 卡底 817 > 800 | 扇形 `y` 系数 0.72 → **0.66**。⚠️ 我原来按 z=0 平面算"装得下"，但手牌在 z≈0.9（离相机更近）⇒ **透视下更大更低**，不能拿另一个平面的比例去推 |
| 竖屏敌人标签互压 | 两个敌人只隔约 114px，而三行标签约 60px 高 | 竖屏间距上限 1.0 → **1.35** |
| 提示气泡盖住 HUD | 气泡 top=14、HUD 在 14–100 | 窄屏 `top` 挪到 100px（HUD 两行高约 96） |

### 守卫

- **闸门 25** 加 4 条版面断言：两张视口下**每张牌的整个矩形**都在视口内（底部留 6px）——
  只查"牌心在视口内"是上一版的做法，牌身被裁掉一半它也报通过；竖屏相邻敌人间距 ≥ 两倍半径 + 8；
  窄屏气泡顶边 ≥ 96（HUD 是 uikit 的 3D 层，DOM 量不到，这条用布局常量，注释写明原因）。
- **闸门 27 `ui-pure`**（新）：队形 0–6 敌 × 横竖屏、**非连续 slot 原样带出**、`>6`/重复 slot
  抛 `RangeError`、屏幕命中 5 条、状态机 4 条（含 `dismiss`）。纯函数的最强证据是穷尽式断言，
  在浏览器里跑同样的事要几十秒且只能覆盖一两种组合。

### 数字

闸门 26 → **27**；`ui-next` 证据 `commits=6`（P1-A/B 的两个场景仍守得住）；units 1233、导出 234、
四条对拍不动。合并引入的新文件：`formation.ts` / `hitTest.ts`。

### 残留（参考包没修、审阅提了的）

- **UX-2 文字锚点**：`TextOverlay` 仍把文字放在 `screen.x`（牌心），紧凑态费用数字应落在
  `hitX`（露出条）；当前 33px 宽度下恰好还没被吃掉，**但这是运气**；
- **P2-D** 投影只投中心 + 一个角，未算旋转后四角；
- **P2-E** `CardEdge` 每张牌一份几何体（注释已改为"每次挂载一次"，不再声称全手牌共享）；
- **UX-3 完整版**：`formation` 只算英雄与敌人，HUD / 手牌 / 操作栏没有统一的
  `CombatLayout(viewport, safeArea, handCount)`，也没有 `env(safe-area-inset-*)`；
- **UX-6** 手牌数量（1/3/5/10/12+）仍无夹具（敌人 1–6 已有）；
- **hover 双源**：拖拽中"哪个敌人被指向"仍有 R3F `onPointerMove`（视觉）与 `hitTest`（提交）
  两个来源，命中半径不同（`r+14` vs 真 mesh）⇒ 边缘会出现"绿环亮着但没有 hover 高亮"。
  统一到 `hitTest` 是下一步。'''
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))

# ── P1 文档：版面/手势/结构更新 ─────────────────────────────────────────────
edit(
    P1DOC,
    '''## 5. 一条产品决策（与旧页面的**有意**分歧）''',
    '''## 4c. 合并第十三轮参考包之后（§353）

版面从"英雄居中、敌人左右"改成**左右阵营**（我方永远在左）：竖屏敌人在右侧单列（≤6，按密度
缩放），横屏两行 `ceil/floor`（每行 ≤3）。队形是纯函数（`stage/formation.ts`），业务 `slot`
原样带出，`>6` 或重复 slot 直接 `RangeError` —— 不静默截掉一个可攻击目标。

交互补齐（都是参考包带进来的）：唯一 `activePointer`（第二根手指不能偷牌）、**真实位移**
（8px 阈值终于有牙，之前四处都送 `999`）、`pointercancel`/`blur`/Esc 统一取消、长按 450ms
看详情、右键看详情、详情有可见关闭按钮、瞄准连线与面向相机的轮廓环（青=可选/绿=目标/红=非法）。

**合并后量出来的三处版面问题**（`native/_dbg_layout.mjs`，不是看截图猜的）：

| 现象 | 数字 | 修法 |
|---|---|---|
| 手牌压底部操作栏 | 390×844 卡底 804 / 操作栏 790 起；1280×800 卡底 817 > 800 | 扇形 `y` 0.72 → **0.66** |
| 竖屏敌人标签互压 | 两敌只隔约 114px，三行标签约 60px | 竖屏间距上限 1.0 → **1.35** |
| 提示气泡盖住 HUD | 气泡 top=14、HUD 14–100 | 窄屏 `top` → 100px |

⚠️ 第一条的教训：我原来按 z=0 平面算"装得下"，但手牌在 z≈0.9（离相机更近）⇒ **透视下更大更低**。
**投影不是线性的，别拿另一个平面的比例去推** —— 这也正是闸门 25 新增的四条版面断言的理由
（只查"牌心在视口内"会让牌身被裁掉一半也报绿）。

## 5. 一条产品决策（与旧页面的**有意**分歧）''',
    'p1doc section 4c',
)

edit(
    P1DOC,
    '''```
web-next/
  src/input/pointerMachine.ts   纯函数状态机（pressed/dragging/targeting/commit/rebound）
                                + decide()：抬起时提交还是回弹，可穷举单测''',
    '''```
web-next/
  src/input/pointerMachine.ts   纯函数状态机（pressed/dragging/targeting/commit/rebound）
                                + decide()：抬起时提交还是回弹，可穷举单测
                                + resultSeq：事件身份（同一动作两次是两个事件）
                                + dismiss：长按看详情与出牌互斥
  src/input/hitTest.ts          屏幕空间命中（指针在 mesh 外松开也能判定目标）
  src/stage/formation.ts        左右阵营队形（纯函数，0–6 敌，业务 slot 不重编号）''',
    'p1doc structure',
)

edit(
    README,
    '''**`ui-next-p1.md`**（**P1 的 R3F PoC 实测**''',
    '''**`ui-next-p1.md`**（**P1 的 R3F PoC 实测**（§353 起为左右阵营布局 + 完整手势反馈）''',
    'readme pointer',
)
print('docs updated')
