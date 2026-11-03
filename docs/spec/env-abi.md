# 环境 ABI（冻结 v1）—— 给 RL 训练用的交互式接口

> 状态：**冻结**。实现方（NativeAOT 侧）与使用方（Python gymnasium 包装）都照本文档写，改则升版本。

## 1. 为什么需要它

现有 oracle ABI 只有 `rd_oracle_run` / `rd_oracle_run_ex`：**它们跑的是固定脚本**（由 `variant` 选形状），
训练环境需要的是**逐决策交互**——观察当前状态、枚举合法动作、施加一个动作、看结果。
用固定脚本做不了 RL（那退化成一个 bandit）。所以需要一组新的、面向 step 的导出。

## 2. 设计约束

1. **全部可 blittable**：`int` 进、`int` 出；字符串一律走 `_len`/`_char` 对。
2. **句柄式**：一个进程里要能同时存在多个环境实例（向量化），所以不能有"当前环境"这种全局状态。
3. **固定尺寸观察**：观察向量是定长整数数组，由 `rd_env_observe_len()` 公布长度，
   调用方不得写死。编码约定见 §4。
4. **确定性**：同 `(config, seed)` + 同动作序列 ⇒ 观察流逐字节相同。这是硬要求，必须有自检导出。
5. **不抛异常穿越边界**：错误用返回码表达，另配 `rd_env_last_error_*` 取人类可读原因。

## 3. 导出签名（v1）

```c
/* 生命周期 */
int  rd_env_create(int config, int seed);          /* 返回 handle >= 0；失败返回负值 */
void rd_env_destroy(int handle);
int  rd_env_reset(int handle);                     /* 复用到同一 seed 的初始状态，返回 0 */

/* 观察 */
int  rd_env_observe_len(void);                     /* 定长观察向量的长度（全局常量） */
int  rd_env_observe(int handle, int index);        /* 越界返回 INT_MIN */
int  rd_env_done(int handle);                      /* 0 进行中 / 1 结束 */
int  rd_env_result(int handle);                    /* 0 未定 / 1 胜 / 2 负（与 CombatResult 对齐） */

/* 动作 */
int  rd_env_action_count(int handle);              /* 当前合法动作数 */
int  rd_env_action_kind(int handle, int i);        /* 见 §5 */
int  rd_env_action_arg(int handle, int i, int which);  /* which: 0 或 1 */
int  rd_env_step(int handle, int action_index);    /* 0 接受；负值=拒绝（状态不变） */

/* 奖励（由环境算，避免包装层各自造轮子） */
int  rd_env_reward(int handle);                    /* 本步奖励，可为负；单位=厘（1/1000）以免用浮点 */

/* 诊断 */
int  rd_env_last_error_len(void);
int  rd_env_last_error_char(int i);
int  rd_env_selfcheck(int config, int seed, int steps);  /* 内部跑两步同种子并比观察流；一致返回 1 */
```

## 4. 观察向量编码（定长，v1）

**上限**：敌人 ≤ 4、手牌 ≤ 10、状态轴 5（str/vuln/weak/dex/frail）、牌堆计数 5（draw/hand/discard/exhaust/queue）。
`observe_len` 由这些上限推出，实现方公布实际值。

| 区段 | 长度 | 含义 |
|---|---:|---|
| 头部 | 12 | `round, turn, phase, result, hero_hp, hero_hp_max, hero_block, hero_ward, energy, energy_max, hand_count, enemy_count` |
| 英雄状态 | 5 | 5 个状态轴的层数 |
| 每个敌人 ×4 | 8 | `alive, hp, hp_max, block, ward, intent_kind, intent_damage, status_slots_used` |
| 每个敌人 ×4 的状态 | 5 | 5 个状态轴的层数 |
| 手牌 ×10 | 4 | `occupied, cost, def_slot, upgraded`（`def_slot` 是卡定义的**稳定小整数**句柄，见 §6） |
| 牌堆计数 | 5 | `draw, hand, discard, exhaust, queue` |
| 保留 | 8 | 置 0，留作版本演进 |

**未占用的槽位一律填 `-1`（"没有"）而不是 0** —— 0 是一个真实取值（比如 0 层状态、0 点格挡），
用它表示"不存在"会让包装层分不清"没有这张牌"和"这张牌 0 费"。

## 5. 动作编码

| `kind` | 含义 | `arg0` | `arg1` |
|---|---|---|---|
| 0 | 打出手牌 | 手牌下标 | 目标敌人下标（无目标填 -1） |
| 1 | 结束回合 | -1 | -1 |
| 2 | 使用英雄自身动作 | 动作下标 | 目标敌人下标 |
| 3+ | 保留 | | |

