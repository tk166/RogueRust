"""§288 文档。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §288 The Colosseum（打完**回到事件**）+ 事件池的楼层门槛

§287 的两条尾巴：`The Colosseum`（Act 2）和"事件只在某层之后出现"。前者要一个新机制
（§286 的 `Fight` 是"战斗结算房间"，而竞技场的第一场要**回到事件**），后者要事件池能按楼层筛。

### 288.1 `After`：战斗之后回到事件

```
选项：{ Label: "Fight", Fight: "monster", Encounter: "ColosseumSlavers", After: "the_colosseum.after" }
```

* `After` 存在 ⇒ 事件**不收尾**：`event` 留着、`event_step` 清空（战斗期间没有选项可点）、
  房间**不**结算，`event_resume` 记住回哪一段；
* 打赢之后 `resume_event_after_fight()` 把事件摆回那一段、`pending` 回到 `Event`；
  它是**一次性**的（再问一次答 `false`，否则一场战斗能被回两次）；
* 这一场**不发奖励** —— wiki 对竞技场第一场明写 "This fight gives no rewards"，
  而它的奖励就是"事件继续"。所以 `apply_fight_outcome` 在**掷奖励之前**先问这一句。

⚠️ `After` 是可达性的**第三条边**（`Next` / `Branches` / `After`）。只沿前两条走会把事件的
后半段判成"孤儿段"——判据当场抓到了 `the_colosseum.after`。

### 288.2 奖励覆盖：`fight_gold_set` / `fight_relic_rarity` / `fight_extra_relic`

wiki：竞技场的 VICTORY 给 `100 Gold, 1 Rare Relic, 1 Uncommon Relic, a card reward,
sometimes a Potion`。按档位掷永远给不出"定数 100 金币 + 指定稀有度两件"，所以加三条**这一场的
奖励修正**（与 §287 的欠账同一套：事件效果写、`roll_reward` 读一次就清）：

| 词 | 含义 |
|---|---|
| `fight_gold_set:<n>` | 这一场的金币**就是** n（不是加法 —— 它把整个区间换掉） |
| `fight_relic_rarity:<common\\|uncommon\\|rare>` | 这一场那件遗物的稀有度**锁定** |
| `fight_extra_relic:<...>` | 这一场**再**给一件该稀有度的遗物（`black_star` 的同一条路） |

锁定的稀有度**抽不到就是没有**（不退回按权重抽）：否则"1 Rare Relic"会安静地变成
"一件随便什么遗物"。`pick_relic_of_rarity` 与 `pick_relic` 共用同一段候选扫描，唯一差别是档位不掷。

`Rarity` 要存进 `RunState`（`Copy`、进存档/回放），所以有一个 `rarity_code`/`rarity_of_code`
的字节编码 —— 判据钉"每个变体码不同且往返一致"（加一档稀有度忘了改这两行就会红）。

### 288.3 楼层门槛（`Dead Adventurer` 第 7 层之后）

```
EventTables.Events: [{Id: "golden_idol"}, ..., {Id: "dead_adventurer", MinFloor: 7}]
```

`Content::event_pool_at(pool, floor)` 过滤后再交给"掷一个"。**先筛后掷**（不是掷了不合格再
重掷）：后者会让随机数被它看不见的规则吃掉。

★ 这条判据抓到一处**静默失效**：第一版 `event_pool_at` 用 `NodeRef::str_field("Id")` 读池条目，
而池条目的 `Id` 在镜像里是**字符串槽**（`F_STRLIST` 的元素），`str_field` 走的是 `F_STR` 字段
那条路 ⇒ 恒 `None` ⇒ **所有条目都被跳过、门槛从不生效**，而"筛过的列表"与"没筛的列表"
一模一样（我的判据正好是比这两个列表的长度，于是它红了）。修法是照 `id_pool` 的方式手解对象槽。

### 288.4 内容

* `the_colosseum`（Act 2，2 段）：`[Fight]` → `the_colosseum.after` → `[VICTORY]` / `[COWARDICE]`；
* `enc_colosseum_slavers`（`blue_slaver` + `slaver_red`）、`enc_colosseum_champions`
  （`taskmaster` + `gremlin_nob`）—— 两个**事件专属**遭遇，登记在内容门的 `INV_EVENT_ONLY`
  （敌人组成是写下来的，且**不算**进 wiki 的遭遇数）；
* 池：`EncounterTables.ColosseumSlavers` / `ColosseumChampions`（各一条）。

### 288.5 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `a_fight_can_return_to_the_event`（run） | `After` ⇒ 事件留着、节点不结算、回到那一段、**一次性** |
| `the_fight_reward_overrides_are_exact`（run） | 金币**恰好** 100、遗物锁定 Rare、额外那件进了包、第二场恢复正常 |
| `every_rarity_has_a_distinct_code`（run） | 字节编码两两不同且可逆 |
| `the_unknown_room_events_are_readable`（core，§288 段） | 竞技场的段/池/`After`；**楼层门槛两侧**（6 层没有、7 层有，且只筛掉一个） |
| `the_colosseum_fight_returns_and_the_victory_pays_exactly_once`（wasm） | 胜利后 `pending = Event`（不是 `Reward`）、金币没动、`event_step` 回到 `.after`；VICTORY 恰好 100 |
| 内容门 | `After` 只在战斗选项上且必须是真的一段、并参与可达性；三个新词的词法；`INV_EVENT_ONLY` 的敌人组成 |

**负控 4 条全 RED**：① 战斗不再回到事件；② 楼层门槛被忽略；③ 定数金币被忽略；
④ `event_resume` 不记（`After` 形同虚设）。

### 288.6 账

事件 **17 → 18**；step **72 → 74**；遭遇 **45 → 47**（两个事件专属）；镜像 **161,332 B**
（core 127,296 B）；`rd-core` 797 / `rd-run` **162** / `rd-wasm` **133**；
八道页面门 + `SOAK`；21/21。

### 288.7 还没做的

* 竞技场第二场的**药水**（wiki：sometimes a Potion）走的是既有的精英池概率，没有单独的口径。
* `The Colosseum` 只在**第二幕上半场**出现（wiki）：楼层门槛的机制已经有了，但"上半场"是
  "楼层 ≤ 半幕"，需要一个 `MaxFloor`（今天没有用户，所以没加）。
* `Masked Bandits` / `The Nest` 那种"定数金币 + 特定遗物"的事件现在可以照着
  `fight_gold_set` / `fight_relic_rarity` 写了。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '### G. ★ 基础值偏差'
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.8 事件战斗与楼层门槛（§288）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `The Colosseum` 第一场 | 打 Blue Slaver + Red Slaver，**没有奖励**，打完继续事件 | **已做**（`After` + "回到事件不发奖励"） | 一致 |
| `The Colosseum` VICTORY | Taskmaster + Gremlin Nob；100 金币、1 稀有、1 罕见、选牌、（有时药水） | **已做**（`fight_gold_set:100` + 两个稀有度词）；药水走精英池概率 | 基本一致 |
| `The Colosseum` 出现位置 | 只有 Act 2，且只有**上半场** | 只在 `Events2`（Act 2）；"上半场"没做 | 缺 `MaxFloor` |
| `Dead Adventurer` 的出现楼层 | 第 7 层之后 | **已做**（`MinFloor: 7`） | 一致 |

### G. ★ 基础值偏差''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§287）', '（主计划 §1–§288）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§288 doc + gap + README')


main()
