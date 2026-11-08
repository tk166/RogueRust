"""§298 文档：A5 收尾（magic_flower / medical_kit / blue_candle）+ A 项总结。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §298 A5：A 项收尾 —— 治疗倍率与"放行 unplayable"

### 298.1 `magic_flower`：一个入口一个乘法

"During combat, healing is 50% more effective." 与 §263 的三个伤害改写同族（内核认状态 id、
数字是 wiki 常量），落点是 `heal_for` —— **治疗的唯一入口**：

```
amount = amount * 150 / 100      // 只在接受治疗的人身上有那条状态时
```

⚠️ **乘在这一个函数里**，不是每个 `Heal` 请求的入队处：入队处有七八个（药水、卡牌、
`dealDamageAndHealByLoss`、事件给的回复……），漏一处就是"某条路的治疗不翻倍"，
而它看起来完全正常。这条理由与 §237 的"`CardExhausted` 只有一个落点"同形。

判据钉三侧：10 → 15（带遗物）、10 → 10（不带）、**7 → 10**（`7×1.5=10.5` 向下取整），
另加一条上限侧（回 100 点只回满 40 点）。

### 298.2 `medical_kit` / `blue_candle`：放行 + 强制消耗

| 遗物 | 放行哪一类 | 代价 |
|---|---|---|
| `medical_kit` | `unplayable` 的 **Status** 牌 | 无（打掉即消耗） |
| `blue_candle` | `unplayable` 的 **Curse** 牌 | **失去 1 点生命** |

内核改两处：

1. `unplayable_validator` 从前只拿 `card`（"放行"这件事根本无从判断）⇒ 现在拿 `state`，
   按"**牌的种类** + 身上有没有那条状态"决定；
2. 放行之后落区强制 **`ExhaustPile`**。少了这一条，"打一张 wound"会把它塞进弃牌堆 ——
   玩家能反复打同一张，与 wiki 的 "Exhaust it" 相反，而且**没有任何东西会红**。

`blue_candle` 的"失去 1 点生命"是**内容**：一条 `CardPlayed` 触发器 + `card.hasTag.curse`
的门 + `node.loseHp 1`。所以它一行 Rust 都不用 —— 与 §297 的 `strike_dummy` 同一条路。

### 298.3 判据（两侧 + 反面，四条）

`the_two_unplayable_relics_let_their_own_card_kind_through`：
① 没遗物 ⇒ `wound` 与 `injury` 都被拒；② `medical_kit` ⇒ `wound` 能打、**进消耗堆**、不掉血；
③ `medical_kit` **不**放行诅咒；④ `blue_candle` ⇒ `injury` 能打、进消耗堆、**失去 1 点生命**；
外加成对的一面（`blue_candle` 不放行 Status 牌）。

`magic_flower_multiplies_healing_by_one_and_a_half`：见 298.1 的三侧 + 上限侧。

### 298.4 负控 4 条（全红）

倍率改 100 / 用加法代替乘法（`+50` 而不是 `×1.5`）/ `medical_kit` 不限牌的种类 /
放行后不强制消耗。

### 298.5 A 项到此结束：七件，四条不同形状

| 遗物 | 载体 | 节 |
|---|---|---|
| `the_abacus` `sundial` | 新触发器 `DeckShuffled` + 内容程序 | §294 |
| `hand_drill` | 新触发器 `BlockBroken`（Bearer + EventTarget 两个槽） | §295 |
| `chemical_x` | 内核规则（`x_cost` 加 2） | §296 |
| `strike_dummy` | **纯内容**（`RestrictSourceCardTag` 已存在） | §297 |
| `velvet_choker` | 新校验器 `CardLimit`（拒绝码 19） | §297 |
| `runic_dome` | 内核 + **观测**（意图在观测里就没有） | §297 |
| `magic_flower` `medical_kit` `blue_candle` | 内核规则（治疗倍率 / 放行的例外） | §298 |

**九件，七个不同的落点** —— 这正是 §292.6 那张"缺哪块载体"的表想说的话：
"轻资产"不是"改一行"，而是"每件都要先想清楚规则该住在哪里"。

### 298.6 账（A 项合计）

内容遗物 **116 → 140**（缺 77 → 53）；状态 **128 → 139**；镜像 **165,340 B**；
`rd-core` **803**（A 项 +6）/ `rd-run` 181（A 项 +11 来自 §293）/ `rd-wasm` **143**；
矩阵 859 行；八道页面门 + `SOAK`；21/21。

### 298.7 A/B 之后剩下的（`docs/sts-wiki-gap.md` D.2 与 F 各节）

* **C 类**（`createRandomCardInstance` / `offerRandomCards` 已有，可直接写成内容程序）：
  `dead_branch` / `nilrys_codex` / `warped_tongs` / `enchiridion` / `mummified_hand` /
  `orange_pellets` —— 这一批**不需要动内核**，是下一轮最省力的。
* **E 类**（地图/页面）：`wing_boots`（忽略路径 3 次）、`frozen_eye`（抽牌堆显示顺序）。
* **F 类**：`strange_spoon`（消耗改丢弃 50%）。
* **G 类**：`neows_lament`（开局三场的敌人 1 血）。
* **H 类**：`gambling_chip` / `toolbox`（开战前三选一）。
* **不做**：`necronomicon`（打两次）、`prismatic_shard` / `toolbox` 的无色池部分、
  另外三个角色（Defect / Silent / Watcher）的专属遗物、Blight（无尽模式）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§298 A5' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '''**A. 战斗侧的一个新事实**（`rd-core`，每件几十行，但共享同一条新通道）：'''
    if g.count(marker) == 1:
        g = g.replace(marker, '''**A. 战斗侧的那一批 —— §294–§298 全部做完**（九件，七个不同落点；
逐件见 `port-plan.md` §298.5）。下面这张表是**做完之前**的样子，留着当"缺哪块载体"的样本：''')

    marker2 = '''### F.17 遗物：规则住在三处（§297）'''
    assert g.count(marker2) == 1
    g = g.replace(marker2, '''### F.18 遗物：治疗与放行（§298）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `magic_flower` | 战斗中治疗 +50% | **已做**（`heal_for` 一个乘法，×150 向下取整） | 一致 |
| `medical_kit` | `unplayable` 的 Status 牌可打，打掉即消耗 | **已做**（校验器放行 + 落区强制 `ExhaustPile`） | 一致 |
| `blue_candle` | `unplayable` 的 Curse 牌可打，失去 1 生命、打掉即消耗 | **已做**（放行在内核，掉血是**内容**触发器） | 一致 |
| 放行后的落区 | "Exhaust it" | 强制 `ExhaustPile`（少了它玩家能反复打同一张） | 一致 |

### F.17 遗物：规则住在三处（§297）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§297）', '（主计划 §1–§298）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
