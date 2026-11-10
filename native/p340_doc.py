"""§340/§341 的 port-plan 章节。"""

import io

PATH = 'docs/port-plan.md'

SECTION = """
## §340 Courier 补货闭环：四排、不加价、不部分提交

八轮 Review 2.1a / 2.1b / 1.4。三件事在同一段代码里，而它们的**共同形状**是"新加一排货架时，
只加了 `buy_*`，没加它该继承的所有同类规则"。

### 1. 无色与药水也要补货（2.1a）

wiki：*"When a Card, Relic, or potion is purchased from the Merchant, it will immediately be replaced
by another item of the same type."* fandom 补一句：*"The Colorless cards may be replaced by a
colorless card of a different rarity"*。

§332 加这两排时只写了 `buy_colorless` / `buy_potion`（买走、置 `-1`、完），**没有补货分支** ——
于是持 `the_courier` 时只有有色卡与遗物两排会补，另外两排**缩水**。屏幕上的表现只是"那一格空着"。

⇒ 新增 `restock_colorless_slot` / `restock_potion_slot`，与既有两条同一形状（避开货架上还活着的
同类、按稀有度取价、池子空就留空）。

### 2. 补货的商品**不受 A16 涨价**（2.1b）

wiki：*"**Any item re-stocked** by The Courier will not be affected by the 10% price increased 16
from Ascension 16+."*

`restock_card_slot` / `restock_relic_slot` 原来都走 `marked_up(price)` ⇒ 补出来的货按 A16 涨价。
**首次铺货**才该涨价（wiki 的价格表本身就带 `(50-61 16)`），补货不该。

### 3. 补货失败不许部分提交（1.4）

原形状：`push_*` → `adjust_gold` → 货架置空 → `restock_*()?`。补货里的 `pool_fits` / `rng.roll` /
`RunId::new` 任一失败 ⇒ 返回 `Err` 但**金币已扣、货已给**。

修法用 `RunState: Copy` 的整结构体快照（与 `rd-wasm` 的 `fight_begin` 同一条纪律）：

```rust
let before = *self;
... 扣钱、给货、置空 ...
if let Err(error) = self.restock_x_slot(...) { *self = before; return Err(error); }
```

⚠️ 真实内容触发不到这条路径（池子远小于 `MAX_POOL`、RNG 计数器不溢出、id 由内容门保证），
所以这是**纪律**而不是**故障**：判据用"注入一个超容量池子"来构造它，而不是等玩家踩。

### 判据

| 判据 | 钉住什么 |
|---|---|
| `the_courier_restocks_all_four_shelves` | 四排各买一次，**活着的格数不缩水**。四排是四条独立分支，写三条漏一条与全漏在现象上一样 |
| `restocked_items_are_not_marked_up_by_ascension_16` | A16 下补出来的价必须落在**基础价目带**里（`card_price_band`），不是 ×1.1 |
| `a_failed_restock_unwinds_the_whole_purchase` | 超容量池 ⇒ `Err(PoolTooLarge)` 且 `run == before`（**整个结构体相等**，含金币/牌组/货架/RNG 计数器） |

负控 4/4（`native/p340_negative.py`）：补货恢复 `marked_up` / 无色不补货 / 药水不补货 /
去掉回滚 —— 四条**各自**红，且 ②③ 用**不同的失败消息**区分（"colourless shelf" vs "potion
shelf"），否则"某一排没补"与"另一排没补"看起来一样。

### 夹具的两个坑（都踩了）

* `RunState::new(seed, health_max, gold, deck)` 的第三个参数是**金币**，不是 ascension ——
  要 A16 得走 `new_with_ascension`。第一版写成 `new(7, 80, 16, ..)`，于是"这局是 A16"当场为假。
* `TYPED_CARDS` 只有 4 张，`stock_shop` 摆 5 格之后**一张余量都没有** ⇒ 补货"抽不出来"是
  **夹具**的事，而判据会把它读成"补货没实现"。现在有一个 `restockable_pool()` helper。

---

## §341 `rd_run_in_fight()`：让 UI 场景表变成纯函数（关闭 G16）

八轮 Review 3.1 的根因。UI 的场景表里"战斗待开始"（SC-03）与"战斗中"（SC-03b）必须互斥，
而内核此前**没有任何一格**能区分它们：

| 候选 | 为什么不行 |
|---|---|
| `rd_run_pending()` | 两种情况下都是 `0` |
| `rd_run_node_resolved()` | 战斗中仍是 false（要等 `fight_end` 才结算） |
| `rd_env_done()` | **没有会话**时返回 `1`（"结束了"），不能反过来说"有没有战斗" |
| `rd_env_beat_count()` | 无会话返回 `-1`，能用但**间接**（"没有 beat" ≠ "没有战斗"） |

于是"未开始"只能是页面自己记的标志（`web/index.html` 的 `mode`）—— 场景表不是**状态**的函数，
而是**历史**的函数。3D 重写必须重新发明这条判断，而它是**事实**，不该住在渲染层。

⇒ 导出 `rd_run_in_fight()` → `1` 有 / `0` 没有 / `-1` 没有局。读的是 `RunSession.in_fight`：
`rd_run_fight_begin` 的**提交点**写它、`rd_run_fight_end` 收尾清它 —— 与"战斗中不许存档/回放"
用的是**同一个字段**，所以页面看到的与内核看到的是同一个事实。

判据 `the_run_layer_reports_whether_a_fight_is_running`（rd-wasm）：四态全覆盖
（`-1` → `0` → `1` → `0`），并顺带钉住"战斗中 `archive_fill` 必须拒绝"—— 那条拒绝用的就是这一格。

### 顺带修的三处 UI 文档问题（Review 3.1/3.2/3.5）

1. **场景表重排**：**强状态优先** —— 无局 → 战斗中 → 遗物欠账 → 终局 → `pending` 各屏 →
   预备战斗 → 幕尽头 → 地图兜底。旧表把 SC-03 排在 SC-03b 前（"未开始"判不出来）、
   把**兜底**的 SC-02 排在 SC-02b 前（⇒ 后者永远不可达）。
2. **§5 的措辞**：原来写"`pending` 是唯一的场景判别式"，与 §1 自己列的 `kind`/`unknownRoom`/
   `eventFight` 矛盾。改成"`pending` 是优先级很高的一项输入，但场景由三类权威事实共同决定"。
3. **§8 的分类**：`rd_run_observe_len` / `rd_env_observe_len` / `rd_env_pile_len` 不是文本长度，
   却混在"文本 `_len`/`_into`"表里 ⇒ 移到 §8.3（"非文本但同样成对"）。
   顺带清掉 `lib.rs` 里两处 `122` 旧注释（表达式早已是 148，只有注释在说谎）。

### 还欠的一件事（写进文档，不假装做了）

`ui_state_check.py` **只**证明"文档点名的导出都存在、每个导出都被登记"。它**不**证明场景谓词
互斥、也不证明某个字段写在正确的表格行里（名字在文中出现过就算登记 —— §8 的分类错位就是
这么混过去的）。所以 `docs/ui-state-model.md` §7b 记下了下一步：19 个场景各一份 snapshot 夹具，
断言 `classifyScene(snapshot)` **唯一命中**，多重命中/零命中都**报错**而不是"取第一个"。

### 数字

`rd-run 221`（218 + 3）、`rd-wasm 183`（182 + 1）、`rd-core 819`、units **1223**（下限 1219 → 1223）；
四条对拍不动；`WEB_SMOKE PASS`；导出 218 → **219**（`ui-state` 闸门证据 `exports=219 mentioned=180`）；
23/23 闸门。
"""

t = io.open(PATH, encoding='utf-8').read()
assert '## §340' not in t
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + '\n' + SECTION)
print('port-plan §340/§341 added')
