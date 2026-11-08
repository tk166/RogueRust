"""§300 文档：三个原子 + 三件遗物。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §300 三个原子，三件遗物（C 类补齐）

§299 剩下三件各缺一个原子。这一节把三个原子补齐 —— 每个原子**只为一件遗物**，但都是
内容侧从此可复用的能力。

| 原子 | 改动 | 解锁 |
|---|---|---|
| `offerRandomCards` 支持 `Then` | 把写死的 `ToHandFree` 换成查**同一张**词表 | `nilrys_codex` |
| `upgradeCards` 支持 `Random` | 取牌从"牌区顺序前 N 张"变成"随机 N 张" | `warped_tongs` |
| 新节点 `node.setCardCostOverride` | 给牌区的牌写 `standard.card_cost_override`（可随机） | `mummified_hand` |

### 300.1 ★ 词表只有一张：`choice_then_from_name`

`chooseCards` 有一张 `Then` 的词表（`ToDrawPileTop` / `ToDrawPileBottomFree` / `Copy` /
`Upgrade` / `Exhaust` / `ToHand`），而 `offerRandomCards` 把 `then` **写死**成 `ToHandFree`
—— 于是"三选一，塞进抽牌堆"（`nilrys_codex`）在内容里表达不出来，而词表其实早就有了。

改法不是"在 `offerRandomCards` 里再写一个 `match`"（那就是**同一个词表两处认识**），而是
把 `chooseCards` 那段抽成 `choice_then_from_name(name, node)`，两个节点都调它。

⚠️ **抽取时漏了 `PlayChosen`**（它原来只登记在 `offerRandomCards` 那个写死的 `match` 里）。
症状是 `Wish` 变成 `Ir(UnknownKind)`，而 `wish_offers_three_cards_and_plays_the_pick_at_once`
与 `wish_plus_offers_the_upgraded_options` **当场红**。这正是"合并两张表"该有的守门人：
少一个名字就有一件牌打不出来。

### 300.2 `upgradeCards{Random}`：随机账只推进**一次**

`Armaments` 的老行为是"按牌区顺序取前 N 张"。`warped_tongs` 要的是"手牌里**随机**一张"。
`Random: true` 时用 `shuffled_pick_index` 挑一个**起点**再顺序取 —— 这样随机账只推进一次，
`Random` 改变的是**结果**而不是"随机流被消费的次数"（后者会让同一颗种子的后续随机全漂）。

### 300.3 新节点 `node.setCardCostOverride`

`{OwnerSelector, FromZone?, Count?, Random?, Amount?}` —— 写 `standard.card_cost_override`
（§161.4 的绝对价，出牌付款后由内核清零）。在此之前只有 `createRandomCardInstance{CostZero}`
与内核的 `playTopCardOfDrawPile` 会写它，所以"给手牌里随机一张改价"表达不出来。

判据的形状照 `upgrade_cards_node`（同一个 owner 选择器 + 同一个"从哪个牌区取"），
两处**先读后写**：先把槽位快照出来，再改。

### 300.4 三件遗物

| 遗物 | 触发器 | 程序 |
|---|---|---|
| `nilrys_codex` | `TurnEnded` | `offerRandomCards{Count:3, Min:0, Max:1, Then: ToDrawPileTop}` |
| `warped_tongs` | `TurnStarted` | `upgradeCards{FromZone: Hand, Count:1, Random:true}` |
| `mummified_hand` | `CardPlayed`（牌带 `power`） | `setCardCostOverride{FromZone: Hand, Count:1, Random:true, Amount:0}` |

### 300.5 ★ 判据自己抓到的第二个"驱动形状"错误

`mummified_hand` 的判据第一版只把**要打的那一张**放进手牌 —— 打出之后手牌空了，
"随机一张手牌变 0 费"没有对象，于是判据红。而**原子本身没问题**：加一条诊断打印后能看到
`defend` 被正确标成 `card_cost_override=0`。

⇒ 与 §299 的 `dead_branch`（每次新建 arena ⇒ 抽到同一张）是同一族：**驱动形状**错了，
断言再对也没用。修法：判据里先铺两张手牌再打第三张。

### 300.6 判据与负控

| 判据 | 钉住 |
|---|---|
| `warped_tongs_upgrades_a_random_card_not_the_first_one` | 恰好一张被升级；**24 个 seed 下位置不唯一**（没有 `Random` 时恒为 0） |
| `mummified_hand_makes_one_random_card_free_after_a_power` | Power ⇒ 恰好一张免费；非 Power ⇒ 0 张；24 个 seed 下位置不唯一 |
| `nilrys_codex_asks_at_turn_end_and_sends_the_pick_to_the_draw_pile` | 回合末真的发问（3 候选、min 0、max 1）、`then == ToDrawPileTop`；无状态时不问 |

**负控 3 条全红**（都改内容再重编）：两件去掉 `Random` / `nilrys_codex` 去掉 `Then`。

### 300.7 已记录的偏差（gap F.20）

1. `nilrys_codex`：wiki 是"**洗入**抽牌堆"，而牌区只有 **Top / Bottom** 两个插入点 ⇒ 用**顶**
   （含义是"下一张就抽它"）。要真洗入得给 `ZonePlacement` 加第三种插入点。
2. `mummified_hand`：0 费写在那**一份副本**上、由出牌消费（与 §161.4 的 `ToHandFree`
   同一条已记录偏差），而不是"回合结束过期"。
3. `warped_tongs`：wiki 是"for the rest of combat"，而本内核的升级是**改定义 id** ⇒
   打完这一场就随战斗一起消失（正好等价，不需要清理）。

### 300.8 账

内容遗物 **143 → 146**（缺 50 → 47）；状态 **142 → 145**；镜像 **167,548 B**；
`rd-core` **809**（+3）/ `rd-run` 181 / `rd-wasm` 143；矩阵 871 行；
八道页面门 + `SOAK`；21/21。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§300 三个原子' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '''### F.19 遗物：C 类纯内容程序（§299）'''
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.20 遗物：三个原子（§300）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `nilrys_codex` | 回合末三选一，**洗入**抽牌堆 | **已做**，但进的是抽牌堆**顶** | **偏差**（牌区只有 Top/Bottom） |
| `warped_tongs` | 回合初随机升级手牌一张 | **已做**（`upgradeCards.Random`） | 一致 |
| `mummified_hand` | 打 Power ⇒ 手牌随机一张变 0 费 | **已做**（新节点 `setCardCostOverride`） | 一致（0 费由出牌消费，见 §161.4） |

### F.19 遗物：C 类纯内容程序（§299）''')

    old_rows = '''| `nilrys_codex` | 回合末三选一塞进抽牌堆 | **没做**：`offerRandomCards` 的收尾写死 `ToHandFree` | 缺原子 |
| `warped_tongs` | 回合初随机升级手牌一张 | **没做**：没有"手牌里随机一张"的选择器 | 缺原子 |
| `mummified_hand` | 打 Power ⇒ 手牌一张变 0 费 | **没做**：没有内容原子写 `card_cost_override` | 缺原子 |'''
    if g.count(old_rows) == 1:
        g = g.replace(old_rows, '''| `nilrys_codex` | 回合末三选一塞进抽牌堆 | **§300 已做**（`offerRandomCards.Then`；进**顶**不是洗入） | 已修 |
| `warped_tongs` | 回合初随机升级手牌一张 | **§300 已做**（`upgradeCards.Random`） | 已修 |
| `mummified_hand` | 打 Power ⇒ 手牌一张变 0 费 | **§300 已做**（新节点 `setCardCostOverride`） | 已修 |''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§299）', '（主计划 §1–§300）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
