"""素材流水线文档：port-plan §369 + README + docs/ui-p8-assets.md。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
assert '## §369' not in t
section = '''

---

## §369 素材流水线：内容 id → 清单 → 注册表 → 绘制

目标不是"画出好看的素材"，而是**把这条链打通并且可断言**：以后换成真正的美术，替换的是
链条的最后一环，前面三环不动。

### 369.1 四层

| 层 | 文件 | 谁生成 | 可测性 |
|---|---|---|---|
| ① 清单 | `web-next/src/assets/manifest.ts` | `python native/build_assets.py`（从内容镜像**穷尽**枚举） | 闸门 45：与内容**逐个 id** 对账 |
| ② 注册表 | `web-next/src/assets/registry.ts` | 手写（解析 + 降级 + 计数） | 闸门 45：确定性、降级被计数 |
| ③ 目录 | `web-next/src/assets/geometry.ts` | 手写（**16 种立体排列，纯数据**） | 闸门 45：≥2 个基本体、只引用已知形状/角色、16 种全被用到 |
| ④ 绘制 | `stage/EnemyFigure.tsx` + `assets/Badge.tsx` | 手写（three 基本体 / DOM 徽章） | 闸门 46：截图里有彩色像素、DOM 里两位大写字母 |

**关键取舍**：清单是**生成**的。所以"内容加了 30 张牌而美术没跟上"在**生成时**就暴露
（闸门 45 逐个 id 对账），而不是等玩家看到灰块。

### 369.2 三维敌人：16 种立体排列组合

`geometry.ts` 里每种原型是 `{ note, parts[] }`，`parts` 每项 = 基本体（球/盒/锥/柱/环/八面体/
胶囊）+ 尺寸 + 位置 + 可选旋转 + 角色（`body`/`accent`/`eye`）。

| 原型 | 基本体 | 原型 | 基本体 |
|---|---:|---|---:|
| slime | 3 | construct | 4 |
| humanoid | 6 | gremlin | 7 |
| beast | 7 | slaver | 5 |
| louse | 9 | sentinel | 5 |
| spire_guard | 3 | floating_orb | 4 |
| plant | 6 | crystal | 4 |
| boss_blob | 7 | boss_machine | 5 |
| worm | 5 | ghost | 4 |

61 个敌人分布在 16 个原型上（`slime` 系 6 个、`gremlin` 系 6 个、`boss_machine` 5 个…），
**16 种全被用到**（闸门断言没有死目录）。没有手写覆盖的敌人按**稳定哈希**挑原型 ——
所以新怪物自动有素材，不会出现空洞。

渲染层只认"原型 + 调色板 + 角色"：加敌人只改清单，加原型只改目录，**渲染代码不动**。
几何体在场景里**共享**（7 种基本体各一份），靠 `scale` 变形 —— 61 个敌人 × 5 个基本体不会变成
300 份 geometry。

### 369.3 二维元素：两位大写字母

规则（生成器与注册表**同一份逻辑**，闸门逐条比对）：

| 输入 | 输出 | 规则 |
|---|---|---|
| `twin_strike` | `TS` | 前两个词的首字母 |
| `strike` | `ST` | 单词取前两位 |
| `strike+` | `ST` | 升级后缀**不改变**字母（升级不改变"这是哪张牌"） |
| `standard.vulnerable` | `SV` | `.` / `_` / `-` 都当分词 |
| `a` | `AX` | 不足两位用 X 补齐 |

覆盖：295 卡 / 152 遗物 / 33 药水 / 150 状态。

⚠️ **字母会撞车**：295 张牌只有 106 组不同字母，**95 组有碰撞**（例如 `searing_blow` /
`sword_boomerang` / `body_slam` 都是 `SB`）。这一版**接受**碰撞 —— 但闸门把它**量出来**并设预算，
因为"换成图标时它应该是 0"这件事需要一个数字盯着。

### 369.4 已经用进产品界面

不只是预览页：**奖励屏**的候选卡、**商店**的四排货位、**牌组弹窗**的每一行、**药水腰带**的每一瓶
都带徽章（闸门 46 逐个数 DOM）。

### 369.5 素材库预览页

`web-next/dist/assets.html`（`npm run build` 产出）：三块 ——

1. **三维原型**：16 种按 4×4 摆开（这一页最有用：截图能一眼看出"哪个原型画歪了"）；
2. **敌人**：61 行列表 + 选中一个在 3D 里看（61 个塞一个画布会看不清）；
3. **二维元素**：四个表的字母网格（295 张牌一屏扫过去）。

截图证据：`docs/ui-p8-assets-archetypes.png`、`-enemies.png`、`-badges.png`。

### 369.6 修掉的两个"看不见的错"

1. **网格布局写错**：`gridPosition` 里有个 `* 0` 的残项，16 个原型全挤在画布中间一小团。
   纯逻辑断言发现不了它 —— **截图**是唯一判据（这也是素材页值得存在的理由）。
2. **`gl.readPixels` 读不到东西**：合成之后 drawing buffer 已清（实测全 0）。改用 CDP 截图统计
   彩色像素（28661 个）。"读晚了"与"没画"是两件事，前者会让人把闸门改成假绿。

### 369.7 数字

闸门 44 → **46**；清单 61/295/152/33/150；原型 16；卡牌字母碰撞 95 组（预算内）；
`ui-assets-render` 截图彩色像素 28661；units 1233、导出 234、四条对拍不动。
'''
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + section)

edit('README.md', '**聚合验收**：44 道闸门', '**聚合验收**：46 道闸门', 'readme count')
edit(
    'README.md',
    '''### 10.4 已知缺口''',
    '''### 10.3b 素材库（`assets.html`）

```bash
python native/build_assets.py     # 内容变了就重跑：生成 web-next/src/assets/manifest.ts
npm run build && node web-next/scripts/serve.mjs --port 8080
# 打开 http://127.0.0.1:8080/assets.html
```

* **三维敌人**：16 种立体几何排列组合（`assets/geometry.ts`，纯数据），61 个敌人按清单分配原型；
* **二维元素**：卡/遗物/药水/状态各两位大写字母 + 调色板（`assets/registry.ts`）；
* 产品界面（奖励/商店/牌组/药水）已经在用这些徽章；三维敌人也已经在战斗里用上了。

### 10.4 已知缺口''',
    'readme assets',
)

doc = '''# 素材流水线（P8）

> 生成器 `native/build_assets.py`；清单 `web-next/src/assets/manifest.ts`；
> 注册表 `assets/registry.ts`；目录 `assets/geometry.ts`；绘制 `stage/EnemyFigure.tsx` +
> `assets/Badge.tsx`；预览页 `assets.html`。闸门 45（纯函数）与 46（渲染）。

## 1. 一条链，四层

```
内容镜像（tools/contentc/.../sts.roguedeck.json）
        │  python native/build_assets.py（穷尽枚举 id）
        ▼
manifest.ts   ── 每个 id 一条：敌人→{原型, 调色板, 体型, boss}；其它→{两位字母, 调色板}
        │  registry.ts（解析 + 降级 + 计数）
        ▼
geometry.ts   ── 16 种原型的**纯数据**（parts: 基本体 + 尺寸 + 位置 + 角色）
        │
        ▼
EnemyFigure（three 基本体）/ Badge（DOM 两位字母）
```

**为什么清单要生成**：手写表必然有洞，而洞只会在玩家看到灰块时被发现。生成之后，
"内容加了东西而美术没跟上"在闸门 45 的**逐个 id 对账**里立刻暴露。

## 2. 三维：16 种排列组合

| 原型 | 说明 | 基本体 |
|---|---|---:|
| slime | 一大球 + 一小球 | 3 |
| humanoid | 盒躯干 + 球头 + 两臂 | 6 |
| beast | 盒身 + 锥头 + 四腿 | 7 |
| construct | 八面体 + 两环 | 4 |
| gremlin | 球身 + 双锥耳 + 双脚 | 7 |
| slaver | 胶囊身 + 盒肩 + 锥兜帽 | 5 |
| louse | 胶囊 + 两触角 + 六腿 | 9 |
| sentinel | 柱身 + 面罩 + 两球 | 5 |
| spire_guard | 锥塔 + 环 | 3 |
| floating_orb | 球 + 两轨道环 | 4 |
| plant | 茎 + 三叶 + 花苞 | 6 |
| crystal | 三块八面体 | 4 |
| boss_blob | 大球 + 三卫星 + 环 | 7 |
| boss_machine | 盒身 + 两柱臂 + 环 | 5 |
| worm | 三球 + 锥头 | 5 |
| ghost | 球头 + 锥尾 + 双眼 | 4 |

渲染层只吃 `{ 原型, 调色板, 体型, boss }`。加敌人改清单，加原型改目录，**渲染代码不动**。
几何体在场景里共享（7 种基本体各一份），靠 `scale` 变形。

## 3. 二维：两位大写字母

```
twin_strike        → TS      （前两个词首字母）
strike             → ST      （单词取前两位）
strike+            → ST      （升级不改字母）
standard.vulnerable→ SV      （. _ - 都当分词）
a                  → AX      （不足两位补 X）
```

⚠️ **碰撞**：295 张牌只有 106 组不同字母，**95 组有碰撞**（`searing_blow` / `sword_boomerang` /
`body_slam` 都是 `SB`）。这一版接受，闸门把它**量化**并设预算 —— 换图标时这个数该降到 0。

## 4. 预览页

`assets.html` 三块：三维原型（4×4，看排列是否成立）/ 敌人（61 行 + 选中看单个）/ 二维（四表网格）。
截图：`docs/ui-p8-assets-archetypes.png`、`-enemies.png`、`-badges.png`。

## 5. 两个"看不见的错"

1. **网格布局的 `* 0` 残项** ⇒ 16 个原型挤在画布中间一小团。纯逻辑断言抓不到，**截图**是唯一判据。
2. **`gl.readPixels` 读不到东西** ⇒ 合成之后 drawing buffer 已清（实测全 0）。改用 CDP 截图统计
   彩色像素（28661）。"读晚了"和"没画"是两件事 —— 前者会让人把闸门改成假绿。

## 6. 下一步（真正的美术）

* 把 `geometry.ts` 的 `parts` 换成 `{ model: GLB, clips }`，`EnemyFigure` 换成 GLB 加载器；
* 把 `Badge` 的内部实现换成图标/立绘（`registry.badgeLook()` 接口不变）；
* 字母碰撞降为 0 之后，闸门 45 的预算可以收紧到 0。
'''
io.open('docs/ui-p8-assets.md', 'w', encoding='utf-8', newline='\n').write(doc)
print('docs written')
