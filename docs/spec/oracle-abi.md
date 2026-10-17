# Oracle ABI —— `native/RogueDeck.Oracle` 的 C ABI（含 W0 规格书对拍结论）

工程 `native/RogueDeck.Oracle/RogueDeck.Oracle.csproj`（NativeAOT，`NativeLib=Shared`），产物
`bin/x64/Release/net10.0/win-x64/publish/RogueDeck.Oracle.dll`（5.3 MB）。构建：
`powershell -NoProfile -ExecutionPolicy Bypass -File tools\dnaot.ps1 publish native/RogueDeck.Oracle/RogueDeck.Oracle.csproj -c Release -r win-x64`。
状态：**0 error / 0 个 IL2xxx、IL3xxx 警告**（只剩 NuGet 的 NU1902 安全通告，与 AOT 无关）。

源码按机制拆成 partial（类名 `OracleExports`）：`OracleExports.cs`（原有 ABI，golden_v1 靠它）、
`.Random.cs`（洗牌）、`.Extended.cs`（宽跑器 + 扩展观测）、`.Probes.cs`（一向量一探针）、
`.PreDown.cs`（自带的死亡前拦截器）、`.Env.cs`（交互式环境 ABI，契约在 `docs/spec/env-abi.md`）、
`HashCanonicalText.cs`（规范文本副本）。约定：全 `int` 进 `int` 出，字符串一律 `_len()` / `_char(i)`
逐字符读回；失败返回 `-1`，错误文本在 `rd_oracle_error_*` / `rd_env_last_error_*`。

## 1. 原有 ABI（**未改动**；golden_v1 的 128 条与冻结基线逐字节一致）

`rd_oracle_run(hero_hp, card_damage, enemy_hp, enemy_damage, seed, variant) -> hash_len`
—— 「英雄一张 strike vs 一只 ogre」的战斗，按 variant 0..7 跑脚本；`variant>=4` 打开洗牌/能量补充/
12 张牌组以消耗随机数。配套 `rd_oracle_hash_len/char`（`CombatStateHasher` 的小写 hex）、
`rd_oracle_steps/problems/hero_hp/enemy_hp/round/turn/random_step/pending/log_count`、
`rd_oracle_error_len/char`。⚠ **`problems` 是 0/1 标志，不是计数**。
## 2. 规范文本（新增，Rust 侧字节级对拍用）

`rd_oracle_hash_input_len() / rd_oracle_hash_input_char(i)` = `CombatStateHasher` 真正喂给 SHA-256
的那段文本，逐字符可读（换行 `'\n'`，**原样导出不做归一化**）。`rd_oracle_hash_input_ok()` = **自检**：
`HashCanonicalText.cs` 是 `src/RogueDeck.Core/Combat/CombatStateHasher.cs:26-164` 的逐行副本，该标志
= 用副本算出的 SHA-256 与引擎自己的哈希一致；副本漂移会变成 0，而不是悄悄给出对不上的文本。
基线样本 `rd_oracle_run(30, 6, 12, 5, seed=1, variant=0)` → **375 字符**，
SHA-256 `f3298ef47264667185933a987ddd4c7cd42e096f60bacdc3b5e5fbc4d1a02a85`
（全文用 `native/hash_input_dump.py` 一条命令导出，含尾部 `\n`）。

## 3. RNG 洗牌（新增）

`rd_oracle_shuffle(count, seed, step, i)` = `CombatRandom.CreateShuffledIndexes(count, seed, step)[i]`
（越界/异常 → `-1`）；`rd_oracle_shuffle_text(count, seed, step) -> len` +
`rd_oracle_shuffle_text_char(i)` 给整条序列 `"1,0,4,2,3"`；`rd_oracle_probe_shuffle_pile(deck_size, seed)`
是**端到端对拍**：牌组 `c0..cN-1` + `ShuffleDrawPileOnStart`，跑**空脚本**（回合一次都没开始），读回
抽牌堆顺序。⚠ **必须跑完整趟 Fisher–Yates**：`rd_oracle_shuffle` 永远调用引擎的
`CreateShuffledIndexes`（内部走完整循环）再取第 i 项；"只取第 0 个就 break" 会得到不同的序列。
实测 `n=5,seed=12345` → `1,0,4,2,3`；`seed=7` → `3,4,1,2,0`；`n=10,seed=42,step=1` → `6,0,7,9,3,1,5,2,4,8`。
`probe_shuffle_pile` 读回的抽牌堆顺序与 `rd_oracle_shuffle(n, seed, 0, ·)` **逐位相同**
（5/12345、5/7、8/42），且 `random_step == 1`。`ReorderDrawPile(order)` 的语义是
`new[i] = old[order[i]]`；**弃牌堆重洗**（`probe_reshuffle`）用同一个序列函数，同样把 step 加一。

