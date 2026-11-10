# UI ABI 审计（P0 交付物）

> **这份文档是什么**：新 UI 开工前的**契约基线**。它由 `native/ui_abi_dump.mjs` 用**真实
> wasm** 跑出来，回答两个问题：
>
> 1. 新 UI 依赖的每个导出，**实际**是什么行为（长度、哨兵、参数、返回码）？
> 2. 哪些场景能**真实到达**并采到快照，哪些只能靠合成夹具（必须标明）？
>
> **基线**：commit `29500d4` + §349；内容镜像 `0x54af44dd`。
> **产物**：本文 + `native/ui_fixtures/p0-scenes.json`（原始 dump，值就是 wasm 说的，未经解释）。
>
> ⚠️ 这份文档**不是** ABI 冻结声明，也**不是**"新 UI 已就绪"的证明。它只证明"这些字段在
> 这个版本上是这样"。

## 0. 复现

```bash
node native/ui_abi_dump.mjs --check            # 契约断言（闸门 24 跑这一条）
node native/ui_abi_dump.mjs --report           # 重新采集真实场景 dump（改内容后必须重跑）
node native/ui_abi_dump.mjs --check-fixtures   # 盘上的 dump 是否还对得上当前镜像
```

`--check` **与内容无关**（不读具体数值），所以内容扩充不会让它变红；`--report` 的产物
**与内容有关**（商店价目、遭遇 id…），换内容后必须重跑，否则本文引用的数字就过期了。

## 1. 契约断言（机器跑，闸门 24）

| 断言 | 结果 |
|---|---|
| 新 UI 第一层依赖的 **52** 个导出都存在 | ✅ |
| `rd_run_observe_len()` = **19**、`rd_env_observe_len()` = **148**（由模块自己说，不许写死） | ✅ |
| 无局时 `rd_run_observe(19)` = `i32::MIN`（不是 0） | ✅ |
| 无局时 `rd_run_exists()` = 0、`rd_run_seed()` = `i32::MIN`、`rd_run_over()` = -1、`rd_run_rest_heal()` = -1、`removal_available` = -1 | ✅ |
| 没有战斗会话时 `rd_env_active_slot()` = **-3**（查询不创建会话） | ✅ |
| **`i32::MIN` 是合法 seed**：用它开局后 `rd_run_exists()` = 1、`boss_id` 长度 = 0（不是 -1） | ✅ |
| 任何 Boss 战之前 `boss_id` = **空串**（不猜池子第一条） | ✅ |
| 18 条场景的 `resolveScene` / `classifyScene` parity（覆盖层与底屏分开、`SC-??` 带回 `unknownPending`、数组顺序即优先级） | ✅ |

## 2. 真实场景 dump（11 条真实 + 1 条显式合成）

| 场景 | 怎么到达 | 关键原始值 |
|---|---|---|
| `SC-00-no-run` | 不 `rd_run_start` | 三个文本查询都返回 **`null`**（`_len` = -1）；`actions` = 0 |
| `SC-01-blessing` | `rd_run_start(7,0)` | `pending` = 6、`startOfferCount` = 2 |
| `SC-02-map` | 选完祝福 | `pending` = 0、`actions` = 5、`bossId`/`eventId`/`encounterId` 全空 |
| `SC-03-pre-fight` | 走到战斗节点（seed 1） | `kind` = 1、`nodeResolved` = 0、`actions` = 1、`encounterId` = **空**（还没开打） |
| `SC-03b-combat` | `fight_begin`（seed 1） | 战斗向量 148 格：`round 1 / turn 1 / phase 1 / result 0 / hp 80/80 / block 0 / ward -1 / energy 3/3 / hand 5 / enemies 2`；`actions` = 11；`beatCount` = 3；`piles` = `[5,0,0]`；`observe[140..148]` 全 `-1`（保留位） |
| `SC-03b-run-facts` | 战斗中读运行层 | `in_fight` = 1 ⇒ `base = SC-03b`；`encounterId` = `enc_small_slimes` |
| `SC-04-reward` | 打赢后 `fight_end` | `pending` = 4、`reward.gold` > 0、`actions` = 0 |
| `SC-12b-defeat` | **故意输**（只结束回合） | `runOver` = 1、`runOverWhy` = 1 |
| `SC-05-shop` | 走到商店（seed 4） | 四排 `5 / 2 / 3 / 3`、价目 `[46, 95, 52, 249]`、`removePrice` = 75、`removalAvailable` = 1 |
| `SC-07-treasure` | 走到宝箱（seed 1） | `pending` = 3、`kind` = 6 |
| `SC-08-event` | 走到 `?` 房掷出事件（seed 3） | `pending` = 5、`unknownRoom` = **1**、`eventId` = `shining_light`、`event.options` > 0 |
| `SC-11a-pickup-debt` | `rd_run_grant_relic("empty_cage")` | `pickup.picks` = **2** ⇒ `resolveScene` = `{ base: "SC-02", overlays: ["SC-11a"] }`（覆盖层压在底屏上） |
| `SC-12a-act-clear` | **合成**（要打穿一幕的 Boss） | 由 `--check` 的 18 条合成夹具覆盖，本文不假装它被真实到达 |