`rd_env_step` 返回 `0` = 接受；`-1` = 非法动作（**状态必须保持不变**）；`-2` = 环境已结束；`-3` 其它。
**"拒绝时状态不变"必须为真**，否则 RL 的 transition 就不成立了。

## 6. 卡定义句柄（`def_slot`）

观察里不能塞字符串。所以要一张**稳定的小整数 → 卡定义**映射：
同一份内容镜像编译出来的 `def_slot` 必须恒定（可由内容编译器按 id 排序后分配，写进镜像的 `IDX` 段）。
另配导出（本版可选）：

```c
int rd_env_card_def_slot(int handle, int card_def_index);  /* 索引 -> slot，越界返回 -1 */
int rd_env_card_def_count(void);
int rd_env_card_def_name_len(int slot); int rd_env_card_def_name_char(int i);
```

## 7. 奖励定义（v1，**允许改，但必须记录**）

一步奖励（单位 1/1000）：

```
reward = 1000 * (敌人总生命损失) - 1000 * (英雄生命损失) - 10 * (本步浪费的能量)
```

意图是"能学"而不是"学得好"；真正的 shaping 属于训练侧。**任何改动都必须同步改本文档与语料**。

## 8. 验收（实现方必须自己跑通并在报告里贴输出）

1. `rd_env_selfcheck(config, seed, steps)` 对若干 `(config, seed)` 返回 `1`（同种子同动作流 ⇒ 同观察流）。
2. 一个 demo 策略（随机 / 总打第一张牌）跑完整局，`rd_env_done()` 最终为 1，无崩溃、无越界。
3. **拒绝动作不改变状态**：对每个 `-1` 返回，前后两次观察必须逐项相等 —— 直接断言。
4. `rd_env_create` 在同一进程里开 **≥16 个** 互不影响的句柄，交错 step，结果与单独跑一致。
5. `dnaot.ps1` 构建 0 error、0 个 IL2xxx/IL3xxx。

## 9. 使用方（Python 侧）的约定

- `py/roguedeck_env/` 提供 gymnasium 形状的 `RogueDeckEnv`（`reset()`/`step()`/合法动作掩码）。
- 向量化优先用**多进程**（每个进程持有若干句柄），而不是线程 —— 环境本身是确定性的，
  多进程还能绕开任何潜在的全局状态。
- 观察**不要**在 Python 侧二次编码成给神经网络的张量：那是训练侧的职责，本包装只保证
  "观察向量 → numpy/列表"这一步忠实、可复现。

## 10. 实现补充（v1 实现方记录 —— **不改契约**，只是把 §4/§5/§7 里含糊的地方钉死）

- **config 清单**（`rd_env_create(config, seed)`；`native/env_check.py` 会打印同一张表）：

  | config | 场景 | 英雄 | 敌人 | 牌组 / 敌人伤害 |
  |---|---|---|---|---|
  | 0 | duel（最小可收敛） | 30/30，能量 3 | 1×12hp | 5×strike(1费6伤) / 5 |
  | 1 | elite2 | 50/50 | 2×14hp | +3×defend(1费5格挡) +1×heavy(2费12伤) / 6 |
  | 2 | statuses | 40/40，起手 Strength 2 | 2×16hp，起手 Vulnerable 2 | +focus(1费+2力量) / 7 |
  | 3 | swarm4（敌人上限 4） | 60/60 | 4×10hp | +cleave(2费，对所有敌人各 4 伤) / 4 |
  | 4 | action（英雄动作） | 30/30 | 1×24hp | 4×strike + 2×defend，另有动作 blast(2费9伤) / 6 |
  | 5 | endurance（长局） | 80/80 | 3×20hp | 10 张：strike/defend/heavy/recover(1费回4血)/jab(0费3伤) / 5 |
  | 6 | locked | 30/30 | 1×12hp | 3×strike + 3×locked(`PlayCondition` 恒假) / 5 |
  | 7 | costfloor | 30/30，起手戴「卡牌最低费用=1」法令 | 1×40hp | 2×strike + 1×heavy + 3×jab(印刷 0 费) / 1 |

- **§7 里「本步浪费的能量」的取值**：该步是"结束回合"时 = 英雄**剩余**的能量；出牌/用动作的步 = 0。
  （公式与单位不变，只是把这一项钉死，避免包装层各算各的。）
