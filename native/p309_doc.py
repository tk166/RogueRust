"""§309 记账：开战状态容量 + 拾取原子性。"""
import io

ROOT = 'D:/Vibe/sts-tui/'
PLAN = ROOT + 'docs/port-plan.md'
README = ROOT + 'README.md'
ACCEPT = ROOT + 'tools/acceptance.ps1'

DOC = r"""
---

## §309 开战状态的容量与拾取类遗物的原子性

审阅报告 §4/§3 的两条 P1。核对之后第一条**比报告判的更严重**，第二条是**潜伏**（只有退化
的池子能触达）但违反本仓已写下的纪律。

### 309.1 `MAX_COMBAT_STATUSES`：4 → 腰带容量 48

报告说"容量 4 达到上限时会丢效果，但尚未验证合法组合能否触及"。核对发现两件事：

1. **每件带战斗程序的遗物都推一条 `standard.<relic>` 标记状态**（内核靠它知道"这件遗物在
   身上"：`runic_pyramid` / `lantern` / `ice_cream` / `calipers` 全是这样）。主表里这种遗物
   有 **80 件** —— 所以 4 格的上限在**第 5 件**就撞上，不需要"稀有组合"：
   `vajra` + `oddly_smooth_stone` + `thread_and_needle` + `bronze_scales` + `orichalcum`
   五件常见遗物就是 5 条。
2. 旧代码的失败路径是 `let _ = bonus.push_status(...)` 三处 + `debug_assert!` 一处 ——
   **release 里全是静默丢**。

改法：

* 容量 = **[`MAX_RUN_RELICS`]（48）**。这不是拍的：结构上界就是"腰带里能装几件遗物"，
  因为一个 match 臂只给一件遗物一条效果，`RELIC_SECOND_HALVES` 的 5 条又与主表的 hero 效果
  不重叠（实测 overlaps = 0）。
* 六处重复的"合并或追加"循环收成**一个** `add_status()`。"同一条状态相加，否则追加"这条规则
  原先写了六遍，而"表满了怎么办"藏在六个不同地方 —— 同一份规则写六遍必然漂。
* 满了 ⇒ `assert!`（与 `Reachable::push` 同款：这是"调用方破坏了前提"，响亮 > 丢一件遗物）。

**闸门里的结构检查**（`native/check_state_fields.py` 的第二段，闸门 22 一起跑）：
从**表本身**重算上界并要求 `capacity >= belt + overlaps`，同时拒绝"capacity 超过腰带两倍"
（那是一个没人重新推导过的常量）。今天打印：

```
belt=48 capacity=48 hero_arms=80 overlaps=0 enemy=3 per_curse=1
COMBAT_STATUS_BOUND PASS (capacity 48 >= belt 48, no relic occupies two slots)
```

### 309.2 拾取类遗物：失败 ⇒ 一个字节都不改

`push_relic("tiny_house", pool)` 先加金币 / 上限 / 当前血 / 欠一瓶药水 / 欠一张牌，再
`roll_pickup_offer(pool)?` —— 池子不合格时前面那些改动**留在原地**，而遗物没进腰带。
`orrery`（`PickupAddCards`）与 `pickup_add_card`（加了一张、再抽下一手）同形。

修法不是给每条 `?` 补回滚（十几处，下一次加一行又会漏），而是**一次快照**：
`RunState` 派生 `Copy`，`push_relic` / `pickup_add_card` 各自包一层
（`*_inner` + 失败时整体写回）。判据直接比整个结构体 —— 与 `archive::restore` 的
"拒绝 ⇒ 一个字节都不改"同一条纪律（FACT §8）。

> 结构上仍然是"一个入口两层"，但**回滚只在一处**：`push_relic` 的所有 `?` 自动被覆盖，
> 包括将来新加的那些。

### 309.3 判据与负控

| 判据 | 作用 |
|---|---|
| `a_run_with_five_status_relics_keeps_all_five` | 五件合法遗物 ⇒ 五条状态、层数逐个对（报告的最小复现） |
| `a_refused_tiny_house_changes_nothing_and_a_good_pool_does_everything` | 空池拒绝 ⇒ 整局相等；合格池 ⇒ 金币/上限/欠账**真的**生效 |
| `a_refused_orrery_changes_nothing_and_a_good_pool_does_everything` | 同上（`pickup_add = 5`） |
| `a_pickup_add_that_cannot_roll_again_rolls_back_the_card_it_added` | 超容池子：牌加进去了、抽下一手失败 ⇒ 整局回滚 |

**负控**（`native/p309_negative.py`）：容量退回 4、`push_relic` 不回滚、`pickup_add_card`
不回滚 —— **3/3 条按预期变红**，跑完自动还原。

### 309.4 账

`rd-run` **194**（+4）；聚合闸门 **22/22**（`rust-units 1154 passed`，
`state-fields 63 fields` + `COMBAT_STATUS_BOUND`）。

### 309.5 小结（留给下一次的自己）

两条 P1 的根因是同一个形状：**"失败"被写成了"不发生"**。
* 容量那一处：`let _ = ...` 让"表满"看起来像"没有这件遗物"；
* 原子性那一处：`?` 之前的副作用让"被拒绝"看起来像"只成功了一半"。

判据的写法也跟着这一条：不许只断言"成功那条路"，必须断言**拒绝之后整局相等**，
并且**反向**再断言"合格的输入真的生效"（否则"永远拒绝"也能通过）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§309 开战状态的容量' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    text = io.open(README, encoding='utf-8').read()
    old = '& .\\tools\\acceptance.ps1                                               # 22 道闸门，约 5 分钟'
    assert text.count(old) == 1
    text = text.replace(old, old)

    # 在"怎么跑测试"那一段补一条：rd-wasm 必须串行。
    anchor = '`acceptance.ps1` 有**真参数块**（`-SkipSlow`、`-UnitsFloor`），不是位置参数。'
    assert text.count(anchor) == 1
    text = text.replace(anchor, anchor + '''
`cargo test -p rd-wasm` **必须**带 `--test-threads=1`：它的测试共享一份全局 session（裸指针
写进去），并行跑会以 `STATUS_HEAP_CORRUPTION` / `STATUS_STACK_BUFFER_OVERRUN` 退出。
`acceptance.ps1` 就是这么跑的 —— 手工复现时别漏了它。''')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(text)

    accept = io.open(ACCEPT, encoding='utf-8').read()
    assert accept.count('  [int]$UnitsFloor = 1150') == 1
    io.open(ACCEPT, 'w', encoding='utf-8', newline='\n').write(
        accept.replace('  [int]$UnitsFloor = 1150', '  [int]$UnitsFloor = 1154'))
    print('§309 recorded; README note added; UnitsFloor 1154')


main()
