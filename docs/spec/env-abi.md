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

