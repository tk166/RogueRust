# P4 场景层：经营 / 事件 / 待决

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
