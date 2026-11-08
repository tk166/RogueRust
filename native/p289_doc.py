"""§289 文档。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §289 奖励族收尾：指名遗物 / `MaxFloor` / 独立药水概率

三件"还差一点"的事：`fight_relic:<id>`（特定遗物）、事件池的**上界**、以及事件战斗的
**独立**药水概率。

### 289.1 `fight_relic:<id>` —— "就是这一件"

`fight_relic_rarity` 只能锁稀有度。有的奖励是**指名**的，而指名不是"更细的稀有度"：
`red_mask` 的稀有度是 `Event`，而 `Event` **不在掉落权重表里**（`relic_rarity_is_droppable`
只认 Common/Uncommon/Rare）⇒ `pick_relic` 与 `pick_relic_of_rarity` **永远抽不到它**。
所以"就是这一件"是唯一能给出它的形状。

    fight_relic:<relic id>

* 命中 ⇒ 那件就是奖励（不看稀有度）；
* **不在池里 / 已持有** ⇒ **没有遗物**（不退回按权重抽 —— 否则"就是这一件"会安静地
  变成"随便一件"）；
* 与 `fight_extra_relic` 一起用时额外那件照旧按稀有度抽（两件事互不覆盖）。

### 289.2 `MaxFloor` —— 事件池的上界

`The Colosseum` 只在**第二幕上半场**出现（wiki）。层号是**本幕内**的行号（换幕归零、
`0..=15`），所以"上半场"就是 `MaxFloor: 7`。`event_pool_at` 现在同时看两条边：

    floor < MinFloor  ⇒ 筛掉      （`Dead Adventurer` 第 7 层之后才有）
    floor > MaxFloor  ⇒ 筛掉      （`The Colosseum` 只在 1..=7）

内容门查：`MinFloor`/`MaxFloor` 是非负整数、`MaxFloor > 15` 是错误（那条事件**永远出不来**，
而屏幕上一切正常）、`MaxFloor < MinFloor` 也是错误。

### 289.3 `fight_potion_chance:<pct>` —— 这一场独立掷

药水掉落平时用**移动的概率**（40% 起，掉了 −10、没掉 +10）。事件里的战斗不是那一幕
"药水荒"节奏的一部分，所以这一场可以**独立**按 pct 掷：

* 掷骰照旧只掷一次（随机流位置不动，回放才稳定）；
* **不移动** `potion_chance` —— 这才是"独立"：这一场既不欠也不还那一幕的账。

`The Colosseum` 的 VICTORY 用 `fight_potion_chance:40`（wiki："sometimes a Potion"，
而 40% 是 wiki 的基准掉落率）。

⚠️ 哨兵：`0..=100` 都是合法概率，所以"没有覆盖"不能用 0 —— 用 `NO_POTION_OVERRIDE = 255`。
判据是两侧的：`0` ⇒ 一定不掉**且**追踪值不变；`100` ⇒ 一定掉**且**追踪值不变
（只有一侧的话，"药水永远不掉"也能通过）。

### 289.4 `Masked Bandits` 为什么还没做

它有 `fight_relic` 最自然的用户（`Red Mask`），但今天缺两件东西：

1. 三个**名册外**的敌人（`Pointy` / `Romeo` / `Bear`）—— 用现有怪物替换是在发明一场战斗；
2. "失去**全部**金币"（`[Pay]`）—— 需要一个 `gold_all` 原子（今天的词表只有定数与区间）。

所以 `fight_relic` 只建机制、不造假内容：内容门校验载荷（必须在 `REL` 表里且内核实现了它的
效果），判据在**真遗物池**上验三条。等名册补齐，`Masked Bandits` 的奖励就是
`{ fight_relic: red_mask, fight_gold_set: 30 }`。

### 289.5 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `a_named_relic_is_paid_exactly_or_not_at_all`（run） | 指名命中（`Event` 稀有度也能给）/ 不在池 ⇒ 空 / 已持有 ⇒ 空 |
| `an_independent_potion_chance_leaves_the_tracker_alone`（run） | `0%` 不掉**且**追踪值不变；`100%` 掉**且**追踪值不变 |
| `the_unknown_room_events_are_readable`（core，§289 段） | `MaxFloor` 两侧：第 3 层有 `the_colosseum`、第 9 层没有，且只筛掉一个 |
| 内容门 | `fight_relic` 的载荷在 `REL` 表且已实现；`fight_potion_chance` 是 0..=100 且 `Amount` 为 0；`MaxFloor` 的上下界与地图长度 |

**负控 3 条全 RED**：① 指名遗物退回按权重抽；② 独立掷照旧移动追踪值；③ 上界被忽略。

★ 第一版判据有两处"验了不可能成立的东西"，都被判据自己抓出来：
药水池传了 `&[]`（空池 ⇒ 永远没药水 ⇒ "100% 也不掉"）；以及"把追踪值顶到 100"这个前提
取不到（掉一次就 −10）。

### 289.6 账

镜像 **161,404 B**（core 127,372 B）；`rd-core` 797 / `rd-run` **164** / `rd-wasm` 134；
八道页面门 + `SOAK`；21/21。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '### G. ★ 基础值偏差'
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.9 奖励族与楼层门槛（§289）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| 指名遗物奖励 | `Masked Bandits` 的 `Red Mask` | **机制已做**（`fight_relic:<id>`），内容未接 | 缺内容：三个名册外敌人 + `gold_all` |
| `The Colosseum` 出现位置 | 只有 Act 2 的**上半场** | **已做**（`MaxFloor: 7`） | 一致 |
| 事件战斗的药水 | 独立的一次掉落 | **已做**（`fight_potion_chance`，不移动追踪值） | 一致（口径见 §289.3） |
| `Masked Bandits` 的 `[Pay]` | 失去**全部**金币 | 没有"失去全部金币"原子 | 缺 |

### G. ★ 基础值偏差''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§288）', '（主计划 §1–§289）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§289 doc')


main()
