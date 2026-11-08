"""§308 记账：`RunState` 的字段清点（审阅报告 §2 的落地）。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'

DOC = r"""
---

## §308 `RunState` 字段清点：18 个漏网字段 + 一道新闸门

审阅报告（`docs/vibe/Review_2a8d87a_5842c59_07_Content_Scaling.md` §2）说"新增长期状态没有
完整接入存档与状态哈希"。核对之后**它是对的，而且比它列的更长**：报告列了 5 组，
穷尽遍历结构体字段是 **18 个**：

```
marks  bosses_fought  event_step  event_resume  event_next  event_fight
event_fight_pool  fight_gold_bonus  fight_gold_set  fight_no_relic  fight_relic_rarity
fight_extra_relic  fight_relic  fight_potion_chance  chest_extra  chest_empty
pickup_relics  pickup_potions
```

其中 `event_step` 的形态最坏：**指纹有、存档没有**。于是"事件走到第 3 段"存档之后重开，
会**静默回到第 1 段** —— 玩家按一次"保存"就能撞上。

### 308.1 三个根因（都不是"忘了"，是判据自己瞎）

1. **那句"漏还原一个字段就红"是假的。** `archive.rs` 的 round-trip 判据是
   `assert_eq!(restored, run)`，而夹具 `sample()` 只设了六个字段（种子/牌组/金币/血/一瓶药水/
   一件遗物）—— 18 个新字段**全在默认值**，漏与不漏同色。这是 §161.5 那个形状的第二次出现：
   **守卫在下游，夹具看不见上游**。
2. **`marks` 身上有一条把两个指纹混为一谈的理由。** 原注释写着"它不进 run hash：
   参考的运行层没有这个概念" —— 那条裁决属于 `hash_golden`（参考引擎逐字节复刻）；
   `hash.rs` 是**我们自己**的行动回放指纹，判据是"同一串动作 ⇒ 同一局"。
   一个字段只要影响**未来行为**，它就必须进后者。
3. **`remove_deck_card` 清了 `deck` 的尾槽，没清 `marks` 的尾槽**；`push_card` 只写 `deck[slot]`。
   ⇒ 删掉一张带成长的 `Ritual Dagger`，尾槽留着它的成长；**下一张加进来的牌继承它**。
   §253 修过"删牌时 mark 跟着牌走"，漏的正是反方向："加牌时它是全新的"。

### 308.2 改法

* 存档：`VERSION` 10 → **11**，18 个字段按"事件链 / 宝箱与欠账 / 下场战斗覆盖 / 每副本 mark"
  四组写进 payload（写与读两处，顺序同构）；`marks` 只写**活动前缀**。
* 指纹：同 18 个字段进 `hash.rs`；`marks` 写成 `marks=<条数>` + 每格 `m<下标>=<键>,<值>`
  —— **只写有值的格**（60 行空 `m=` 会把 8 KB 的指纹缓冲顶穿，实测过一次）。
* 不变量：`marks` 的活动前缀之外必须为空（`Invariant("a per-copy mark outlived its card")`）；
  `bosses_fought ∈ {0,1}`。
* 容量（常量是语义，改了就要写账）：`MAX_PAYLOAD` 4096 → **8192**、
  `MAX_ARCHIVE` 16384 → **24576**。依据是压出来的实测：60 张牌各带一条 mark 时
  **文本 5653 B**（payload 约 4.5 KB），而按 `MAX_PAYLOAD` 算的 base64×RLE 上界是 21.8 KB。

**新闸门 22 `state-fields`**（`native/check_state_fields.py`）：穷尽读 `pub struct RunState` 的
字段表，逐个要求它出现在 `write_payload` 与 `hash.rs` 里；豁免必须带理由，豁免表里的字段
一旦被删也是红。它证明的只是"点过名"（编译才证明"打得开"），但漏掉的那 18 个正是"没点名"。

> ⚠️ 这个脚本第一版把文档注释里的 `{` 当成花括号，于是把 `Pending` / `inv` / `Cumulative`
> 当成字段读了出来 —— **解析器自坏比字段缺更隐蔽**（它会红得很有说服力）。改成逐行去注释
> 再数括号之后是 63 个字段。

### 308.3 判据与负控

| 判据 | 作用 |
|---|---|
| `a_saved_run_round_trips_byte_identically`（改用 `sample_full()`） | 18 个新字段各取非默认值，`assert_eq!(restored, run)` 从此**真的**在比这些字段 |
| `a_deck_where_every_copy_carries_a_mark_still_fits` | 最坏情况装得下 + 逐字节回来（容量判据，不是"应该够"） |
| `a_removed_cards_mark_does_not_live_on_in_the_tail` | 删牌后尾槽清空 |
| `a_mark_beyond_the_deck_is_an_invariant_violation` | 新不变量**自己**会响 |
| `a_newly_added_card_never_inherits_a_mark` | 加牌不继承 |
| `a_per_copy_mark_is_visible_in_the_fingerprint`（rd-run hash） | 只有某一张牌的成长不同 ⇒ 指纹不同（报告的最小复现 #5） |

**负控（"只改数字不算验证"）**：`native/p308_negative.py` 把 `chest_extra` 的写入、
`marks` 的写循环分别删掉，`round_trips` 两次都**红**；跑完自动还原。

**闸门自己的反证**：`acceptance.ps1 -UnitsFloor 99999` 必须红（§161.5 的教训：
一个从来没生效过的下限天天报绿）。这次下限抬到实测值 1150。

### 308.4 账

`RunState` **63 个字段**，全部同时进存档与指纹（`STATE_FIELDS PASS`）；
`rd-core` 809 / `rd-run` **190**（+5）/ `rd-wasm` 151；聚合闸门 **22/22**（`rust-units 1150 passed`）。

### 308.5 顺带发现（不在这一节做）

* `rd-wasm` 的单元测试**必须** `--test-threads=1`：并行跑会以
  `STATUS_HEAP_CORRUPTION` / `STATUS_STACK_BUFFER_OVERRUN` 退出（全局 session + 裸指针）。
  这条在干净树上也能复现，不是本轮引入的；`acceptance.ps1` 早就带着 `--test-threads=1`。
* `Orange Pellets`（§310）、`CombatBonus` 容量与拾取原子性（§309）按审阅报告的顺序排在后面。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§308 `RunState` 字段清点' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)
    print('§308 recorded')


main()