- **§5 动作表的展开方式**：kind 0 的攻击牌对每个**存活敌人槽位**各给一个动作，`arg1` 是**观察里的
  敌人槽位下标**（敌人死了也不挪位，`alive` 字段为 0）；非攻击牌 `arg1 = -1`；kind 1 只在英雄回合出现；
  kind 2 = 每个可用英雄动作 × 存活敌人槽位。
- **§5「拒绝」的判据**：`-1` 当且仅当**该步之后观察逐项未变**（而不是"引擎报没报 problem"）——
  所以"零副作用"是**构造上的保证**，不是承诺；被拒时 `rd_env_reward` 归零。这样即使引擎静默 no-op
  （实测确实会：`InteractiveCombat.CanPlay` **不查能量**，付不起的牌会静默无操作），也不会出现
  "返回 -1 却已经前进"的状态。
- **动作枚举的健全性（实测）**：`CanPlay` 会查 `PlayCondition`（config 6 的 locked 牌因此**进不了**
  动作表），但**不查能量、也不查法令抬高的费用** —— 所以实现方自己补了能量/费用门控；
  config 7（0 费 jab + 最低费用 1 法令）专门用来构造"**在范围内、引擎却会拒**"的动作，
  供 §8.3 第二类验收使用。
- **终止判定**：`done = 1` 当且仅当战斗已判出胜负 **或** 英雄已倒下。后者必须单列：英雄倒地而场上
  还有活着的友方单位时 `CombatResult` 仍是 `Ongoing`，此时既无可打之牌也不是英雄回合，动作表会空掉。


---

## 11. run 层导出（v1 追加，2026-10-19）—— 与 §3 那套**并列**，不是它的扩展

> **为什么单列一套**：§3 的 `rd_env_*` 是"一场战斗"的环境（RL 用途，一个 `CombatState`）。
> run 层是"一局"（地图 + 游标 + 牌组 + 金币），寿命、状态与消费方都不同
> （`docs/spec/run-layer.md` §4.1 说明了为什么不塞进 `CombatState`）。
> 两套共用"定长整数观察 + 动作表 + `-1` 表示缺失"的约定，但**互不调用**。

### 11.1 签名

```c
/* 一局 */
int rd_run_start(int seed);        /* 建一局：生成地图；游标在出发前（node = -1）；返回 0 */
int rd_run_seed(void);             /* 当前一局的 seed（供 UI 显示与复现） */

/* 地图：定长，节点按 (row, col) 升序编号 */
int rd_run_map_len(void);          /* 节点总数（= 所有 present 节点） */
int rd_run_map_rows(void);         /* 行数 */
int rd_run_map_node(int index, int field);   /* 越界返回 INT_MIN；field 见 11.2 */
int rd_run_map_row_first(int row); /* 该行第一个节点的全局下标；空行返回 -1 */

/* 一局的观察 */
int rd_run_observe_len(void);
int rd_run_observe(int index);     /* 见 11.3；越界返回 INT_MIN */

/* 动作 */
int rd_run_action_count(void);
int rd_run_action(int index);      /* kind，见 11.4；越界返回 -1 */
int rd_run_action_arg(int index, int which);   /* which ∈ {0,1}；越界返回 -1 */
int rd_run_step(int action_index); /* 0 接受；负值拒绝且**状态逐字节不变** */
```

### 11.2 `rd_run_map_node(index, field)`

| field | 含义 |
|---:|---|
| 0 | `row`（0 基；floor = row + 1） |
| 1 | `col` |
| 2 | `kind`（与 `rd_run::map::NodeKind` 的判别值一致；**0 = Unassigned**，见 `run-layer.md` §7.2） |
| 3 | `out_degree`（0..3；最后一行恒 0） |
| 4 | 第 1 条出边的**全局节点下标**（没有则 `-1`） |
| 5 | 第 2 条出边 |
| 6 | 第 3 条出边 |
| 7 | `reachable`：从**当前游标**这一步能不能进入它（1/0）。游标未出发（node = -1）时，floor 1 的节点全部可达 |

**出边给的是全局下标，不是行内下标。** 原因：行内下标要求使用方自己维护每行偏移，
那是把一个容易算错的映射推给每个消费者（`run-layer.md` §4.3 的存储用行内下标，
是因为内核自己会重编号；对外的接口不该泄露这个选择）。

### 11.3 `rd_run_observe(index)`

