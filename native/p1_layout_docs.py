"""port-plan §355 + P1 文档：版面区域模型、四角投影、共享几何体、手牌数量夹具。"""

import io

PLAN = 'docs/port-plan.md'
P1DOC = 'docs/ui-next-p1.md'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── port-plan §355 ─────────────────────────────────────────────────────────
t = io.open(PLAN, encoding='utf-8').read()
anchor = '''### 残留（参考包没修、审阅提了的）'''
assert t.count(anchor) == 1

addition = '''---

## §355 版面区域模型（UX-3）、四角投影（P2-D）、共享几何体（P2-E）、手牌数量夹具（UX-6）

§353/§354 留下的四项一起做完。核心是**把版面收进一个纯函数**：`stage/combatLayout.ts`。

### ① UX-3：`computeCombatLayout(viewport, handCount)` 是版面唯一来源

之前版面常数散在三处 —— `Stage` 的 `-halfH * 0.66`、`fanSpread()` 的 `0.76`、CSS 里
`top: 100px` 的提示条。三者互相不知道对方存在，于是"手牌压操作栏""气泡压 HUD"只能靠截图发现。

现在一个函数给出：

| 输出 | 用途 |
|---|---|
| `cameraDistance` / `halfW` / `halfH` | 相机与可见范围（含 `FIT_HALF_WIDTH` 夹紧） |
| `fanSpread` / `fanCenterY` / `fanArc` | 手牌位置。**`fanCenterY` 由"手牌底边贴操作栏"反推** —— §353 那个 `0.66` 原本是量出来的魔法数，现在它有了推导 |
| `regions`（hud / combat / hand / actions，CSS 像素） | 闸门断言 + 提示条位置 + 安全区 |

`pxPerWorldAt(dist, worldZ, height)` 单独导出：**透视不是线性的**，手牌在 z=0.9 比 z=0 平面更近，
拿另一个平面的比例去推会让牌压到操作栏下面（§353 踩过）。

**提示条也接到模型上**：`TextOverlay` 的 rAF 把 `regions.hudBottom + 6` 写进 `--hint-top`，
CSS 只消费变量。于是"气泡压 HUD"在结构上不可能再发生，闸门也能拿**同一个**值断言
（原来写死 `hintTop >= 96`，那是两份认识）。

**HUD 高度是模型值**：`HUD_ROW_H = 36` 由截图校准（390×844 上 uikit HUD 实测约 86 CSS 像素）。
uikit 的 HUD 是 3D 画的、DOM 量不到 —— 这条一致性只能靠截图人工复核，注释里写明了。

### ② P2-D：四角投影

原来只投"中心 + 一个**未旋转**的角"估宽高，而手牌是斜着摆的（±15°），偏差正好决定窄屏上
"文字压不压到邻牌"。现在投四个角取屏幕外接矩形，另加一个 `faceW`（上、下两条边投影长度的均值
= 牌面看起来多宽）：外接矩形是**占位**，牌面才是**能写字的地方**。文字框宽度取
`min(faceW, visibleW)` —— 紧凑态受露出条限制，抬起/悬停受牌面限制。

### ③ P2-E：`CardEdge` 几何体共享

原来每个实例各建一份 `EdgesGeometry`（注释还写着"只创建一次"，其实是"每次挂载一次"）。
改成模块级懒单例，十张牌共用一份。注释也改成准确的描述（含"多 Canvas 时应改由上下文注入"）。

### ④ UX-6：手牌数量夹具（1 / 3 / 12）

`?debug&hand=N`（1..12）。⚠️ 第一版**没生效**：`hand` 的处理写在 `enemies` 的早退守卫**之后**，
不带 `enemies` 就永远执行不到 —— §4.19 的"守卫装在切口下游"。顺手把这段抽成纯函数
`debugScene(search)`，URL 怎么解释可以被单测。

闸门 25 现在跑 1 / 3 / 12 三档：手牌数正确、每张牌的**整个矩形**与**命中点**都在视口内、
**最右那张点得到**（12 张时 stride 约 29px，全部紧凑态）。

### 数字

闸门 **27**（不新增）；`ui-next` 断言 67 → **94 条**；`ui-pure` 证据加 `layout=6`
（区域有序 / 外缘在视口内 / stride ≥ 20px / 1 张不除零 / 安全区 / 非法视口抛错）；
units 1233、导出 234、四条对拍不动。

### 残留

- **操作栏按整条带子预留**（`ACTIONS_H = 56`，全宽）⇒ 左下角有空白；要与 StS 一样让手牌贴底，
  得把底部按左右分区（左：手牌，右：按钮），而不是整条带子；
- **队形仍按 `halfH` 比例算**，没接 `regions.combatTop/combatBottom`（区域模型目前管相机/手牌/
  提示条 + 断言；接进去要重新调参，留待 P2）；
- **安全区**已进纯函数并有单测，但浏览器里没验真机 `env(safe-area-inset-*)`；
- 手牌上限 12 是 P1 的规则，正式玩法允许更多时要先扩规则再加夹具。

### 残留（参考包没修、审阅提了的）'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))

# ── P1 文档 ───────────────────────────────────────────────────────────────
edit(
    P1DOC,
    '''## 5. 一条产品决策（与旧页面的**有意**分歧）''',
    '''## 4e. 版面收进一个纯函数（§355）

`stage/combatLayout.ts` 现在是版面的**唯一来源**：相机距离、可见范围、手牌扇形
（`fanSpread` / `fanCenterY` / `fanArc`）、以及四块区域 `regions`（HUD / 战场 / 手牌 / 操作栏，
CSS 像素）。手牌的中心高度由"**底边贴着操作栏**"反推 —— 之前那个 `-halfH * 0.66` 是量出来的
魔法数，现在它有推导了。

三个直接后果：

1. **提示条位置由模型驱动**（`--hint-top` = `regions.hudBottom + 6`），CSS 不再有第二份 HUD 高度；
   闸门也拿同一个值断言（原来写死 `hintTop >= 96`）。
2. **闸门能断言"东西没跑到别人的区域里"**：敌人整个落在 `combatTop..combatBottom`、
   手牌底边不越过 `actionsTop`、气泡在 `hudBottom` 之下。这些断言都用同一个函数算出来的值。
3. **手牌数量 1–12 张都是纯函数的一部分**：`?debug&hand=N` + 闸门跑 1/3/12 三档
   （12 张时 stride ≈ 29px、全部紧凑态、最右那张仍点得到）。

另两项审阅遗留一起做掉：**四角投影**（原来只投中心 + 一个未旋转的角，牌斜 15° 时宽高会偏；
现在取四角外接矩形，另给文字一个 `faceW` = 牌面宽度）与 **`CardEdge` 几何体共享**
（原来十张牌十份 `EdgesGeometry`）。

⚠️ 一个已知的版面取舍：操作栏按**整条带子**预留（56px 全宽），所以左下角有空白。要与 StS
一样让手牌贴底，得把底部按左右分区而不是整条带子 —— 留给 P2。

## 5. 一条产品决策（与旧页面的**有意**分歧）''',
    'p1doc 4e',
)

edit(
    P1DOC,
    '''  src/stage/formation.ts        左右阵营队形（纯函数，0–6 敌，业务 slot 不重编号）''',
    '''  src/stage/formation.ts        左右阵营队形（纯函数，0–6 敌，业务 slot 不重编号）
  src/stage/combatLayout.ts     版面唯一来源：相机/扇形/四块区域（纯函数，含安全区）''',
    'p1doc structure',
)
print('docs updated')