### 2.1 三个"夹具缺陷伪装成场景不可达"（值得记下来）

写这个 dump 时连踩三次，三次都表现为"这个场景走不到"，而**根因都在驱动脚本**：

1. `fight_begin` 之后**立刻** `fight_end` ⇒ 战斗还没有结果 ⇒ 没有奖励屏、节点不结算 ⇒
   后续每一步 `rd_run_step` 被 `NodeNotSettled` 拒 ⇒ 商店/宝箱/事件"400 个种子都走不到"。
2. **站在战斗节点上 `begin_node` 什么都不做**（战斗靠 `fight_begin`/`fight_end` 结算）⇒
   "站在未结算节点就先 `begin_node`"这个分支**空转 26 跳**。
3. 落到商店那一格后**立刻被 `leave` 掉**（`settleHere` 的 case 2）⇒ 搜索永远"没到达"。

⇒ 一般教训：**"场景不可达"这个结论，必须先排除"驱动脚本走错了"**。这三条都不是内核缺陷。

## 3. 已验证的 ABI 清单（新 UI 可直接依赖）

### 3.1 运行层事实（无参数、返回 i32）

| 导出 | 已验证的行为 |
|---|---|
| `rd_run_exists()` | `1/0`；**唯一**正确的"有没有局"判据 |
| `rd_run_seed()` | 无局 = `i32::MIN`；**`i32::MIN` 也是合法 seed**，所以不能拿它当哨兵 |
| `rd_run_act()` / `rd_run_ascension()` | 幕号 / 难度 |
| `rd_run_pending()` | `0..9`，`-1` = 无局（`Pending` 判别值） |
| `rd_run_node_kind()` | `-1` = 无节点；Boss 已折算成 `7` |
| `rd_run_node_resolved()` | `0/1`；`node < 0` 时是 **0**（不是"已结算"） |
| `rd_run_in_fight()` | `1/0/-1`；**唯一**能区分 SC-03 与 SC-03b 的判据 |
| `rd_run_over()` / `rd_run_over_why()` | `1/0/-1` / `0..3/-1`（`RunEnd` 判别值） |
| `rd_run_boss_beaten()` | `1/0/-1` |
| `rd_run_rest_heal()` | 含 `regal_pillow` 与 `eternal_feather`；`-1` = 无局 |
| `rd_run_removal_available()` | `1/0/-1`（每店一次） |
| `rd_run_start_offer_count()` | 祝福槽数（当前 2） |
| `rd_run_campfire_options()` | 位掩码 `0..63` |
| `rd_run_girya_lifts()` / `rd_run_wing_boots()` / `rd_run_remove_price()` | 计数 / 价格 |
| `rd_run_pickup_picks()` / `rd_run_pickup_add()` | 遗物欠账（`>0` 即覆盖层） |
| `rd_run_event_fight()` | `0/1/2`（事件引来的伏击档位） |
| `rd_run_action_count()` / `rd_run_action(i)` / `rd_run_action_arg(i,0)` | 运行层动作表；`arg0` = 目标节点**全局下标** |
| `rd_run_map_len()` / `rd_run_map_rows()` / `rd_run_map_node(i, field)` | 地图；`field 2` = kind、`field 7` = 可达 |
| `rd_run_observe(i)` | 19 格；越界 = `i32::MIN` |

### 3.2 运行层文本（`_len` / `_into` 成对）

| 导出 | 已验证的行为 |
|---|---|
| `rd_run_boss_id_len/into` | 无局 = `-1`；**有局但 Boss 未定 = `0`（空串）**；已定 = 长度。§349 的三种时间语义 |
| `rd_run_event_id_len/into` | 无事件 = 空串（不是 `-1`）；实测 `shining_light` |
| `rd_run_encounter_id_len/into` | 没打过 = 空串；打过后保留（实测 `enc_small_slimes`） |
| `rd_run_event_text_len/into`、`event_label_*`、`event_offer_*` | 事件文本 / 按钮 / 候选 |

### 3.3 战斗层