## 4. 宽跑器 `rd_oracle_run_ex`（新增，27 个 int，顺序即签名）

```
rd_oracle_run_ex(hero_hp, card_damage, card_hits, card_damage_target, card_kind, card_block, card_block_target,
  card_ward, card_cost, queue_on_play, enemy_hp, enemy_damage, enemy_count, hero_strength, hero_vulnerable,
  hero_weak, hero_dexterity, hero_frail, enemy_strength, enemy_vulnerable, enemy_weak, enemy_dexterity,
  enemy_frail, draw_per_turn, deck_size, seed, variant)
```

Python 侧形参名表在 `make_corpus.py` 的 `RUN_EX_ARGS`，**改一边必须改两边**。
`card_kind`：0 Direct｜1 DamageOverTime｜2 Direct+IgnoresBlock（引擎里的"真伤"）｜3 DoT+IgnoresBlock。
`*_target`：0 = 英雄（卡的 source），1 = 事件目标（敌人）。`card_hits` = 卡里有几个 `DealDamageNode`
（每个都独立走修饰管线 = 多段伤害）。卡的程序固定为
`Sequence([ward 池增减], [GainBlock], [DealDamage × hits])` —— 顺序即语义：Sequence 子节点按序
**入队**、队列 FIFO 排空，所以格挡/池在伤害结算时已经就位。状态用 `StartingStatuses` 施加（走真实
`ApplyStatus` 管线）：strength/dexterity 无持续时间，vulnerable/weak/frail 带 `DurationTurns=2`。
自定义池 `oracle.ward` 恒以 `AbsorbPriority=10` 注册（排在 Block 之后）。
`variant` = 脚本形状：0 只出牌｜1 出牌→结束回合→敌人出手｜2 出牌→结束回合→走完一轮｜3 连出两张→
结束回合｜4 出牌→一轮→再出牌｜5 只结束回合（对照）｜6 出牌→结束回合（队列窗口）｜7 只做回合/轮次记账。

扩展观测（`run_ex` 与各探针共用）：`hero_block/enemy_block/hero_ward/enemy_ward/energy/energy_max/
hand_count/draw_count/discard_count/exhaust_count/queue_count/enemy_count/enemy_hp_at(i)/
enemy_block_at(i)/phase/result/played/hero_stacks(axis)/enemy_stacks(axis)`（`axis`：0 strength、
1 vulnerable、2 weak、3 dexterity、4 frail）。`rd_oracle_text_len/char` = 一段 `k=v;k=v` 明细：
`active/result/phase/hand/draw/disc/queue/heroStatuses/enemies/party/problems/log=`；**log 放最后**，
条目用 `\n` 分隔、`类型@消息`，消息里带数额与池名（顺序类向量靠它判定）；`party=` 是玩家队里英雄
以外的成员，格式同 `enemies=`。`played`：1 成功、0 = runner 报了 "was not played"、-1 = 没出牌。
## 5. 探针（新增，一向量一个入口）

`probe_expr(op,a,b,c)`（0 Abs／1 Divide／2 Remainder／3 Clamp／4 Add；c=1 走 `DivideByZeroPolicy.Fault`）、
`probe_conditional(cond,then,else)`（else<0 = 无 else 分支）、`probe_repeat(count,maxCount,damage)`、
`probe_program_steps(shape,maxProgramSteps)`、`probe_for_each(poison0..2,hp0..2,seed)`、
`probe_decree(rule,amount,startEnergy,maxEnergy,drawPerTurn,deckSize,cardCost,enemyHp,seed,variant)`
（rule 0 不戴法令／1 UnspentResourceCarries／2 MaxHandSize；variant 2 = 出一张牌开启回合但不结束）、
`probe_reshuffle(deckSize,drawPerTurn,seed)`、`probe_trigger_order(pZzz,pAaa,pMmm,seed)`（格挡量当身份：
zzz=1、aaa=100、mmm=10000）、`probe_snapshot(seed)`、`probe_intercept(kind,seed)`、
`probe_pre_down(kind,hits,seed)`（0 Phoenix / 1 Martyr）、`probe_turn(heroHp,enemyHp,block,damage,seed,variant)`
（**最小注册表**，直驱 `CombatTurnProcessor`）。`rd_oracle_probe_ok()` = 探针自己的不变量。
## 6. 规格书 §7 对拍结论（`corpus/spec_vectors_v1.jsonl`，75 条子向量）

