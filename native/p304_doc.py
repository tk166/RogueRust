"""§304 文档：`gambling_chip` + `toolbox`。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §304 `gambling_chip` / `toolbox`：开战那一刻问一句

两件遗物都是"**开战那一刻**问玩家一句"，而句子形态**早就存在**：

| 遗物 | wiki | 复用哪个形态 |
|---|---|---|
| `gambling_chip` | *"At the start of each combat, discard **any number** of cards, then draw that many"* | 现成的 `DiscardThenDraw`（Gambler's Brew 那条），`min = 0` |
| `toolbox` | *"At the start of each combat, choose 1 of **3** random Colorless cards and add the chosen card into your hand"* | 现成的 `Offered`（Attack/Skill Potion 那条），但**按印刷价格**入手 |

### 304.1 时点：第 1 回合**开始之后**

`gambling_chip` 弃的是**起手牌**、`toolbox` 加的是起手牌**之外**的一张 —— 所以钩子挂在
`start_first_turn` + `apply_combat_bonus_block` **之后**、提交点的 `reobserve` **之前**：
页面读到的第一份观察里就带着待决问句。

### 304.2 两件同时持有：一个位掩码，按固定顺序问

内核的 `begin_choice` 拒绝嵌套，所以两件同时在身上时不能同时问。`RunSession.open_choices`
是**位掩码**（`COMBAT_OPEN_GAMBLING_CHIP` / `COMBAT_OPEN_TOOLBOX`）：`fight_begin` 时按遗物
算出来，每问出一位就清一位，`rd_env_choice_confirm` 成功后调 `after_choice_resolved()`
接着问下一位。

⚠️ 掩码是"**欠着还没问**的"，不是"一共几次"：`ask_next_open_choice` 在**已经有问句挂着**时
直接返回且不清位 —— 于是"谁发起问句"永远只有一个来源。

### 304.3 ★ 新变体 `ChoiceThen::ToHandPrinted`：因为"免费"会变成一句谎

`toolbox` 拿到的牌按**印刷价格**进手牌。最接近的现成变体是 `ToHand`，但它的语义是
"拿进手牌 + 写一个每副本价格"，而页面那句 `2:3` 的文案写死了 **"（它这次免费）"**。

复用 `ToHand` 再传 `delta = 0` 的后果是：**行为对、话是谎** —— 屏幕承诺免费、内核按印刷价
收费。所以加一个变体，并把"价格不动"写进变体本身：`resolve_choice` 对它的任何非零
`cost_delta` 报 `DeltaNotApplicable`。页面的 `2:10` 是它自己的句子。
（这是 §250 那条判据的镜像：那边是"静默忽略一个折扣"，这边是"静默承诺一个不存在的折扣"。）

### 304.4 顺手修的一处真错

`rd_env_choice_confirm` 的 `Offered` 分支**无条件**算 `priced_delta`。对 `PlayChosen`（Wish）
这类不写价格的变体，那只是靠"恰好 0"没事；但 **X 费牌**会算出 `Err`，于是"选它就被拒"。
改成"只有真的写价格的变体才算差价"。

### 304.5 判据与负控

| 判据 | 钉住 |
|---|---|
| `the_combat_open_relics_are_a_bitmask_and_absent_without_the_relics`（rd-run） | 没有遗物 ⇒ `(0, 0)`；两件同时 ⇒ 两位都立、`offer == 3` |
| `gambling_chip_asks_at_combat_start_and_discards_then_draws`（wasm） | 问句自己出现、`min == 0`、`max == 手牌数`；弃 2 ⇒ 手牌不变、弃牌 +2、抽牌堆 −2 |
| `toolbox_offers_three_colorless_cards_and_charges_the_printed_price`（wasm） | 三张候选**都是无色**；入一副新牌**且没有任何价格标记** |
| `both_open_relics_ask_one_question_at_a_time`（wasm） | 先 chip 后 toolbox；答完一个第二个才出现 |
| `native/p304_page.mjs`（一次性真浏览器） | 两句话在**屏幕上**说到点上、三个候选、确认后回到战斗 |

**负控 4 条全红**：没有遗物也问 / chip 的 `min` 写成 1 / 池子不筛无色 / ★ 误用 `ToHand`（写折扣）。

### 304.6 ★ 这一轮的两次判据自坑（都是"牌组太小"与"选择器写错"）

1. `gambling_chip` 的判据第一版用 5 张牌组：起手 5 张、抽牌堆 0，于是"弃 2 抽 2"会把刚弃的
   **洗回抽牌堆**，弃牌堆变成 0 —— 那不是 bug，是洗牌。判据要的牌组必须**够大**。
2. 一次性浏览器判据用了 `[data-choice-index]` 与 `modal.classList.contains("hidden")`，
   而页面用的是 `[data-choice]` 与 `modal.hidden`：**选择器不对 ⇒ 读到 0 个候选**，
   看起来像"页面没画选项"。这正是"工具报成功、被测对象没被测到"的老形状。

### 304.7 账

内容遗物 **149 → 151**（缺 44 → 42）；镜像 167,856 → 168,xxx B；`rd-core` 809 /
`rd-run` **184**（+1）/ `rd-wasm` **149**（+3）；矩阵 877 行；八道页面门 + `SOAK`；21/21。

### 304.8 剩下的 42 件

* **E 类**：`frozen_eye`（抽牌堆显示顺序）、手牌保留类；
* **F 类**：`necronomicon`（明确不做：打两次）、无色池的其余部分；
* **不做**：另外三个角色、Blight。

⚠️ **页面侧还没有 `2:10` 之外的自动化**：`p304_page.mjs` 是一次性脚本，不进闸门
（它要真浏览器，而 `browser_test.mjs` 已经在跑同一套 CDP；把它并进去是下一步的便宜活）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§304 `gambling_chip`' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '### F.22 遗物：落区与地图（§302/§303）'
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.23 遗物：开战问一句（§304）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `gambling_chip` | 开战弃**任意张**、抽同样多 | **已做**（`DiscardThenDraw`，`min = 0`） | 一致 |
| `toolbox` | 开战三选一**无色**牌入**手牌** | **已做**（`Offered` + 新变体 `ToHandPrinted`） | 一致 |
| 入手的牌是否免费 | wiki 没有这句 ⇒ **按印刷价** | `ToHandPrinted` 一个字都不写；页面的句子也不说免费 | 一致 |
| 两件同时 | 各自触发一次 | 位掩码，先 chip 后 toolbox（内核一次只许一个问题） | 顺序是写明了的实现选择 |

### F.22 遗物：落区与地图（§302/§303）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§303）', '（主计划 §1–§304）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
