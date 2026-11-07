"""写 §267 文档头部（清单表格由 MISSING 分类生成，避免手抄）。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'

SECTION = '''
---

## §267 遗物扫描 + 零基建批次（18 件）

### 267.1 先扫一遍：还是的 119 件按"需要什么"分类

`native/audit_relic_gap.py` 给出账（56 → 74 件已实现，119 件缺）。逐条读 wiki 原文后，
**按"需要什么基建"归成四档**（这张表就是这一步的产物，比"再记 119 个名字"有用）：

| 档 | 数量 | 典型 | 说明 |
|---|---|---|---|
| **零基建**（纯内容） | ~30 | `art_of_war` / `charons_ashes` / `clockwork_souvenir` | `TurnStarted`/`TurnEnded`/`HpLost`/`CardExhausted`/`CardPlayed` 触发器 + 已有的修饰器管线与 §264/§266 的参数 |
| **轻资产**（一个小钩子） | ~25 | `preserved_insect`（精英血量 -25%）/ `question_card`（多 1 张选牌）/ `sozu`（不能再拿药水） | 都是"某个**已存在**的层里加一个判断"：战斗构建（kind）、奖励掷骰、商店价格、金币增减、卡组增删 |
| **中资产**（一个新事件/节点） | ~15 | `sundial`/`the_abacus`（洗牌）/ `unceasing_top`（手牌空）/ `hand_drill`（破格挡） | 缺一个"事实"，不是缺一条规则 |
| **暂不做** | ~50 | Defect/Silent/Watcher 专属（球、Calm/Mantra、Shiv、毒相关卡池）、`Blight` 桶 | 用户已明确"观者先不开发"；Blight 是无尽模式 |

这张表的口径是**可执行性**，不是"想不想做"：零基建那一档今天就能全部落地，轻资产每一件
要动一个具体的位置，中资产要先造事实。

### 267.2 这一批：零基建 18 件

| 组 | 遗物 | 机制 |
|---|---|---|
| 轮次轴 | `ring_of_the_snake`(Starter) / `ring_of_the_serpent`(Boss) / `philosophers_stone`(Boss) / `happy_flower` / `art_of_war` | `TurnStartDraw` / `TurnStartEnergy` 修饰器 + `TurnStarted` 计数器 |
| 反应轴 | `centennial_puzzle` / `runic_cube` / `charons_ashes` / `duality` / `akabeko` / `brimstone` | `DamageTaken`+`HpLost` / `CardExhausted` / `CardPlayed` 触发器 |
| 开战载体 | `clockwork_souvenir` / `red_mask` / `gremlin_visage` / `fossilized_helix` / `mutagenic_strength` | `StartCombatStatus(OnEnemies)` 的既有四个变体 |
| 拾取即生效 | `mango` | 既有 `MaxHealthUp` |

外加 **3 处元数据修正**：`nunchaku` / `pen_nib` 应是 **Common**、`paper_krane` 应是 **Uncommon**
（§262/§264 当时按"这七件全是 Uncommon"批量写的，那是错的 —— `audit_relic_gap.py` 的
`METADATA` 一节一直报着，这次顺手改掉）。

### 267.3 ★ 三处踩出来的**时序**（这才是零基建真正的难点）

零基建不等于零思考：规则能写进内容，但"什么时候算"仍然是语义。

**(1) `art_of_war`：回合末给的能源会被下回合补给抹掉。**
第一版写成 `TurnEnded` → `gainResource(energy, 1)`，判据报 **3 而不是 4** ——
因为下一次回合开始的补给是"**设成** base"，不是"加"。正解：回合末只立一个待决标记
（`art_of_war_pending`），能量走 `TurnStartEnergy` 修饰器 + `Condition: pending > 0`，
清零放在 `TurnStarted`（**晚一步**，那时补给已经发生）。

**(2) "掉血"有两条路。**
`HpLost` 只在**失去生命**那条路（`offering` / `bloodletting`）发；伤害走 `DamageTaken`。
`centennial_puzzle`（第一次掉血抽 3）与 `runic_cube`（每次掉血抽 1）都**两条都要听**，
后者还要加 `eventAmount > 0` 的门（被格挡吃干净的那次是 0）。

**(3) `DamageTaken` 触发器要求**有出手方**。**
`Host::run_damage_taken_triggers` 的第一句就是"没有出手方就跳过"（与参考同一条）。
判据夹具最初用 `source: None` 的伤害，于是掉血类遗物**一个都不触发** —— 那不是 bug，
但值得写下来：**环境伤害不会触发"被你伤害/掉血"类遗物**，这条是参考的行为。

### 267.4 判据（按机制分三条，不是一件一条）

| 判据 | 钉住 |
|---|---|
| `the_turn_axis_relics_move_draw_energy_and_periods` | 第 1 回合 7 张（Ring of the Snake）vs **每回合** 6 张（Serpent）；Philosopher's Stone 4 能量；Happy Flower **第 3 回合**才给；Art of War 没出攻击 ⇒ 下回合 4 能量 |
| `the_combat_start_carriers_land_the_right_status` | Artifact 1；**Buffer 真的挡住第一次掉血**且被消耗；Mutagenic **第一回合末**真的掉 3 力量 |
| `the_reaction_relics_fire_the_right_number_of_times` | Puzzle 第一次 +3、第二次 +0；Cube 每次 +1；Charon's Ashes 出 `offering`（自消耗）后敌人掉 ≥3；Duality +1 敏捷**并**挂"回合末归还"的孪生；Akabeko 第一击 14、第二击 6；Brimstone 第 1 回合开始 +2/+1 |

两处**夹具**踩坑也记下来：① Cultist 自己的 `Ritual` 每回合末 +3 力量，所以 Brimstone 的敌人
力量要写成 "1 + 3 + 1 = 5" 并说明来源，而不是"看起来该是 2"；② 第 1 回合的开始**也算一次**
回合开始（`start_first_turn` 就在那一刻派触发器），所以"打完一回合"是**两次**。

### 267.5 账

遗物 **56 → 74 件**（+18）；`rd-core` 788 / `rd-run` 126 / `rd-wasm` 119；内容 114 状态 / 74 遗物；
四条对拍全过；`ACT1_SLICE` / `SOAK` / `MAP_RENDER` PASS；21/21。
剩下的零基建档还有 ~12 件（`self_forming_clay` / `dead_branch` / `bird_faced_urn` / `unceasing_top`
等），轻资产档 ~25 件 —— 见 §267.1 的分档。
'''


def main():
    src = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(src.rstrip('\n') + '\n' + SECTION)
    print('doc §267 written')


main()
