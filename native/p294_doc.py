"""§294 文档：A1 `DeckShuffled` 触发器。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §294 A1：`DeckShuffled` —— 一条触发器，两件遗物

§292.6 的 A 项里最划算的一格：`the_abacus`（洗牌 +6 格挡）与 `sundial`（每 3 次洗牌 +2 能量）
**共用同一条**新事实。

### 294.1 为什么是"我们自己的事件"

参考的 `TriggerEvent` 有 25 个成员，**没有"洗牌"**——它把这件事折进 `CardMovedToZone`。
本内核 §237 已经为同一类缺口加过两个（`CardsDrawn` / `CardExhausted`），这一条是第三个：
被真实内容逼出来的扩展，与那条"声明一个没有解析器的变体等于给'永远不生效'配个好听类型名"
是同一条纪律的反面 —— **有内容真的在等它**，才值得一个新名字。

### 294.2 落点只有一处

`CombatState::reshuffle_discard_into_draw` —— 三条洗牌的路（抽牌时的自动重洗、内容里的
`shuffleDiscardIntoDraw`、`Havoc` 一类的辅助）**全都**经过它。它已经在推进 `random_step`、
已经在处理"弃牌堆空 ⇒ 返回 0"，所以事件也发在这里：

* **只在真的洗了之后**发 —— 空弃牌堆不算一次，否则 `sundial` 的"每 3 次"会被空洗凑数；
* **入队而不是立刻派发**：这个函数在 `CombatState` 上，没有 `Host`；事件由回合机的
  事件循环解析，与 `CardsDrawn` / `CardExhausted` 同一条路（`enqueue_event`）。

Bearer 是**洗牌的那个人**。没有事实位：`sundial` 数的是**次数**，它用自己的
`combatantCounter`（与 `nunchaku` 的"每 10 张攻击牌"同一种形状）。

### 294.3 两件遗物：整条规则都是内容程序

| 遗物 | 载体 | 内容 |
|---|---|---|
| `the_abacus` | 开战挂 `standard.the_abacus` | `DeckShuffled → gainBlock 6` |
| `sundial` | 开战挂 `standard.sundial` | `DeckShuffled → remainder(counter,3)==2 → +2 能量`，然后 `counter += 1` |

内核那边**只有** `RelicEffect::StartCombatStatus(...)` 一行 —— 规则一行都不在 Rust 里。
这是"零内核改动的遗物"那条路（§260 起的同一形状）第二次吃到新触发器。

### 294.4 判据（一条，三段）

`the_shuffle_trigger_pays_the_abacus_and_sundial`（wasm，真战斗 + 真镜像）：

1. **遗物真的挂了内容状态**（`combatant.statuses()` 里有 `standard.the_abacus` 的
   `definition_id`）—— 少了这一段，"状态没挂上"与"触发器没派发"会被同一条红混在一起；
2. **洗一次牌 ⇒ `+6` 格挡**（`the_abacus`），而能量不动（`sundial` 的第一次不该付）；
3. **第 3 次才付 2 能量**（第 2 次不付）—— 并且事件队列**排空**（没有漏解析的 `DeckShuffled`）。

三种配置各跑一遍（`the_abacus` / `sundial` / 无遗物），所以"总是给 6 格挡"这类
"判据自己在撒谎"的错误也会红。

### 294.5 负控 3 条（全红）

| 改坏的地方 | 应当红 |
|---|---|
| 洗牌后**不入队** | 两件都不生效 |
| host 把事件映射成 `CardPlayed` | 派发了但没人接 |
| 内容里 `sundial` 改成**每次**都付 | "第 3 次才付"那一段 |

第三条是**内容侧**的负控（改镜像再重编）：它证明这条判据真的在数次数，而不只是"看它付了钱"。

### 294.6 账

内容遗物 **130 → 132**（缺 63 → 61）；状态 **129 → 131**；镜像 **163,592 B**；
`rd-core` 797 / `rd-run` 181 / `rd-wasm` **141**（+1）；矩阵 843 行；八道页面门 + `SOAK`；21/21。

### 294.7 A 项剩下的（每件缺什么）

| 缺的事实 | 遗物 | 难度 |
|---|---|---|
| `BlockBroken` 触发器（打破格挡） | `hand_drill` | 小：与本节同形（事件 + 内容程序） |
| "打出的牌带某 tag 时伤害 +N" | `strike_dummy` | 中：伤害管线上的第四个改写点 |
| 每回合出牌**上限** | `velvet_choker` | 中：`plan_play` 的拒绝 + 一个计数器 |
| 战斗中治疗倍率 | `magic_flower` | 中：`heal` 的数值改写（与 §263 的伤害改写同形） |
| X 费牌的 X 加数 | `chemical_x` | 小：`x_cost` 已经是计划的字段 |
| `unplayable` 放行 | `medical_kit` / `blue_candle` | 中：`validate_card_play` 的例外 |
| 隐藏敌人意图 | `runic_dome` | 小：运行层标记 → 观测 → 页面 |
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
        plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    # D.2 的"中资产"那一行：`sundial` / `the_abacus` 已经不需要 `DeckShuffled` 了。
    old_row = "| 中资产 | ~30 | 缺一个**事实/事件** | `sundial` `the_abacus`（缺 `DeckShuffled`）、`tough_bandages` `tingsha`（缺 `CardDiscarded`）、`hand_drill`（缺\"打穿格挡\"）、`bottled_*`（拾取时绑牌）、`gambling_chip` `singing_bowl` |"
    new_row = "| 中资产 | ~30 | 缺一个**事实/事件** | `tough_bandages` `tingsha`（缺 `CardDiscarded`）、`hand_drill`（缺\"打穿格挡\"）、`bottled_*`（拾取时绑牌）、`gambling_chip`（§293/§294 之后的余项） |"
    assert g.count(old_row) == 1, g.count(old_row)
    g = g.replace(old_row, new_row)

    marker2 = '''### F.13 遗物：加牌问句（§293）'''
    assert g.count(marker2) == 1
    g = g.replace(marker2, '''### F.14 遗物：洗牌触发器（§294）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `the_abacus` | 每次洗牌 +6 格挡 | **已做**（`DeckShuffled` + 内容 `gainBlock`） | 一致 |
| `sundial` | 每 3 次洗牌 +2 能量 | **已做**（计数器在内容里） | 一致 |
| 空弃牌堆算不算"洗过" | 不算 | **不算**（早退 ⇒ 不发事件） | 一致 |

### F.13 遗物：加牌问句（§293）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§293）', '（主计划 §1–§294）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
