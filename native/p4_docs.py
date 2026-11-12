"""P4 文档：port-plan §364 + README + docs/ui-p4-scenes.md。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── port-plan §364（追加到文件尾，§363 之后）────────────────────────────────
PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
assert '## §364' not in t

section = '''

---

## §364 P4 交付：全部实际可达的经营/事件/待决场景

plan P4 的退出条件是"18 条权威场景中，当前内容实际可达者都有可操作 UI；UI-only `SC-14` 可用；
未知状态清晰报错"。这一节记的是**每一屏的判据与交互**，以及一路上修掉的**五个真 bug** ——
其中两个（Boss 哨兵、宝箱"打开即结束"）会让玩家**软锁**，一个（`lastLoot`）让战利品永远看不见。

### 364.1 新增的屏

| 屏 | 场景 | 数据来源（全部内核） | 交互要点 |
|---|---|---|---|
| `ShopScene` | SC-05 | 四类货架各 `_count/_id/_price`；`remove_price`/`removal_available` | 价格**只显示内核那一份**；买不起的按钮**能点**（点了说差多少），不是禁用；已售货位**保留位置**；删卡服务每家店一次 |
| `RestScene` | SC-06 | `campfire_options`（**位掩码**）+ `rest_heal` + `girya_lifts` | 画哪些按钮由位掩码决定；休息显示**内核算的**回复量（已含遗物加成）；锻造/抽烟斗进选择器 |
| `ChestScene` | SC-07 | `open_chest` | **打开即结束**（相位归 0），所以只有"打开"和"不打开就走"两个按钮 |
| `EventScene` | SC-08 | `event_id/text` + `event_option_count/_available/_label/_effect_at` | 按钮条数由内容给（不是写死 2）；不可用的**画出来但禁用**并说明原因；效果翻人话 |
| `EventOfferScene` | SC-10 | `event_offer_len/_title/_take` | 候选数量由运行层给（`The Library` 是 20 选 1） |
| `DeckSelectOverlay` | SC-01b / SC-09 / 锻造 / 抽烟斗 / 删卡 / 欠账 | `deck_count/_id/_title` | **牌组下标就是身份**；想找牌加过滤框而**不重排**；不可选的牌说明原因（升级过的不能再升级） |
| `PickupOverlay` | SC-11a/b | `pickup_picks/_add/_change/_offer_*` | 盖在当前屏之上、**关不掉**（欠账必须还）；`orrery` 可跳过、`singing_bowl` 可换 +2 上限 |
| `PileOverlay` | 战斗中 | `env_pile_len/_card_*` | 抽牌堆**按名字排序**显示（不泄露内部顺序，那是规则不是实现细节） |
| `PotionBar` | 全局 | `potion_effect/_needs_fight` | 战斗外只有 run-only 的能喝（§158）；要敌人的药水先"选目标" |
| `SettingsOverlay` | 全局 | 运行层状态 | 种子/进阶/场景/相位/对账/遗物/药水/日志 —— 这一版的**可观测性**落脚点 |

### 364.2 闸门 35 `ui-p4-models`（纯函数）

展示逻辑最容易与内核漂（同一个词表两处认识），所以逐个判别值钉住：

* 篝火**位序**（`Rest 1 | Smith 2 | Recall 4 | Lift 8 | Toke 16 | Dig 32`）六条 + 组合 +
  **未知位必须被报出来**（`unknownCampfireBits`）；
* 效果判别值 5 条 + **未知不被显示成"无"**（`nothing` 是 5，不是 0 —— 拿 0 判"无"会把未知吞掉）；
* 商店：`-1` 已售、价格 == 金币算买得起（边界）、价格 0 仍在卖；
* 删卡服务三种取值；牌组选择器（锻造只收没升级的牌）；药水四种用法 + 战斗外规则。

证据串：`UI_P4_MODELS PASS campfire=6 effects=5 shelves=4 picker=3 potions=4`

### 364.3 闸门 36 `ui-next-p4`（端到端旅程）

**为什么是"旅程"而不是六个独立夹具**：商店/篝火/宝箱的位置由地图生成决定，而生成有硬规则
（`run-layer.md` §7.1）：第 1–5 层**没有**篝火与精英、第 9 层**全是**宝箱、第 15 层全是篝火。
所以"走到这些屏"本身就是被测对象。

闸门从第 1 层往上走，遇到什么测什么，**走两段旅程**覆盖全部屏：

```
seed 3（第 2 层的 `?` 房掷出事件 shining_light）→ 事件 / 宝箱 / 篝火 / 选择器
seed 1（第 2 层有商店）→ 商店（买药水 + 删卡服务）
```

每屏都用**真 DOM 点击**，并断言：

| 断言 | 证据 |
|---|---|
| 商店价格来自内核 | `[81,71,55,…]` 全是 `>0` 或 `-1` |
| 买完金币真的少 | `267 → 186`，日志有"买了…" |
| 删卡：选择器 → 牌组 -1 → 每家店一次 | `12 → 11`，`removalAvailable` 变 0 |
| 篝火休息显示内核回复量并真的回血 | 按钮文案含 `heal` |
| 宝箱打开后出现**战利品横幅** | `data-run-loot` |
| 事件正文/选项条数/可用性 | 不可用选项数量 == 禁用按钮数量 |
| 事件选牌 / 事件候选 / 祝福选牌 | 三处都走选择器 |
| 第 15 层之后能点 **Boss 哨兵** | 走到第 16 层 |
| 药水条：可用性是布尔、扔完 -1 | `1 → 0` |

证据串：`UI_NEXT_P4 PASS floors=14 screens=reward,event,deck-picker,chest,rest,shop,potion,settings`

### 364.4 修掉的五个真 bug

| # | bug | 后果 |
|---|---|---|
| 1 | **Boss 哨兵不在 `map.nodes` 里**（`BOSS_NODE = 100`，第 16 层在地图之外） | 第 15 层站定后地图上**一个可点的格子都没有** ⇒ 软锁。内核其实给了合法动作（`enter_node(100)`） |
| 2 | **`open_chest` 是"打开即结束"**（相位直接归 0） | 按"打开 → 看战利品 → 离开"画的三个状态里，后两个永远到不了（等一个不会来的"离开"按钮） |
| 3 | `refresh()` 用 `this.state.lastLoot` 而不是刚设的字段 | 战利品横幅**永远不出现**（动作里设的值被旧 state 当场抹掉） |
| 4 | 旅程策略"没测过的类型优先" | 只有精英可达时直接撞上去、6 层就死 ⇒ 篝火与事件一次都没走到（空转 83 条 FAIL） |
| 5 | 战斗中不回答**待决选牌** | `Headbutt` 一类牌让动作表变空 ⇒ 被判成 `stuck`（P4 要求里本来就有"待决场景"） |

### 364.5 数字

闸门 34 → **36**；`ui-p4-models` 覆盖 6 位掩码/5 效果/4 货架/3 选择器/4 药水；
`ui-next-p4` 两段旅程、覆盖 8 屏、走到第 14–16 层；units 1233、导出 234、四条对拍不动。

### 364.6 还欠的

* **P5**：Beat 演出（1–13 类动画）、低多边形资产、完整幕内流程；
* `SC-02b`（幕尽头）在**当前内容**下仍不可达（地图走完即 `RunEnd`）—— 闸门 33 用合成夹具覆盖它；
* 事件/祝福/遗物的中文名仍是 id（内容侧没有事件表；用户已明确与美术一起统一处理）；
* 药水在**战斗内**的选目标仍是 P2 的"点敌人"路径（`ui-wasm-choice` 在测），运行层只补了战斗外的用法。
'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + section)

# ── README ─────────────────────────────────────────────────────────────────
edit(
    'README.md',
    '''**聚合验收**：34 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice`、`ui-wasm-fixtures`、`ui-wasm-xcost`、`ui-scene` 与 `ui-next-loop`），一道红就整体红''',
    '''**聚合验收**：36 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice`、`ui-wasm-fixtures`、`ui-wasm-xcost`、`ui-scene`、`ui-next-loop`、`ui-p4-models` 与 `ui-next-p4`），一道红就整体红''',
    'readme gates',
)

# ── 新文档 ─────────────────────────────────────────────────────────────────
doc = '''# P4 场景层：经营 / 事件 / 待决

> 代码在 `web-next/src/run/scenes/` 与 `web-next/src/run/overlays/`，纯逻辑在 `run/models.ts`。
> 场景语义的权威是 `docs/ui-state-model.md`；P3 的路由在 `docs/ui-p3-loop.md`；这一份讲 P4。

## 1. 每一屏的判据（全部来自内核）

| 屏 | 相位 / 事实 | 关键导出 |
|---|---|---|
| 商店 `SC-05` | `pending == 2` | `shop_{card,relic,potion,colorless}_{count,id,price}`、`remove_price`、`removal_available` |
| 篝火 `SC-06` | `pending == 1` | `campfire_options`（位掩码）、`rest_heal`、`girya_lifts` |
| 宝箱 `SC-07` | `pending == 3` | `open_chest`、`leave` |
| 事件 `SC-08` | `pending == 5` | `event_id/text/needs`、`event_option_count/_available/_label/_effect_at` |
| 事件候选 `SC-10` | `pending == 9` | `event_offer_len/_title/_take` |
| 选牌 `SC-01b`/`SC-09` | `pending == 7/8` | `pick_blessing_card` / `pick_event_card` |
| 遗物欠账 `SC-11a/b` | `pickup_picks > 0` / `pickup_add > 0` | `pickup_*` |
| 药水 / 牌堆 / 设置 | 全局 | `potion_*`、`env_pile_*`、运行层状态 |

## 2. 六条交互纪律

1. **价格只显示内核那一份**（`_price` 已算上会员卡/涨价）。页面算价必然与内核漂，而"显示 100
   却收 120"是最难查的那种 bug。
2. **买不起的按钮能点**：点了说"还差多少"。禁用按钮说不出差多少，玩家只能自己算。
3. **不可用的选项画出来但禁用**并说明原因（事件的 `option_available`、锻造的"已升级"）。
   隐藏起来等于骗人：玩家会以为这个事件只有一个选项。
4. **牌组下标就是身份**：列表顺序 == `rd_run_deck_*` 的下标，想帮玩家找牌就加**过滤框**，
   绝不重排（重排之后"第 3 张"是哪个就说不清了）。
5. **欠账关不掉**：遗物要求改/加牌时必须还完。它是**覆盖层**而不是另一屏，所以底下的奖励屏
   不会丢（`rd_run_pickup_*` 不走 `pending`，可以和任何屏同时存在）。
6. **抽牌堆不显示顺序**：按名字排序显示"有什么、几张"。按内核顺序画出来等于给玩家一个外挂。

## 3. 两个"内核语义决定了 UI 形状"的例子

### 3.1 宝箱：打开即结束

`rd_run_open_chest()` 让相位直接归 0，所以"已打开的宝箱"不是一个可停留的屏。
第一版按"打开 → 看战利品 → 离开"画了三个状态，结果后两个永远到不了。
现在：**打开**（战利品由外壳的横幅说，`RunStore.lastLoot`）或**不打开就走**。

### 3.2 Boss：一个不在地图上的哨兵

第 16 层的 Boss **不在地图里**（`inv:§7.2`），它以 `BOSS_NODE = 100` 出现在**动作表**中。
第一版只从 `map.nodes` 里找 Boss（`kind == 7`），于是第 15 层站定后地图上没有一个可点的格子
—— 玩家软锁。现在 `MapScene` 单独问 `bossReachable`，并把那个徽章画成**按钮**。

## 4. 待决选牌（战斗内）

`PendingChoice` 出现时**动作表是空的**，所以：
* `CombatScreen` 弹 `ChoiceModal`（P2 已有）；
* 任何"自动打完一场"的驱动（含闸门）都必须先回答问句，否则会被判成 `stuck`。

## 5. 探针（`window.__run`）

P4 追加：`screens()`（一次读全六屏数据）、`piles()`、`choice()/choicePick/choiceClear/choiceConfirm`，
以及每个动作一份（`buy` / `leave` / `rest` / `smith` / `toke` / `lift` / `dig` / `recall` /
`openChest` / `chooseEvent` / `takeEventOffer` / `pickEventCard` / `pickBlessingCard` /
`pickupPickCard` / `pickupAddCard` / `pickupSkip` / `pickupMaxHp` / `usePotion` / `dropPotion`）。

## 6. 闸门

| 闸门 | 做什么 |
|---|---|
| 35 `ui-p4-models` | 纯函数：位掩码位序、效果判别值、商店定价边界、选择器规则、药水规则 |
| 36 `ui-next-p4` | 两段真实旅程（seed 3 事件 / seed 1 商店），每屏真 DOM 点击，覆盖 8 屏 |
'''
io.open('docs/ui-p4-scenes.md', 'w', encoding='utf-8', newline='\n').write(doc)
print('docs written')
