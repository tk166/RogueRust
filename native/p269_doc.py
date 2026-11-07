"""§269 文档 + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §269 轻资产档（一）：**战斗类型层** 4 件 + **奖励层** 5 件

### 269.1 战斗类型层

| 遗物 | 稀有度 | wiki 原话 | 落点 |
|---|---|---|---|
| `preserved_insect` | Common | "Enemies in Elite combats have 25% less HP." | `enemy_health_bonus_percent(Elite)` —— **与升阶同一条通道** |
| `pantograph` | Uncommon | "At the start of Boss combats, heal 25 HP." | `CombatBonus::start_heal` |
| `slavers_collar` | Boss | "During Boss and Elite combats, gain 1 Energy at the start of your turn." | `StartCombatStatusInKinds` + `TurnStartEnergy` 状态 |
| `sling_of_courage` | Shop | "Start each Elite combat with 2 Strength." | `StartCombatStatusInKinds` |

两条新变体把"哪几类战斗"收成了一个 **`KindMask` 位掩码**：遗物表里写
`KindMask::ELITE` / `KindMask(2 | 4)`，读起来就是 wiki 那句话。旧入口
`combat_bonus()` 保留为 `combat_bonus_for(FightKind::Normal)` —— 它的调用方（大量测试、
`rd-wasm` 的非战斗路径）没有"这一场是什么类型"这个概念。

`preserved_insect` **没有走新路径**：它加在 `enemy_health_bonus_percent(kind)` 里，也就是
升阶 A7/A8/A9 用的同一个数。⚠️ 这条是刻意的 —— 为它另开一条"精英血量"的通道会让那个数字
有两个来源。副作用：那个函数从 `const fn` 变成 `fn`（查遗物表不是常量表达式）。

### 269.2 奖励层

| 遗物 | 稀有度 | wiki 原话 | 落点 |
|---|---|---|---|
| `question_card` | Uncommon | "Future card rewards have 1 additional card to choose from." | `RewardCardDelta(+1, ALL)` |
| `busted_crown` | Boss | "…Future card rewards have 2 less cards to choose from." | 能量状态 + `EXTRA_REWARD_CARD_DELTAS` |
| `prayer_wheel` | Rare | "Normal enemies drop an additional card reward." | `RewardCardDelta(+1, NORMAL)` |
| `white_beast_statue` | Uncommon | "Potions always appear in combat rewards." | `PotionAlwaysDrops` |
| `black_star` | Boss | "Elites now drop an additional relic when defeated." | `EliteExtraRelic` |

三处值得写的细节：

**(1) `MAX_REWARD_CARDS`（存储）与 `BASE_REWARD_CARDS`（一屏几张）分开了。**
存储 3 → **4**（`question_card` 要放得下第 4 张），而"默认给 3 张"成了独立常量。
把两者混成一个数，加一张牌就要动所有下标 —— 而第一版就是这么写的，判据报
"question_card: +1 得到 3"（`clamp` 把它压回了存储上限）。

**(2) `busted_crown` 有两半，而 `relic_effect` 只能表达一个。**
它既是"每回合 +1 能量"（走 `StartCombatStatus`）又是"奖励卡数 -2"。第二半写在一张
**显式的小表** `EXTRA_REWARD_CARD_DELTAS` 里，并在那里写明"只有一件"的理由 ——
比让 `relic_effect` 长出"返回多个"小得多。

**(3) `black_star` 的第二件遗物是直接进包的。**
奖励屏只有一个遗物槽（`Reward::relic`），加第二个槽要改结构、ABI 与页面三处。所以第二件
掷出来就 `push_relic` —— **偏差写在这里**，别让它悄悄消失。

`white_beast_statue` 的实现也有一处刻意：**掷骰照旧**，只把结果 OR 成真。
跳过掷骰会让随机流少走一格、回放对不上。

### 269.3 判据

| 判据 | 钉住 |
|---|---|
| `the_kind_gated_relics_only_fire_in_their_own_kinds` | Sling **只在精英**给 1 条状态（普通/Boss 各 0）；Collar 在精英与 Boss 给、普通不给；Pantograph 只有 Boss 的 `start_heal == 25`；Insect 只有精英 `-25`，且**与升阶同通道**（A8 的 +10 叠加成 -15） |
| `the_reward_layer_relics_change_the_payout` | 基线 3；Question Card 4（普通与 Boss 都是）；Prayer Wheel 只有普通 4、精英仍 3；Busted Crown 3-2=1 **且**挂上能量载体；Question+Busted = 2 |

每条都**两面**（该生效的 kind 生效、不该生效的不生效）：没有反面，`sling_of_courage`
就会变成"任何战斗都 +2 力量"而判据全绿。

⚠️ 一处数值陷阱记下来：本内核的升阶血量增量是 `ASCENDED_ENEMY_HEALTH_PERCENT = 10`
（不是 wiki 那套 +75% 分数），所以"升阶精英 + 昆虫"是 **+10 - 25 = -15**。
判据写成 `ASCENDED_ENEMY_HEALTH_PERCENT - 25` 而不是硬编码，免得下次改升阶时它悄悄错。

### 269.4 账

遗物 **80 → 89 件**；`rd-core` 788 / `rd-run` 129 / `rd-wasm` 120；内容 121 状态 / 89 遗物；
四条对拍全过；`ACT1_SLICE` / `SOAK` / `MAP_RENDER` PASS；21/21。
"""


def main():
    doc = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(doc.rstrip('\n') + '\n' + DOC)

    s = io.open(README, encoding='utf-8').read()
    s = s.replace('* **遗物**：**80 / 193**', '* **遗物**：**89 / 193**')
    s = s.replace('所以缺的 113 件', '所以缺的 104 件')
    s = s.replace('/ 119 状态 /', '/ 121 状态 /').replace('/ 80 遗物 /', '/ 89 遗物 /')
    s = s.replace('142,476 B 的 `rdcf` 镜像（core 镜像 110,008 B）。',
                  '143,316 B 的 `rdcf` 镜像（core 镜像 110,504 B）。')
    s = s.replace('（主计划 §1–§268）', '（主计划 §1–§269）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(s)
    print('doc §269 + README written')


main()
