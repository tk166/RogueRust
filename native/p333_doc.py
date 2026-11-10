"""§333 文档：把"下一回合多抽/多能量"这条 gap 的**分析**与**修法**写清。"""

import io

PLAN = 'docs/port-plan.md'
GAPS = 'docs/sts-wiki-gap.md'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PLAN, encoding='utf-8').read()
assert '## §333' not in t
t = t.rstrip('\n') + '\n' + """
## §333 "下一回合多抽 / 多能量"：先纠正 gap 的定性，再补那一个时刻

`docs/sts-wiki-gap.md` §2.B 那条写的是"需要：**内核**（回合开始的发牌/能量）"。**这句话是过时的** ——
两条管线都在，而且都有真实消费者。逐条对账（这一节的主要产出）：

| 管线 | 读它的时刻 | 现有消费者 |
|---|---|---|
| `TurnStartDraw` | 回合开始第 **6** 步（抽牌） | `standard.draw_reduction`（每层 −1，`panic`）、`standard.ring_of_the_serpent`（+1 flat）、**§333 起** `standard.snecko_eye`（+2 flat） |
| `TurnStartEnergy` | 回合开始第 **2** 步（补能） | `berserk`、`philosophers_stone`、`art_of_war`、`mark_of_pain`、`slavers_collar`、`busted_crown`、`ectoplasm`、`sozu`、`cursed_key`、`velvet_choker`、`runic_dome` |

所以缺的不是"回合开始的发牌/能量"，而是**一次性**：wiki 的 `Energized` / `Draw Card` 是
"**只**下一回合"，而上面 13 个消费者全是"每回合"。

### 涉及的流程 / 遗物 / 卡牌（用户问的那张清单）

**流程（3 处，只有 1 处要动）**

1. **回合开始**（`turn.rs::start_current_turn`）—— 顺序是
   `补能(2) → pending 转正(3) → TurnStarted 触发器(4) → 队列(5) → 抽牌(6) → 清 Block(7)`。
   这条顺序是**语义**，也是这个 gap 的根：能量在**触发器之前**读、抽牌在**触发器之后**读，
   所以"自己 `TurnStarted` 摘掉自己"对能量成立、对抽牌不成立。
   ⇒ **要动**：在抽牌之后加一个"过期"钩子（内容够不到那一刻）。
2. **回合末**（`end_current_turn`）—— 不需要动：`Energized`/`Draw Card` 不该在回合末衰减
   （它们不是 `UsesDuration`）。
3. **战斗开始**（`build_fight` / 第 1 回合）—— 不需要动：`bag_of_preparation` 是
   "开战多抽 2"，用的是 `TurnStarted` 触发器 + 首回合条件，已经对。

**遗物（都不需要改，但有三件值得记下来）**

| 遗物 | 现在的实现 | 结论 |
|---|---|---|
| `art_of_war` | `TurnStartEnergy/AddFlat 1` + **计数器条件**（`art_of_war_attacks`，`TurnEnded` 置位/清零） | 已经是"下回合 +1 能量"的正确形状，**不动** |
| `pocketwatch` | `TurnStarted` 触发器里 `drawCards 3`（条件：上回合出牌 ≤3） | 行为对，但"先抽 3 再抽 5"而非"抽 8"（重洗时机/`no_draw` 交互不同）。**本轮不动**（它不属于这条 gap，且改它要碰"上回合出牌数"的事实） |
| `snecko_eye` | ~~`TurnStarted` 里 `drawCards 2`~~ ⇒ **§333 改成 `TurnStartDraw/AddFlat 2`** | 顺手修：wiki 说的是 "Draw 2 additional cards each turn"，那就是管线的语义 |

**卡牌（口径内 0 张，口径外 4 张）**

* **Ironclad 75 张里没有一张**是"下回合多抽/多能量"：`berserk` 是"每回合 +能量"（已对），
  `seeing_red` / `bloodletting` 是"**本**回合 +能量"（已对），`battle_trance` 等是"本回合抽"
  （已对）。所以这条 gap 对**当前可玩内容**没有可见影响 —— 这也是它一直没被修的原因。
* **Colorless 70 张里也没有**。
* 口径外（静默猎手/观者）需要它的牌：`Outmaneuver`（`Energized` 2/3）、
  `Doppelganger`（`Draw Card` X + `Energized` X）、`Predator`（下回合多抽 2）、
  `Study` / `Foresight`（观者的"下回合多抽"）。⇒ 一旦补静默猎手/观者，**这四个消费者立刻要用**
  新状态，所以载体先做好是划算的。

**结论**：这是"**载体缺、消费者在口径外**"的一条 gap。修它不需要改任何**遗物或卡牌**；
需要的只是 (a) 两个状态行，(b) 一个"读完就摘"的时刻。

### 修法

1. **内核**：标签 `one_shot_turn_start` + `Host::expire_one_shot_turn_start`（与 §197
   `consume_one_shot_block_retainers` 同形：收集定义 → 删实例），在**抽牌之后**调一次。
   那一刻两条管线都已经读过它们了。`TurnHost` 给默认空实现（只有 `Host` 有内容）。
2. **内容**：`standard.energized`（`TurnStartEnergy/AddPerStack 1`）、
   `standard.draw_card_next_turn`（`TurnStartDraw/AddPerStack 1`），都带那个标签、都**没有触发器**。
3. 两条状态在 `status_catalog::is_declared_inert` 里登记（行为在修饰器行里，`has_behaviour`
   看不见它们 —— 与 `draw_reduction` / `no_draw` 同一条理由）。

### 判据

`the_one_shot_turn_start_statuses_apply_once_and_then_go_away`（rd-core）：挂
`energized 2` + `draw_card_next_turn 3`，然后

1. 下一回合：能量 `3+2`、手牌 `5+3`；
2. **状态真的消失**（不是留一条 0 层）；
3. 再下一回合：能量回到 3、手牌回到 5。

只测 ① 的话，"每回合都 +X"（把一次性写成永久）照样绿 —— 那正是这条机制的全部区别。

负控 2/2：删掉"抽牌后过期" ⇒ 红；把 `draw_card_next_turn` 的 `one_shot_turn_start` 标签删掉
（变成每回合）⇒ 红在 `standard.draw_card_next_turn is spent`。

数字：`rd-core 814 / rd-run 215 / rd-wasm 181`、units **1210**（下限 1209 → 1210）；
四条对拍不动。
"""
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t)
print('port-plan §333 ok')

# gap 文档：那两行重写
g = io.open(GAPS, encoding='utf-8').read()
old = """| **Draw / Energized（**下一回合**多抽 / 多能量）** | 回合开始结算 | 内核（回合开始的发牌/能量）—— 现在只有**本回合**的 `combat_draw` / `combat_energy`，以及"下一回合**少**抽"的 `standard.draw_reduction` |"""
new = """| ~~**Draw / Energized（**下一回合**多抽 / 多能量）**~~ | 回合开始结算 | ✅ **§333 已做**：两条管线（`TurnStartDraw` 第 6 步 / `TurnStartEnergy` 第 2 步）本来就在，缺的是**一次性** —— 现在有 `standard.energized` 与 `standard.draw_card_next_turn`（修饰器 + 标签 `one_shot_turn_start`，内核在**抽牌之后**摘掉）。⚠️ 旧版这条写"需要内核（回合开始的发牌/能量）"，那是**过时**的：当时已有 13 个消费者（`art_of_war` / `snecko_eye` / `ring_of_the_serpent` / `berserk` …） |"""
assert g.count(old) == 1, 'gap row'
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(g.replace(old, new))
print('gap doc row rewritten')
