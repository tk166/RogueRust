# 素材流水线（P8）

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
