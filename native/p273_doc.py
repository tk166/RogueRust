"""§273 文档 + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §273 商店族收尾：**一个 `enter_shop`** + `the_courier`

### 273.1 先记一个**核对结果**（避免重复劳动）

StS1 的 `?` 房那一族（`wiki Module:Relics/data` 里描述含 `?` 的行）**只有三件**：

| 遗物 | 状态 |
|---|---|
| `juzu_bracelet` | §272 已做 |
| `tiny_chest` | §272 已做 |
| `ssserpent_head` | §271 已做 |

`Planisphere`（"? 房回 5 血"）与 `Golden Compass`（"Act 2 的 `?` 房全是事件"）是 **StS2** 的
遗物，离线 dump 的 193 行里**两个都没有** —— 所以这一族 3/3 已经做完，不再是缺口。

真正还缺的是**商店那一侧**：`the_courier`，以及 §272 自己留下的一个缺口。

### 273.2 §272 的缺口：`?` 房掷出商人时 `meal_ticket` 不回血

`begin_node` 的两个分支是**两段代码**：`NodeKind::Shop` 摆货架 + 收 `meal_ticket` 的 15 血，
而 `UnknownRoom::Shop`（§272 新加的）只 `stock_shop`。于是"`?` 房变成商店"不回血 ——
而 wiki 的 Planisphere 页明写过这件事：

> Meal Ticket is the same idea for shop rooms, and **a ? that turns into a shop triggers both**.

修法不是"在第二个分支再抄一遍回血"，而是抽出一个 `enter_shop(card_pool, relic_pool)`：
摆货架 + 进门遗物，**两个调用方共用**。判据钉的就是"两条路都要付"。

### 273.3 `the_courier`（Uncommon）：两个半

| 半 | wiki | 落点 |
|---|---|---|
| 折扣 | "All prices are reduced by 20%" | `ShopDiscountPercent(20)`（与 `membership_card` 的 50% **相加** ⇒ 30%） |
| 补货 | "The Merchant restocks cards, relics, and potions" | 买走一格就**补一格**（`restock_card_slot` / `restock_relic_slot`） |

三处刻意的决定：

**(1) 补货是"补那一格"，不是"重摆整个货架"。** wiki 说的是 "restocks"，也就是"货架不会因为
你买了就变少"。重摆会把没买的货也换掉 —— 那是另一条规则（而且玩家会看着自己想要的货消失）。

**(2) 补货**不**保证"给你另一张"。** 第一版判据断言"补回来的牌必须与刚买的不同"，跑出来是红的 ——
而那说明的是**判据写错了**：没有任何来源说商人不能立刻把同一张再摆上来。改成钉真正的不变量：
**货架上活着的那几格不缩水、且不出现重复格**。（判据用的池子也因此要有 7 张 —— 3 张的池子被
5 格货架一次用尽，根本补不出来。）

**(3) 池子空了就把那一格留空**（`price = -1`），不是错误：那正是"商人的货卖完了"。
判据里有一条反面：`RELICS` 只有一件遗物，买走之后没得补 ⇒ 那一格必须是空的（补货不能凭空造货）。

⚠️ **药水那一半没做**：本内容的商人**不卖药水**（没有药水货架），所以 "restocks … potions" 的
那三分之一无处可落。这是既有缺口（§254 记过），不是这一节新漏的。

### 273.4 接口变化：`buy_card` / `buy_relic` 现在要池子

补货要从池子里抽，所以两个函数的签名各多一个参数（`card_pool` / `relic_pool`）。
没有 `the_courier` 时它们不被读到 —— 但"一处规则、一个入口"比"多一个重载"重要。
`rd-wasm` 的两个 ABI 各自把池子造好传进来（`full_pool` / `relic_pool`）。

### 273.5 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `an_unknown_room_that_becomes_a_shop_pays_the_shop_entry_relics` | `?` 房掷出商人 ⇒ `Pending::Shop` + 货架已摆 + **`meal_ticket` 回 15**；没有这件遗物时不回血；`stock_shop` 单独调用**不**回血（把 `enter_shop` 的分工钉住） |
| `the_courier_restocks_the_slot_it_sells` | 20% 折扣、与 `membership_card` 相加成 30%；买走两格后**货架不缩水**且**无重复格**；没有这件遗物时那一格 `-1`；遗物池空了补不出来 |

**负控**（`native/p273_negative.py`）：`?`→商店 退回 `stock_shop`、`buy_card` 的补货去掉 ——
两处全 RED ✓。

### 273.6 账

遗物 **107 → 108 件**；`rd-core` 788 / `rd-run` **142** / `rd-wasm` 123；内容 124 状态 / 108 遗物；
镜像 144,872 B（core 111,528 B）；四条对拍全过；
`ACT1_SLICE` / `SOAK` / `MAP_RENDER` / `BROWSER_TEST` PASS；`COVERAGE_MATRIX` 781 行；21/21。
"""


def main():
    doc = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(doc.rstrip('\n') + '\n' + DOC)

    s = io.open(README, encoding='utf-8').read()
    s = s.replace('* **遗物**：**107 / 193**', '* **遗物**：**108 / 193**')
    s = s.replace('所以缺的 86 件', '所以缺的 85 件')
    s = s.replace('/ 107 遗物 /', '/ 108 遗物 /')
    s = s.replace('144,820 B 的 `rdcf` 镜像（core 镜像 111,492 B）。',
                  '144,872 B 的 `rdcf` 镜像（core 镜像 111,528 B）。')
    s = s.replace('（主计划 §1–§272）', '（主计划 §1–§273）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(s)
    print('doc §273 + README')


main()