`一致 48 / 带口径说明的一致 12 / 不一致 1 / 无法表达 14`。

* **不一致 1 条**：`cst-V11c`「能量不足 ⇒ 拒绝」—— 本 ABI 把英雄能量写死 3/3，摆不出前置条件，实测是
  **成功出牌**（12→7）。这是 ABI 表达力缺口，不是引擎问题（jsonl 的 `reason` 里写了怎么补）。
* **带口径说明 12 条**：数值一致但口径不同。最值得记的三条：`cst-V14`（规格书 `Hand.Count==3`，
  探针必须出一张牌才能开局 ⇒ 手牌 2、**实抽 3** 与抽牌堆 7 都一致）；`cst-V12b`（见下）；
  `modp-08b`（**0 充能的状态实例不会被自动移除** —— 见 §7）。
* **规格书唯一读错的地方**：`combat-state-and-turn.md` §7 V12 的「`EndTurn` 后 `Queue` 空」。引擎的
  解析窗口是**拥有者下一次回合开始**，单独一次 `HeroEndsTurn`（只结束英雄回合）不足以排空，必须走完
  一整轮；`cst-V12c` 是这条反差的有意留证（实测 enemy_hp=200、queue_count=1）。
* **14 条无法表达**的原因都在 jsonl 的 `reason` 里，三类为主：① 需要注册**自定义 handler / 触发器
  过滤器**并读取它们内部的计数；② 需要测试专用的副作用节点（`SideEffectNode` / `LambdaExpression`）
  来观察"没被求值"这类断言；③ 断言对象在引擎内部（`ProgramStepCount`、`MaxActiveScopes`、
  `CurrentEffectChain`、过滤器计数）。`pre_down_intercept` **不在这 14 条里**：Core 没有公开的
  `IPreDownInterceptor` 实现（唯一那个在 Sandbox 且是 internal），但接口公开，所以 oracle 自己写了
  两个约 15 行的实现（`modp-08a/08b/09`）。`cst-V10b`（JSON 存档）的异常见 §7。

## 7. 已知限制（实现里踩到、移植方必须知道的）

* **JSON 存档路径在 AOT 下不可用**：`CombatSaveJson` 用的是 System.Text.Json 的**反射重载** ——
  编译期冒 IL2026/IL3050（破坏"0 个 IL 警告"的验收线），实测运行时也直接抛
  `Reflection-based serialization has been disabled for this application.`。所以存档格式**没有覆盖**，
  W1 的 Rust 侧要自己定义（这也是 `cst-V10b` 记 not_expressible 的原因）。
* **`CanPlay` / `CanUse` 都不查能量**：会放行付不起的牌/动作，随后由出牌请求**静默 no-op**（牌还在
  手里、能量不变、没有伤害）。环境 ABI 因此自己补了能量/费用门控，并把"拒绝"的判据改成**观察有没有
  变**。**同步改状态也不触发引擎清理**：拦截器直接改充能后，0 充能的状态实例不会被自动移除
  （"掉到 0 就移除"只发生在引擎自己的扣充能路径上，见 `modp-08b`）。

## 8. 覆盖清单（`corpus/coverage.json`）

**19 个机制全部有真正跑起来它的用例**（`native/coverage_check.py` 门禁 **19/19、退出码 0**）。
两条需要说明：`pre_down_intercept` = `modp-08a/08b/09` + oracle 自带的拦截器实现；`decree_round`
覆盖的是**轮次边界本身**（`cst-V2` 回绕 Round 1→2 且 Turn 回到 1，`cst-V13c` 带法令走完整轮），
因为引擎的 `CombatRule` 枚举里没有轮次级法令（只有回合级的 MaxCardsPerTurn / MaxHandSize /
UnspentResourceCarries 等）—— `coverage.json` 的 `not_supported` 字段显式记了这一条。
`golden_v2.jsonl` = 机制语料（28 条，走 `rd_oracle_run_ex`）；`golden_v1.jsonl` 保持 128 条不变，
另有 `corpus/baseline/golden_v1.jsonl` 做逐字节冻结基线（`make_corpus.py` 每次生成后都会比对）。
⚠ `pending` 恒为 0 **不是**异常：它数的是待解析的**效果请求**，脚本每次都会把队列排空；
"排队等着的卡"是另一个观测 `queue_count`（为 1 时见 `ex_queue_deferred`）。