| index | 含义 |
|---:|---|
| 0 | `floor`（1..=15 在地图上；0 = 还没出发） |
| 1 | 当前节点的全局下标，`-1` = 还没出发 |
| 2 | `health` |
| 3 | `health_max` |
| 4 | `gold` |
| 5 | `deck_size` |
| 6 | `relic_count` |
| 7 | `potion_count` |
| 8 | `map_len` |
| 9..15 | 七条 RNG 流的计数器，**按 stream id 1..=7 升序**（`run-layer.md` §3.2） |
| 16 | `reachable_count`（本步可进入的节点数） |
| 17 | `removed_cards` |
| 18 | 保留（置 0） |

### 11.4 动作

| kind | 含义 | arg0 | arg1 |
|---:|---|---:|---|
| 0 | 进入节点 | 目标节点的**全局下标** | `-1` |

M1 的路径选择只有一个动作族（"沿哪条出边走"）；`run-layer.md` §6.1 里
`ChooseCard`/`RestSite`/`OpenChest`/`TakeBossRelic` 的动作编码在它们各自落地时**追加**
（kind 从 1 起，与 §5 的 kind 0/1/2 不冲突，因为两套 ABI 各自编号）。

### 11.5 这一版的**能力边界**（必须写清，否则就是静默降级）

这一版实现的是**游标在地图上走**：`rd_run_step` 校验"这条出边真的属于当前节点"、
把游标移过去、`floor` 跟着走。它**不结算节点**：

* 普通战斗、篝火、宝箱、`?` 房**都还没有结算逻辑**（`run-layer.md` §6 的 `RunAction` 全表）；
* 也就是说 `rd_run_step` 的语义是"**走到**那个节点"，不是"**结算**那个节点"。
  消费方（UI）必须把这一点显示出来 —— 判据：地图页上每个已走过的节点都要能看出
  "这一步只走了、没结算"（`ui-plan.md` §6 U1 的验收串里有一条 `M1` 的降级标记）。

⇒ 这一节在节点结算落地后**必须回来改**，写明哪些 kind 会真的结算、哪些仍然只走。
把"只走不结算"写在这里而不是留给读者猜，是纪律第 12 条的用法。

**落地实况（2026-10-19）**：`web/map.html` 就是这一节的消费者 —— 它用
`rd_run_map_node` 画出一张 SVG（每节点一个圆、每条边一条 path），用
`rd_run_action_arg(0)` 决定哪些节点可点，点一下就是一次 `rd_run_step`。
判据是闸门 16 `web-map`（`node web/map_test.mjs` ⇒ `MAP_RENDER PASS`），它把
`web/map_render.js` 的纯函数与真 `.wasm` **逐节点、逐边**对账，并且**走完整张地图的每一步
都重新对账**（不是只在开局对一次）—— 第一版只对了一次，于是"可达集合改成前 N 个节点"与
"游标永不标记"两个变异都溜过去了。

⚠️ 页面**不画**"这一步只走了、没结算"的标记。§11.5 要求它可观察，而当前地图页只在
`msg` 行里写角色状态，没有逐节点的"已走 / 已结算"区分。**这是一个已知的欠账**，
写在这里以免"看得见地图"被当成"节点结算做了"。
## 12. 诊断导出（2026-11-03 追加，v1 契约的**纯增量**）

§3 那套是"可玩"所需的；这一组是"卡住时能说清为什么"所需的。它们都不改观察向量的布局，
也不参与指纹。

| 导出 | 返回 | 用途 |
|---|---|---|
| `rd_env_step_code(index)` | 第 `index` 步的 `Deck`/`Play` 拒绝码（`0` = 没有，`-1` = 越界/无会话） | `StepThrew(Script)` 只说了家族；这个说**哪一条**拒因（`Refused(Unplayable)` / `Unaffordable` / `CardNotInHand` / …） |
| `rd_env_code_name_len(code)` / `rd_env_code_name_into(code, ptr)` | 码的**名字**（内核里只有一份表） | 页面把数字印成人话 |
| `rd_env_host_failure_len()` / `rd_env_host_failure_into(ptr)` | 宿主**上一次失败的原始文本**（`0` = 没有） | `TurnError::Host` 只带五个家族；细节一直在 `Host::last_failure()`，**在此之前没有任何导出读它**。实测它就写着 `Exec(Capacity(Full(Combatants)))` |

它们抓到过的第一个真凶：Boss 分裂在同一回合多次触发、战斗员容器溢出（§177 → §178）。
`?debug` 侧另有 `dropPotions()`（空腰带）与 `givePotion(id)`，理由与 `startWithSeed` 相同：
一个必须"祈祷掉落抽到某一瓶"的检查器不是检查器（§185）。


