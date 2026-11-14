"""§397–§399 文档：第十六轮 Review 的处置 + 表现层管线。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: %d' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


SECTION = '''

---

## §397–§399 第十六轮 Review 处置：队形回归、素材流水线一致性、表现层契约

审阅文档：`docs/vibe/Review_16_ac6e2af_32c0a20_Assets_Animation.md`。
逐条核过源码，**P1 与四条 P2 全部成立**（其中哈希的四个反例我用 Node 复算，逐个对上）。

### 397 P1：横屏 4 名敌人被改回 2+2 —— 这是我自己的错

时间线（写进代码注释，避免下一轮再"修回去"）：

| 提交 | 做了什么 | 依据 |
|---|---|---|
| `956facb` §353 | 照参考包 `ceil(n/2)`/`floor(n/2)` | 参考包 |
| `8383837` §360 | 改成 **n ≤ 4 单排** | **用户原话**："n<=4 的时候都只有一排" |
| `35bf81a` §361 | 又改回 **n ≤ 3**（4 → 2+2） | 第十四轮 Review 的 P1-C |

问题在最后一行：那条审阅说"n=4 一排 4 名违反 **每排 ≤ 3** 这条更早、更强的约束"，
但**那条约束不存在** —— `inv:§` 里没有、参考包里没有，它只出现在那条审阅自己的措辞里，
然后被我抄进了注释与闸门断言。

> ★ **审阅是证据的一种，不是需求来源。** 一条"更强的约束"必须能指到 `inv:§` 或 wiki 原文，
> 否则它只是审阅者的偏好。用户明确说过的话优先级高于审阅意见。

修法：`singleRow = n <= 4`（5 → 3+2、6 → 3+3），注释里把三次改动与依据都写清楚；
闸门 27 的期望改成 `[1],[2],[3],[4],[3,2],[3,3]`，并补一条"4 名同排且 x 两两不同"。

### 398 P2×4：素材流水线的一致性（审阅 §3/§4/§5）

**① Python 与 JS 不是同一个 FNV-1a。** Python 遍历 **UTF-8 字节** + 精确 32 位乘；
JS 遍历 `charCodeAt`（UTF-16 code unit）+ 浮点乘（乘积超 2^53 后 `>>> 0` 的低位已不准）。
审阅给的四个反例我复算过，逐个对上：

| 输入 | 旧 JS | 正确 FNV-1a | mod 16 |
|---|---:|---:|---|
| `not_a_real_enemy` | 1294215100 | 2453344752 | 12 vs 0 |
| `new_monster_id` | 116679432 | 2615040844 | 8 vs 12 |
| `strike` | 2778783723 | 632598351 | 11 vs 15 |
| `中文` | 1362277804 | 3297308741 | 12 vs 5 |

修法：`Math.imul` + `TextEncoder().encode()`（UTF-8），与 Python 逐字节一致。

**② 调色板回退的种子不同。** 生成器 `stable_hash(id + '|p')`，JS 回退 `stableHash(id)`
⇒ 哈希修好了，同一条 id 在"清单里"与"降级时"仍会落到不同调色板。修法：JS 也带 `|p`。

**③ `gremlin_nob` 被当成 Boss。** 它在生成器的 boss 名单里 ⇒ `scale=1.55` + 光环。
StS1 的 Gremlin Nob 是**精英**。修法（按审阅的建议，把"玩法身份"与"视觉体型"分开）：
`boss` 只由真 Boss 决定；新增 `tier` 字段（`boss`/`elite`/`normal`），精英 `scale=1.3`、**不加光环**。

**④ 闸门的盲点：只验覆盖，不验"生成器变了没重跑"。** `ui_assets_check.mjs` 里明写着
"不调 `python build_assets.py --check`"（验收链 PATH 剥空，跑不了 python）。
于是"改了 palette/scale/boss 规则但清单没重跑"这条**永远不会红**。

修法（不需要 python，Node 能算 sha256）：
* 生成器把**自己源码的 sha256**（`GENERATOR_SHA`）写进 `manifest.ts`，闸门重算比对
  ⇒ "改了生成器没重跑"立刻红；
* 生成器同时写一张**哈希对拍表**（`HASH_FIXTURES`，含 ASCII/中文/空串），闸门逐条验证
  JS `stableHash` == Python 的结果 ⇒ 跨语言漂移立刻红；
* 补"精英 ≠ Boss"的两侧断言（`gremlin_nob` 是 elite、`slime_boss` 仍是 boss）
  + 一条穷尽断言（没有一只怪 `boss=true` 却不是 boss 档）。

### 399 R1：表现层契约 —— Beat → Cue → 视觉配方（审阅 §6/§7）

**问题**：`planBeats` 把内核 Beat 压成 `{kind, at, text, tone, duration}`，`def`（卡/状态定义）、
`actor`、`flags` 全丢 ⇒ "Strike 的斩击"与"Bash 的重击"在数据上一模一样，
将来做动画只能靠数值/文案**反推原因**（而反推迟早错）。

**新增两层（都是纯函数/纯数据，闸门 57 穷尽断言）**：

```text
Beat{kind, actor, target, flags, a, b, c, def}        ← 内核权威（规则事实，未改一行）
   │  presentation/cues.ts::translateAll()            ← 纯函数；缺信息就降级，不猜
   ▼
Cue{eventId, origin, actorSlot, targetSlot, value,
    effectKey, phase, anchorSlot, appearanceId}       ← 语义（"谁做的 / 做了什么"）
   │  presentation/registry.ts::recipeFor(effectKey)  ← 纯数据表（22 条配方 + 显式回退）
   ▼
{color, shape, duration, shake, motion}               ← 视觉配方（DOM 与将来的 3D 共用）
```

三条纪律：

1. **`origin` 不猜**：`def` 为空 ⇒ `system`；`standard.*` + 状态类 kind ⇒ `status`；
   出牌 + 卡 id ⇒ `card`。⚠️ **伤害即使带 `def` 也不猜成某张卡** —— 毒/荆棘/遗物都能造成伤害
   （闸门 57 有这条反证）；
2. **逐卡可分**：`card.strike` / `card.bash` / `card.cleave` … 有各自配方（`motion` 不同），
   未列出的卡落到 `card.play` 通用配方（`fallback=false`，不是兜底灰）；
3. **未知不静默**：真正未知的 key 落到 `FALLBACK_RECIPE` 并报 `fallback=true`，调用方计数。

**顺手修掉审阅 §6 的"陷阱 1"（冻结锚点）**：`BeatLayer::anchorOf` 以前用**当前**
`layout.enemies.find(slot)` 取位置，而槽位会被重用（Boss 分裂/召唤/死亡）。
现在 Cue 在**创建那一刻**冻结 `appearanceId`，播放时若该槽位的外观已变，
退回屏幕中上而不是画在新对象头顶（`data-cue-*` 属性让闸门可断言）。

**还顺带**：`damage.dot` **不震屏** —— 持续伤害没有"被打"的动作，震屏会让玩家以为敌人出手了。

### 399.1 下一阶段的顺序（按审阅 §9 收敛，不一次做完）

| 里程碑 | 范围 | 验收 |
|---|---|---|
| **R2 动画原型** | `ActorRenderer`（读 `VisualAssetSpec`）+ cast→hit→resolve 分阶段调度 | skip/reducedMotion 不改游戏状态；槽位重用不画错人 |
| **R3 GLB 渐进** | 两个代表体型（Cultist / Slime）的 GLB + sockets + clip；`kind:'gltf'` 那一路 | fallback 不丢；缓存/卸载；断网/缺 clip 有证据 |
| **R4 内容驱动** | 配方表外置成数据文件 + 素材画廊 | 新增一种卡/状态/遗物触发，**不改** `Stage.tsx`/`EnemyFigure.tsx` |

`VisualAssetSpec`（`procedural | gltf` 判别联合）已经在 `presentation/registry.ts` 里定形，
但**没有**接进 `EnemyFigure` —— 现在换会把数据契约改一半，正是审阅说的"不要半程序化半 GLB"。

### 399.2 闸门与数字

* 闸门 **57 `ui-cues`**（13 条）：13 种 kind 穷尽可翻、origin 四条含反证、逐卡可分、
  配方回退显式、显式配方 22 条字段完整、冻结锚点一路带到 `BeatEffect`、`translate` 纯函数、
  未知 kind 可计数。
* 闸门 45（`ui-assets`）新增 4 条：生成器指纹、哈希对拍（6 条含中文）、
  精英不是 Boss、没有假 Boss（穷尽）。
* 闸门 27（`ui-pure`）队形期望改回 `n ≤ 4 单排`。
* 数字：闸门 **57**、wasm 1,376,110 B、配方 22 条、定向牌 88 张不变。

### 399.3 还欠的

* 3D 动画本身没有（只有 DOM 飘字 + 形状/震屏）；`phase`（cast/hit/resolve）还没被调度器使用；
* `enemyMove` 这个 origin 分支还没接（内核 Beat 里没有"敌人招式 id"，要加就得动 Rust Beat ——
  审阅也说"别为尚无证据的动画需求重构规则层"）；
* 配方表还是 TS 常量，不是内容侧数据文件（R4）；
* 审阅提到的"每个修复附复现材料"（commit/wasm sha/content fingerprint/save/seed/视口/截图/闸门）
  只在 `port-plan` 里手工写，没有模板化。
'''

PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
assert '## §397' not in t
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + SECTION)

edit('README.md', '**聚合验收**：56 道闸门', '**聚合验收**：57 道闸门', 'readme gates')
print('docs written')
