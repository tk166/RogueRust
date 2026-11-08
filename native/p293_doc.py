"""§293 文档：加牌问句（B）—— 三件遗物共享一条新通道。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §293 B：拾取时"挑一张牌**加**进牌组"

§292.6 的 B 项：运行层缺一个"加牌"的问句，三件遗物都在等它。这一节把它做出来，三件一起落地。

### 293.1 为什么是**新通道**，不是 `Pending` 的一个变体

`Pending` 是"**这个节点**要什么"，一个流程一个写者。而拾取可能发生在**另一个屏开着的时候**
（宝箱、战斗奖励屏、商人货架）—— 把 `pending` 抢过来会把那一屏顶掉，玩家丢掉还没拿的奖励。
§274 已经为"欠着的牌组编辑"立了这条规矩（`pickup_change` / `pickup_picks`），这一节照同一条
形状再加一组：

| 字段 | 意思 |
|---|---|
| `pickup_add` | 还欠**几张牌**要加进牌组（`orrery` 5、`tiny_house` 1） |
| `pickup_offer[..len]` | 这一次可以挑的那几张（一手，最多 `MAX_REWARD_CARDS`） |

两者都**进 run hash**、都**进存档**（存档 `VERSION` 7 → 8）—— 不进指纹就"两局只差一次加牌"
哈希相同，不进存档就"读回来不欠了，那几张牌永远拿不到"。

⚠️ 与 `pickup_picks` **分开**而不是合并：那个是"改**已有**的一张"，这个是"从候选里**加**一张"。
一个字段两用会让"还要选几张"说不清是哪一种（而两种的收尾动作完全不同）。

### 293.2 三件遗物

| 遗物 | wiki | 实现 |
|---|---|---|
| `orrery` | 拾取时挑 5 张牌加入牌组 | `PickupAddCards(5)` → 欠 5 次，每次挑完**换一手新的** |
| `tiny_house` | +50 金币、上限 +5、1 瓶药水、1 张牌 | `PickupTinyHouse`（四件事一件遗物；金币走 `adjust_gold`，所以 `ectoplasm` / `bloody_idol` 照常互动） |
| `singing_bowl` | 加牌时**可以**改拿 +2 上限 | `SingingBowl(2)`：加牌问句与**战斗奖励屏**各多一个"换"的入口 |

候选牌的**档位与战斗奖励同一套**（`reward_bands(FightKind::Normal, …)` + `pick_of`，同一条
空档兜底链），但**不动** `rarity_offset`：那是"战斗奖励的稀有度保底"（`inv:§3.5`），
让一件商店遗物重置它，"三场没出稀有"会凭空消失。这条偏差写在这里。

### 293.3 页面：一条与 `pickupPicks` 完全同形的通道

* `ui_panels.js::describePickupAdd` —— 面板**优先级最高**（压过奖励屏/宝箱屏），选完自然回到
  原来那一屏；每一行带**内核的槽号**（不是数组下标，§161.8 的老账）。
* `+2 上限` 按钮**只在持有 `singing_bowl` 时画**：没有那件遗物时内核会 `UnsupportedRelic`，
  画出来就是一个点了没反应的死按钮。
* 奖励屏上同理，并且**牌已经被拿走之后**不再画（那时内核会 `EmptyOffer`）。
* 四条新动作进 `PANEL_ACTIONS`（页面唯一一处"按钮的意思"）。

### 293.4 判据（两侧各一次）

| 判据 | 钉住 |
|---|---|
| `orrery_owes_five_cards_and_rolls_a_new_hand_each_time` | 欠 5；挑一张牌组 +1、欠账 -1；**换一手**（`hand_before != hand_after`）；欠账 0 时 `WrongPhase` |
| `tiny_house_does_all_four_things` | 金 +50、上限 +5、血 +5、一瓶药水欠账、一张牌欠账 |
| `singing_bowl_trades_a_card_for_two_max_hp_in_both_places` | 加牌问句与奖励屏各 +2 上限；**没有遗物 ⇒ `UnsupportedRelic` 且整局不变**；奖励屏第二次调 ⇒ `EmptyOffer` |
| `a_full_deck_refuses_the_pick_without_eating_the_debt` | 满牌组 ⇒ `Capacity`，**欠账不被吃掉** |
| `the_pickup_add_round_trip_works_through_the_abi`（wasm） | 导出真能用：候选**有非空显示名**（不是 `#0`）、加牌真的动牌组、跳过一次递减 |
| `singing_bowl_trades_a_reward_card_through_the_abi`（wasm） | 奖励屏那条：有遗物 `0` + 上限 +2；没有遗物 `-2` 且上限不动 |
| `ui_test` 的 `pickup add cards` | 面板标题、每行的 `pickup_add_card` 与槽号、无遗物时**不画** +2 按钮 |
| `browser_test` 的 (l3) | **真点**：`giveRelic("orrery")` → 面板出现 → 点一行 ⇒ 牌组 +1、欠账 5→4；再给 `singing_bowl` ⇒ 按钮出现、点了上限 +2 |

### 293.5 ★ 负控抓到的第一个洞：「换一手」我根本没验

第一版 `orrery` 判据只数欠账（5→4→0），于是负控"挑完不换一手（同一手给两次）"**照样全绿** ——
而那条恰恰是这一节最容易写错的地方（忘了 `roll_pickup_offer`）。

修法：挑之前把 `pickup_offer()` 复制成 `Vec<String>`，挑完再复制一次，`assert_ne!`。
现在那条负控是红的。教训与 §4.20 同形：**"我检查了计数"不等于"我检查了那件事"**。

### 293.6 账

内容遗物 **127 → 130**（缺 66 → 63）；镜像 **163,060 B**；`rd-core` 797 / `rd-run` 181（+4）/
`rd-wasm` 140（+2）；矩阵 839 行；八道页面门 + `SOAK`；21/21。

负控 6 条全红（`orrery` 不记欠账 / 挑完不换一手 / 满牌组吃掉欠账 /
`singing_bowl` 无遗物也放行 / 奖励屏不花掉卡牌行 / `tiny_house` 只给金币）。

### 293.7 还差什么

* `orrery` 的 5 次挑选在真 StS 里是**5 张独立的奖励屏**（可以看牌堆、可以跳过）；
  我们的问句压在一个面板上（"还要选 N 张"），跳过一次就少一张 —— 语义一致，界面更紧。
* `singing_bowl` 在**事件**里"加牌"的场合（`card:<id>` / 诅咒之外的给牌）没有挂上去：
  今天只有战斗奖励与这两个拾取问句有这条路。这是**已知的不对称**，不是遗漏。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
        plan.rstrip('\n') + '\n' + DOC)

    plan2 = io.open(PLAN, encoding='utf-8').read()
    marker = '''**B. 运行层还差一个"拾取时让玩家挑一张牌加进牌组"的问句**（一次做，三件受益）：

`tiny_house`（50 金币 +5 上限 +1 药水 +1 张牌）、`orrery`（选 5 张）、`singing_bowl`
（加牌时可以不拿牌、改 +2 上限）。今天的 `PickupPick` 只能"选**已有**的一张去删/升/改"，
不能"从候选里**加**一张"。'''
    assert plan2.count(marker) == 1
    plan2 = plan2.replace(marker, '''**B. 加牌问句 —— §293 已做**：`orrery` / `tiny_house` / `singing_bowl` 走
`pickup_add` + `pickup_offer`（与 `pickupPicks` 同一条形状的欠账通道），`singing_bowl`
在战斗奖励屏上也有一条"换成 +2 上限"。''')
    io.open(PLAN, 'w', encoding='utf-8', newline=chr(10)).write(plan2)

    g = io.open(GAP, encoding='utf-8').read()
    marker2 = '''### F.12 遗物：Wave 1 与 `Shop` 档（§292）'''
    assert g.count(marker2) == 1
    g = g.replace(marker2, '''### F.13 遗物：加牌问句（§293）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `orrery` | 拾取时挑 5 张加入牌组（5 张独立奖励屏） | **已做**（一个面板"还要选 N 张"，可跳过） | 一致（界面更紧） |
| `tiny_house` | +50 金、上限 +5、1 瓶药水、1 张牌 | **已做** | 一致 |
| `singing_bowl` | 加牌时可以不拿牌、改 +2 上限 | **已做**（战斗奖励屏 + 两个拾取问句） | 一致 |
| `singing_bowl` 在**事件**给牌的场合 | 同样可换 | **没挂**（事件给牌不走"加牌问句"） | **偏差**（已知不对称） |

### F.12 遗物：Wave 1 与 `Shop` 档（§292）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§292）', '（主计划 §1–§293）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
