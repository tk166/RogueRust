"""§334/§335 文档：`hash_full` + `094d34e` 的复核结论。"""

import io

PLAN = 'docs/port-plan.md'
GAPS = 'docs/sts-wiki-gap.md'
SPEC = 'docs/spec/SEMANTICS-v1.md'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PLAN, encoding='utf-8').read()
assert '## §334' not in t
t = t.rstrip('\n') + '\n' + """
## §334 `hash_full`：把 model-only 字段也纳入指纹

`hash_golden` 是参考引擎规范文本的**逐字节**复刻，而参考只哈希它自己的一个子集。本项目里有几类
字段**参考没有**（或是它主动排掉的），于是它们此前**只进模型、不进指纹** ——
`FACT.md` 那条"`PendingChoice` 不进 `hash_golden` ⇒ `hash_full` 落地时必须覆盖它"说的就是这件事。

后果是具体的：两个**只在 `PendingChoice` 上不同**的局面，`hash_golden` 一模一样，而下一步的合法
动作集不同 ⇒ "同一串动作 ⇒ 同一局"这条回放判据**看不见**这种分叉。

### 做法：严格超集

`write_full_hash_input` = `write_hash_input`（**一个字节都不动**）+ `--full--` 之后一段模型文本。
这样三件事同时成立：

* `hash_golden` 与它 85 份语料、`golden-baseline` 闸门**完全不受影响**；
* `hash_full` 对 `hash_golden` 的每一处差异都敏感（超集 ⇒ 不会漏）；
* 两个指纹各自回答各自的问题 —— "与参考一致吗" vs "这一局真的相同吗"。

### 覆盖了什么（每条都写理由）

| 字段 | 为什么它改变"以后会怎样" |
|---|---|
| `choice`（`PendingChoice`：`chooser`/`source`/`min`/`max`/`then`/`offered`/`candidates`） | 决定"现在能选什么、选完发生什么"——**这条是 `hash_full` 存在的主要理由** |
| 状态实例的 `source_combatant_id` | DoT 的出手方：`poison` 的"施加者力量加伤"靠它 |
| `ascension` / `encounter` / `heal_blocked` | 本移植的 model-only 战斗事实（意图条件、`spot_weakness`、`mark_of_the_bloom`） |
| `gold_carried_away` / `gold_gained` | 跨层约定：逃跑带走的钱与战斗里赚到的钱 |
| `next_combatant_number` | 召唤编号（参考的哈希器不写 `summon_num`） |
| `cards_played_this_turn` / `cards_played_last_turn` | "本回合打了几张"（`Pocketwatch` / `Normality` 那一类规则读它） |
| `vacated_seat` / `extra_turn_for` / `forced_turn_ends` | 回合机的瞬时段，但决定"席位交给谁 / 谁再来一次" |

### 明确**不**覆盖的

* 待决效果/事件/续延队列、节目帧/节点/循环、`chains` / `current_chain`：**瞬时执行状态**
  （`snapshot.rs` §C 第 9 条，参考也按设计排除在快照之外）；
* `beat_log`：**已经发生过什么**的日志（§142）。两个只在日志上不同的局面，后续行为逐字相同；
* `end_turn_requested`：一个**请求**，下一次宿主调用就消费掉。

⚠️ 还有两条是"**模型里没有**"，不是"忘了"：`snapshot.rs` §A 列的
`CardPlayTurnStats`（全量）与 `TriggerActivity` 在本内核里根本不存在 ——
只有 `cards_played_this/last_turn` 两个数。它们要等真的被引入时再补。

### 判据（5 条）

* `a_pending_choice_moves_the_full_hash_but_not_the_golden_one` —— ★ 这条是全部理由：
  `hash_golden` 相同、`hash_full` 不同；
* `a_status_source_moves_the_full_hash_but_not_the_golden_one`；
* `the_model_only_fight_facts_move_the_full_hash_only` —— `ascension` / `heal_blocked` /
  `gold_gained` / `encounter` 四条各两侧；
* `everything_that_moves_the_golden_hash_also_moves_the_full_one` —— 超集的另一半
  （少了它，`hash_full` 可能退化成"根本不看规范文本"）；
* `the_full_text_is_the_golden_text_plus_a_section` —— 文本是**追加**而不是重写。

负控 2/2：删掉 `choice` 段 ⇒ 红；删掉 `status_src` 段 ⇒ 红。
⚠️ 第二条第一版写成"把 `status_src=` 改名"，**没红** —— 改名仍然改变指纹，判据只能证明
"这一段被写过"，证明不了"它写的是 source"。所以负控必须**删**，不能改名。

数字：`rd-core 819 / rd-run 215 / rd-wasm 181`、units **1215**（下限 1210 → 1215）；
`hash_golden` 的四条对拍与 85 份语料**一个字节都没动**。

## §335 复核 `094d34e`（§308 RunState 字段清点）：修复仍然成立

`094d34e` 修的是三件事：18 个漏网字段进存档与指纹、`sample_full()` 夹具、闸门 22
`state-fields`。这次用**负控**复核，而不是"读一遍代码觉得对"：

| 复核项 | 结果 |
|---|---|
| `state-fields` 闸门仍在跑 | ✅ `STATE_FIELDS PASS (67 fields)` |
| 删掉 `event_step` 的存档写入（`094d34e` 里"最坏"的那个：指纹有、存档没有） | ✅ round-trip 红 |
| 删掉 `bosses_fought` 的写入 | ✅ 红 |
| 删掉 `pickup_potions` 的写入（18 个之一） | ✅ 红 |
| 删掉 `event_relic_offer_len` 的写入（**§331 之后新加的**字段） | ✅ 红 |

最后一条是关键：它证明 `094d34e` 那条"**每加一个字段，`sample_full()` 加一行**"的纪律
在之后 §331/§332 加字段时**被遵守了**。如果夹具退化回默认值，这四条会全绿。

脚本：`native/p335_review308.py`（`REVIEW_094d34e PASS`）。
"""
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t)
print('port-plan §334/§335 ok')
