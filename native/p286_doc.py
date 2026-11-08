"""§286 文档：port-plan + 缺口表 + coverage matrix + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §286 段的进入效果 + **事件中途开战斗**（Dead Adventurer）

§285 留了两条尾巴：奖赏只能在结果屏的 `[Leave]` 上兑（多一次点击），以及
`Dead Adventurer` 的"25%/35% 精英归来"没有载体。这一节把两条都补上，顺手把
`Chance`/`NextFail` 收成权重表（`Dead Adventurer` 的一次搜索是**四选一**，两条边装不下）。

### 286.1 `Branches`（取代 §285 的 `Chance`/`NextFail`）

```
选项：{ Label, Effects, Branches: [{Weight, Next}, ...], BranchesAsc: [...], Fight: "elite" }
段：  { Id, TextKey, Effects: [...], EffectsAsc: [...], Options: [...] }
```

* 权重**和恰好 100**（内容门查）；内核按累积读，最后一档吸收零头 —— 所以"和不是 100"
  不会越界，但会被门拦下（那不是"接近"，是一个概率表和它写的数字不一致）。
* 两条边是它的特例：`[{70,win},{30,lose}]`。§285 的形状**删掉了**，内容门对
  `Chance`/`NextFail` **报错**（留着它的人以为概率还在，而内核只看 `Branches`）。
* `BranchesAsc` 是 A15 那一版（`Dead Adventurer` 的伏击率 25% → 35%）。

### 286.2 段的**进入效果**（`Effects` / `EffectsAsc`）

到达目标段时应用，与选项自己的效果在**同一个事务**里（失败整个回滚，所以"金币到账了但
改牌被拒"不会留半截）。进入效果**不许改牌**：改牌会变成待答问题，而问题队列只有一个位置，
那个位置属于选项。

**格式没动**：`EVND` 行的第 4 格本来就是 `extra` —— 编译器把没被 schema 消费的字段打包
成一个对象塞进那一格（`compile.py: row()` 的 `leftover`）。所以加 `Effects` 只是多了一个
AUX 对象，行宽与 `FORMAT_VERSION` 都不变。⚠️ 但那个对象形状**在文档里从不字面出现**，
`Deriver.scan()` 扫不到 ⇒ 第一版 `Encoder.obj()` 直接 `KeyError`。修法是
`register_extra_shapes()`：按 `extra` 的 leftover 登记形状，登记方式与扫描逐字段一致。

### 286.3 **事件中途开战斗**

`Fight: "elite"`（或 `"monster"`）写在一个选项上。选它 ⇒ 事件**收尾**、房间**不**结算，
运行层把档位记进 `event_fight`；`rd_run_fight_begin` 认这个档位（它同时决定池子与战后
结算的档位），`mark_resolved` 是**唯一**清它的地方。

* 为什么档位留在 `RunState` 而不是页面：三个答案（要不要开打 / 哪个池子 / 战后按哪档结算）
  必须出自同一个数，否则"页面按精英画、内核按普通怪发奖"这种漂没人能看出来。
* 为什么事件先收尾：`Dead Adventurer` 的伏击打完**不回到事件**（wiki："The event ends with
  no additional dialogue after the Elite is defeated"）。于是"节点只付一次"仍然成立 ——
  反复按"开始战斗"不会刷出第二场（节点要等战斗结算）。

### 286.4 Dead Adventurer（Act 1）

23 段：搜索段 1 + 3 + 3（按"还剩下哪些奖励"分叉 ⇒ 每件奖励只出现一次）、奖励段
3 + 6 + 3、伏击段 1、以及每段的 `[Leave]`。

* 伏击率 **25/50/75%**（A15 **35/60/85%**），每次搜索 +25 个百分点；
* 安全时从剩余奖励里**均匀**取（30 金币 / 随机遗物 / 什么都没有）；
* 奖励在**到达**时兑（进入效果），所以"你找到了 30 金币"那一屏就是钱的落点；
* 被伏击 ⇒ 只有一个 `[Fight]`，打的是本幕的**精英**池，按精英结算（遗物、`Preserved Insect`
  一类都走同一条路）。

### 286.5 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `entry_effects_land_on_arrival_and_roll_back_together` | 到达时兑；进入效果失败 ⇒ **选项那半也回滚** |
| `a_four_way_branch_reaches_every_branch` | 四档**都到过**（64 个种子），同种子同结果 |
| `an_event_can_turn_the_room_into_a_fight` | 档位置位、事件收尾、节点**不**结算、`mark_resolved` 清档位 |
| `an_event_fight_begins_and_settles_as_an_elite`（wasm） | `[Fight]` → `event_fight()==2` → `fight_begin` 接受 → `elite_fight` → 战后节点结算 |
| `every_event_effect_word_in_the_image_parses`（wasm，**穷尽**） | 镜像里每一个事件效果词（选项 + 进入效果）都必须解析得出来 |
| `the_unknown_room_events_are_readable`（§286 段） | Dead Adventurer 的权重和 = 100、A15 = 35%、奖励不重复、`[Fight]` 是精英 |
| 内容门 | `Branches` 2..4 项/和 100/`Next` 存在且可达；`Chance`/`NextFail` **报错**；`Fight` 与后继互斥；进入效果走**同一份**词表且不许改牌 |

**负控 6 条全 RED**：① 进入效果不应用；② 四选一总走第一档；③ `mark_resolved` 不清档位；
④ `relic_random` 回到"带载荷"那一支；⑤ `gold_random` 用原值比较；⑥ `fight_begin` 不认事件战斗。

### 286.6 穷尽判据抓到的两个真问题（都是 §285 埋的）

1. **`relic_random` 从来没解析出来过**：它没有冒号，却被写进 `split_once(':')` 那一支 ⇒
   `parse` 恒 `None`。页面只是少一个按钮，没有任何闸门会红；`Scrap Ooze` 的"找到遗物"那一屏
   真的点不动。抓到它的是 `Dead Adventurer` 的走图判据。
2. **`gold_random:-20:-50` 读不出来**：内容门按**绝对值**比较负区间，内核按**原值** ⇒
   `-20 <= -50` 为假。两处对同一条规则的认识不一致，而症状是"这条效果不存在"。

⇒ 教训写进 §4.20 的白名单：**"词表"要有一条穷尽判据**（走遍内容里的每一个词），
而不是"我检查了清单"。

### 286.7 账

事件 **16 → 17**；step **46 → 69**（Dead Adventurer 23 段）；镜像 **159,476 B**
（core 125,444 B）；`rd-core` 797 / `rd-run` **157** / `rd-wasm` **131**；
`STS_CONTENT PASS`；七道页面门 + `ACT1_SLICE` + `SOAK`；21/21。

### 286.8 还没做的

* `Dead Adventurer` 的**战后补偿**：wiki 说"战斗胜利后补发还没搜到的奖励，另加 25-35 金币"。
  我们的奖励流程是 `roll_reward(kind)`，它不知道"这一次少发了什么" ⇒ 缺一条
  "把奖励差额带进战斗结算"的通道。伏击**之前**搜到的奖励不会重复（树里已经给过），
  但"还没搜到的"不会补。**偏差，见缺口表**。
* Lagavulin 在这场伏击里**不该睡着**（wiki）：我们的 `ENCT` 没有"这次不睡"的列。
* 楼层门槛（wiki：`Dead Adventurer` 只出现在第 7 层之后）：事件池还没有"按楼层筛"的能力。
* `The Colosseum`（Act 2）：同一套机制可以做，缺的是"打完回到事件"（我们是"战斗结算房间"）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '### G. ★ 基础值偏差'
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.6 事件中途开战斗（§286）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `Dead Adventurer` 战后补偿 | 战斗胜利补发"还没搜到"的奖励，另加 25-35 金币 | **不补**（奖励流程 `roll_reward(kind)` 不知道差额） | **偏差**：缺"把奖励差额带进战斗结算"的通道 |
| `Dead Adventurer` 的 Lagavulin | 这场伏击**不睡觉**，开局直接 Siphon Soul | 睡眠是遭遇的静态属性，没按"这次不睡"覆盖 | **偏差**：`ENCT` 没有这一列 |
| `Dead Adventurer` 的出现楼层 | 只出现在第 7 层之后 | 事件池无按楼层筛 | 缺：`EV` 没有楼层门槛 |
| 奖赏时机（§285 的偏差） | 到达结果屏就生效 | **已修**：段落进入效果（§286） | 一致 |
| 伏击的档位 | 精英 | 精英（同一套 `elite_fight`） | 一致 |

### G. ★ 基础值偏差''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§285）', '（主计划 §1–§286）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§286 doc + gap rows + README')


main()
