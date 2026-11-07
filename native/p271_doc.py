"""§271 文档 + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §271 轻资产档（三）：**节点类** 3 件 + **药水类** 2 件

| 遗物 | 稀有度 | wiki 原话 | 落点 |
|---|---|---|---|
| `meal_ticket` | Common | "Whenever you enter a shop, heal 15 HP." | `begin_node` 的 Shop 分支 |
| `ssserpent_head` | Event | "Whenever you enter a ? room, gain 50 Gold." | `begin_node` 的 Unknown 分支 |
| `ancient_tea_set` | Common | "Whenever you enter a Rest Site, start the next combat with 2 extra Energy." | Rest 分支置 `tea_set_pending` + 开战兑现 |
| `sozu` | Boss | "…You can no longer obtain Potions." | `push_potion` 拒绝 + `roll_reward` 不掷 |
| `toy_ornithopter` | Common | "Whenever you use a potion, heal 5 HP." | `consume_used_potion` → 战斗员 +5 |

### 271.1 三个节点钩子都在 `begin_node` 的 `NodeKind` 分支上

`begin_node` 是**唯一**知道"这一格是什么房间"的地方（`enter_node` 只挪游标）。所以三条规则
各占一个分支，`meal_ticket` 与 `Eternal Feather` 同一个规矩：**进门就付**，不是"用了服务才付"
（wiki 的 `Eternal Feather` 页面写过 "Heal applies on entering"）。

`ssserpent_head` 走 `adjust_gold`，所以 `ectoplasm` 该拦就拦、`bloody_idol` 该回血就回血 ——
"金币变了"这条规则只有一处。

### 271.2 `ancient_tea_set`：一个**欠一场**的字段

能量是战斗里的资源，而进篝火那一刻**没有战斗**，所以不能"当场加"。所以：

1. 进篝火 ⇒ `tea_set_pending = true`（`owe_tea_set_for_the_next_fight`，一个实现两个调用方：
   篝火分支与判据）；
2. `combat_bonus_for(kind)` 读它，把 `standard.ancient_tea_set` 挂进开战加成；
3. **开战那一刻** `clear_tea_set()`。

⚠️ 清理点的位置是这条规则的**全部**：先清再算，`combat_bonus_for` 就永远读不到它，
`ancient_tea_set` 变成一件什么都不做的遗物 —— 而**所有判据都还是绿的**（没有任何东西"错"）。
所以负控专门做了这一处：把 `clear_tea_set()` 挪到算加成之前，
`the_tea_set_charge_is_spent_by_the_next_fight` 必须变红。

内容侧的 `standard.ancient_tea_set` 是**抄 `lantern` 的程序**（`TurnStarted` + 计数器 == 0 ⇒
加能量），只改两个数（`Amount` 1 → 2、计数器 `lantern_turns` → `tea_set_turns`）。手写 IR 是这一批
最容易错的地方，而错法很隐蔽 —— 所以生成脚本自带两条自检（"Amount 是 2"、"没有共用 lantern 的
计数器"）。**自检当场抓到过一次**：第一版递归在"没有 `kind` 的中间节点"上停住，`Amount` 没改成 2。

### 271.3 `sozu` 有两道门，判据要各自证明

* **不发**：`roll_reward` 里 `drop &= !NoPotionGain` —— 奖励屏上根本不该出现药水那一格。
  掷骰照旧（随机流位置不动）。
* **收不了**：`push_potion` 返回 `RunError::PotionGainBlocked` —— 事件/调试入口递过来的也进不了
  腰带。自己的错误变体而不是复用 `Capacity`：容量满是"腾一格再来"，这里是"永远不行"。

判据两面都测：`sozu` 之下 24 个种子**一个药水都不发**，而对照组 24 个种子里**至少有一个**
（否则第一条什么也没证明）。

### 271.4 `toy_ornithopter` 回的是**战斗里**那一份血

`run.health` 不是战斗中的真血：一场战斗的 HP 在战斗状态里，结束时才折回运行层。改运行层那一份
会被折回覆盖 —— 玩家看不到回血，而且没有任何地方会报错。所以 `heal_on_potion_use` 用**两个 slot**：
`run_slot()`（认识遗物）取数字、`crate::slot()`（认识血量）改战斗员。
第一次写混成一个 slot，编译器直接报 `expected &RunState, found &Box<CombatState>`。

数字本身只在遗物表里（`RelicEffect::PotionUseHeal(5)`），wasm 通过 `RunState::relic_effect` 读，
不写第二个 5。

### 271.5 没做的两件（写下来而不是绕过去）

`tiny_chest`（"Every 4th ? room is a Treasure room"）与 `juzu_bracelet`（"Regular enemy combats
are no longer encountered in ? rooms"）都需要 `?` 房**不是**事件的证据 —— 而现在
`begin_node` 的 Unknown 分支**永远**开一个事件（`unknown` 那三个计数器在指纹里，却**没有消费者**，
这一轮把它记下来了）。要这两件就得先造"`?` 房的 monster / treasure / shop / event 分流"，
那是中资产（新规则层 + 遭遇池 + 页面），不属于"在既有的一行旁边加一个判断"。

### 271.6 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `the_node_relics_pay_on_the_right_kind_of_room` | meal_ticket 进商店 +15、进篝火不动；ssserpent_head 进 `?` +50、没有它一分不多；ancient_tea_set 进篝火后加成里有 `standard.ancient_tea_set`（而且不是 lantern 的），清掉后下一场没有 |
| `sozu_refuses_potions_at_both_doors` | `push_potion` 报 `PotionGainBlocked` 且 run 一个字节不变；24 个种子奖励屏都没有药水（对照组至少一次有）；能量载体逐条比 id |
| `the_potion_relics_carry_their_own_numbers` | `toy_ornithopter` = `PotionUseHeal(5)`，而 `burning_blood` 不是 |
| `drinking_a_potion_heals_five_with_the_toy_ornithopter`（wasm） | 真喝一瓶：**战斗员** +5；没有遗物时喝同一瓶**不回血** |
| `the_tea_set_charge_is_spent_by_the_next_fight`（wasm） | 真开一场：`tea_set_pending` 被清**且**那一场英雄身上真有 `standard.ancient_tea_set` |

**负控**（`native/p271_negative.py`，跑完自动还原）：四处切口全 RED ✓ —— 房间、`sozu` 两道门、
以及最容易骗人的"`clear_tea_set` 顺序"。

### 271.7 账

遗物 **100 → 105 件**；`rd-core` 788 / `rd-run` **135** / `rd-wasm` **122**；内容 124 状态 / 105 遗物；
镜像 144,716 B（core 111,420 B）；存档 `VERSION` 4 → **5**；四条对拍全过；
`ACT1_SLICE` / `SOAK` / `MAP_RENDER` / `BROWSER_TEST` PASS；`COVERAGE_MATRIX` 778 行；21/21。
"""


def main():
    doc = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(doc.rstrip('\n') + '\n' + DOC)

    s = io.open(README, encoding='utf-8').read()
    s = s.replace('* **遗物**：**100 / 193**', '* **遗物**：**105 / 193**')
    s = s.replace('所以缺的 93 件', '所以缺的 88 件')
    s = s.replace('/ 122 状态 /', '/ 124 状态 /').replace('/ 100 遗物 /', '/ 105 遗物 /')
    s = s.replace('144,028 B 的 `rdcf` 镜像（core 镜像 110,972 B）。',
                  '144,716 B 的 `rdcf` 镜像（core 镜像 111,420 B）。')
    s = s.replace('（主计划 §1–§270）', '（主计划 §1–§271）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(s)
    print('doc §271 + README')


main()