| 导出 | 已验证的行为 |
|---|---|
| `rd_env_observe_len()` / `_buf()` / `_into(ptr)` | **148**；`_buf` 返回 `Int32Array` 的地址（必须 `slice()` 复制，`memory.grow` 会让 View 失效） |
| `rd_env_action_count()` / `_kind(i)` / `_arg(i, which)` | 每张牌 × 每个活敌人一条；`arg1 = -1` 表示无目标 |
| `rd_env_step(i)` | `0` 接受 / `-1` 拒绝且观察向量逐字节不变 / `-2` 已结束 / `-3` 驱动坏了 |
| `rd_env_beat_count()` / `_field(i, f)` / `_beats_dropped()` | 本步 beat 数 / 8 个字段 / 丢了几条（`0` 是唯一好答案） |
| `rd_env_choice_pending()` / `_source` / `_kind` / `_min` / `_max` / `_count` / `_pick` / `_selected` / `_clear` / `_confirm` / `_copies` | 战斗内待决选牌（⚠️ 本轮**没有**真实快照，见 §4） |
| `rd_env_active_slot()` | `-1` 英雄 / `0..5` 敌人 / `-2` 没人 / **`-3` 没有会话** |
| `rd_env_done()` / `rd_env_result()` | ⚠️ `done` 在**没有会话**时返回 **1**（"结束了"），不能反过来说"有没有战斗" |
| `rd_env_pile_len(zone)` | `0/1/2` = 抽/弃/耗；`3` = 问句来源牌区 |

### 3.4 内容

| 导出 | 已验证的行为 |
|---|---|
| `rd_content_fingerprint()` | 8 位十六进制；本轮 `0x54af44dd` |
| `rd_env_enemy_name_*` | ⚠️ 返回**敌人定义 id**（`acid_slime_m`），**不是**本地化文本 ⇒ 可直接作资源键 |
| `rd_env_card_name_*` | ⚠️ 返回 **card definition id** ⇒ 可直接作资源键；`card_title_*` 才是 `NameKey` |

## 4. 未验证 / 确实缺失（诚实清单）

| 项 | 状态 | 影响 |
|---|---|---|
| `SC-12a`（幕通关）真实快照 | **未采集**（要打穿一幕的 Boss） | 只有合成夹具；UI 需按类型实现，不假装主路径覆盖 |
| A20 双 Boss 的三个时间窗口 | **只有单元测试**（`boss_enemy_id` 直接给参数），没有真实流程快照 | UI 的"第二只未定 ⇒ `null`"按单元测试实现 |
| `rd_env_choice_*`（战斗内待决选牌） | **没有真实快照**（要触发药水/卡牌问句） | P2 接真 wasm 时必须补一条夹具 |
| `beats_dropped > 0` 的降级 | **未验证**（容量 64 很难打满） | 按 `diffObservations` 兜底实现 |
| Beat kind 1–13 全量 | 只实测到 3 条（首回合：TurnStarted / StatusChanged / CardPlayed） | 其余按 `ui-state-model` §4 的表格实现，P5 补 |
| `rd_run_script_*` / `rd_run_archive_*` | **未纳入 P0** | 存档/回放 UI 属于 P4+ |
| **稳定卡牌实例 id**（跨动作） | **确实缺失** | 跨区动画无法追踪"同一张牌"；首期按 `handSlot + revision` 处理（计划 §13 已列） |
| `SC-02b`（幕尽头） | 当前内容**几乎不可达** | 保留类型 + 合成夹具，不伪造 |
| 敌人**显示名** | 只有 id | 显示层用 `displayName()`（§0.5），不是 ABI 缺口 |

## 5. 与 `docs/ui-state-model.md` 的核对结果

| 文档说法 | 实测 |
|---|---|
| `R.obs(18)` = `unknown_room` | ✅ 事件屏实测 `1` |
| `E.obs(7)` = ward 恒 `-1` | ✅ |
| `E.obs(140..147)` 保留 | ✅ 全 `-1` |
| `E.obs(9)` = `energyMax` = 回合补给 3 | ✅ |
| 商店四排 `5/2/3/3` | ✅ |
| 删卡价 75 起 | ✅ |
| 事件 `pending 5` + `unknownRoom 1` | ✅ |
| `rd_run_node_resolved()` 在 `node < 0` 时是 0 | ✅（文档未明说，**本轮补记**） |

**本轮新发现的文档空白**（已写进本文，暂不改 `ui-state-model`，避免与 P0 混在一起）：
`rd_run_node_resolved()` 在"还没出发"时返回 **0**，而 `resolveScene` 的 `mapExhausted(s)` 要求
`kind >= 0` 才看它 —— 所以这个 0 **不会**误判成"幕尽"。这条值得在 `ui-state-model` §3.1 补一句。

## 6. 对计划 v1.1 的两条事实更正（复核时提出，此处复述）

1. **`rd_env_enemy_name_*` 返回的是定义 id**，不是本地化文本 ⇒ 计划 §1.3 的"候选接口缺口"
   不成立，AssetRegistry 零新增 ABI。
2. **`rd_env_card_name_*` 返回的是 card definition id** ⇒ 计划 §4 的 `definitionId?`
   （"仅在有可信来源时填充"）可以直接填。
