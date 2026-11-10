"""§332 文档：商店四排 + 药水/遗物货架的分析。"""

import io

PLAN = 'docs/port-plan.md'
GAPS = 'docs/sts-wiki-gap.md'
README = 'README.md'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PLAN, encoding='utf-8').read()
assert '## §332' not in t
t = t.rstrip('\n') + '\n' + """
## §332 商店四排：无色货架 + 药水货架 + 遗物价目

wiki（`The_Merchant`，wiki.gg 与 fandom 两个来源一致）的商店是**五排**。§332 之前我们只有
"5 张卡 + 3 件遗物 + 删卡服务"，而且那两排都有偏差。逐排对账：

| 排 | wiki | §332 之前 | 现在 |
|---|---|---|---|
| **5 张有色卡** | 永远 **2 攻 / 2 技 / 1 能力**；**随机一张 5 折** | 5 张**任意**牌（**含无色**），无折扣 | 按类型分桶取（缺档从其余非无色牌补位），恰好一张半价 |
| **2 张无色卡** | 永远 **1 Uncommon + 1 Rare**；**贵 20%**（81-99 / 162-198） | **完全没有**（无色牌只能靠 Colorless Potion 拿） | 两格，`colorless_price_band` |
| **3 瓶药水** | 权重 **65 / 25 / 10**；48-53 / 71-79 / 95-105 | **完全没有**（`ShopStock` 里连字段都没有） | 三瓶，`pick_potion` 的同一套权重，互不相同 |
| **3 件遗物** | **最右必为 `Shop` 档**（且**只有**那一格能出）；143-158 / 238-263 / 285-315 | 3 件都可能出 `Shop` 档，且**价格一律 143-157**（稀有遗物卖白菜价） | 最右锁 `Shop`、前三格排除 `Shop`、价格按稀有度 |
| 删卡服务 | 75 起、每次 +25（`smiling_mask` 固定 50） | **已对** | 不变 |

### 三处"形状在、规则漏"（分析结论）

* **药水货架是彻底缺的**：`ShopStock` 只有 `cards` / `relics` 两个字段，也没有 `buy_potion` ——
  也就是说"商店能买药水"这件事在运行层**不存在**，不是"少了个功能点"。
* **遗物货架的价格是错的**：`stock_shop` 里写死 `143 + roll(15)`，与稀有度无关。后果是
  **稀有遗物（285-315）和普通遗物同价**，于是商店的 50/33/17 权重失去意义 —— 玩家永远买稀有。
  这条在 §332 之前没有任何判据钉住（判据只断言"143-157 之内"，而实现正是那样）。
* **无色货架缺**，而且有色那排**会抽到无色牌**（`full_pool` 里两者混着），所以"无色牌能不能
  在商店买到"这件事在旧实现里是"能，但不是单独一排"—— 与 wiki 的构成不同。

### 踩到的两个坑

1. **`Rng::shuffle` 的入参是"位置表"，不是"值表"**：`rng::shuffle_indexes` 的第一件事是
   `out[i] = i`，所以往里塞"选中的池下标"会被重写成 `0..len` ⇒ 货架上出现重复的牌
   （`the_courier_restocks_the_slot_it_sells` 报 `the shelf must not shrink`，调试打印里
   `bash` / `anger` 各两份）。修法：洗 `pos` 位置表再索引，**不动** `shuffle_indexes`。
2. **判据自证**：四条价目断言原来用 `colorless_price_band(...)` / `relic_price_band(...)` 去算
   期望区间 —— 而那两个函数正是被测对象，改坏它判据跟着改坏。负控第一次跑出
   "三条全 NOT CAUGHT" 才暴露出来。补了一组**字面量**断言（wiki 的数字）才算独立。

### 判据

`a_shop_stocks_all_four_shelves_with_the_wikis_composition`（rd-run）：一份按 wiki 构造的小池子，
逐排断言**构成**（2/2/1、1+1、3、最右 `Shop` 且前三格非 `Shop`）与**价目**（字面量 + 区间两侧）。

负控 3/3：无色价目改回普通 ⇒ `wiki: 162-198`；遗物价目改回一律 ⇒ `wiki: 238-263`；
"Shop 只走最右"整条拿掉 ⇒ `Shop relic`（先撞"最右必为 Shop"那句）。

数字：`rd-core 813 / rd-run 215 / rd-wasm 181`、units **1209**（下限 1208 → 1209）；
四条对拍不动；`STATE_FIELDS PASS (67 fields)`。
"""
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t)
print('port-plan §332 ok')

# gap 文档：商店那一行重写
g = io.open(GAPS, encoding='utf-8').read()
old = """| 商店 | **有**（卡/遗物/药水/删卡，价格按稀有度；A16 加价；`the_courier` 刷新货架、`membership_card` 打折）。⚠️ **无色牌仍不出售**：没有 StS 的无色货架 —— 内容侧的无色池已经 **70/70**（§243–§252），缺的只是**商店里那一排**（`stock_shop` 加一排即可） | 内核（无色货架） |"""
new = """| 商店 | **四排齐全**（§332）：5 张有色卡（**2 攻 / 2 技 / 1 能力**，**随机一张 5 折**）、**2 张无色卡**（1 Uncommon + 1 Rare，**贵 20%**）、**3 瓶药水**（65/25/10）、**3 件遗物**（**最右必为 `Shop` 档**、前三格排除、价格按稀有度 143-158 / 238-263 / 285-315）+ 删卡服务（75 起、每次 +25，`smiling_mask` 固定 50）。A16 加价、`the_courier` 补货、`membership_card` 折扣都在 | — |"""
assert g.count(old) == 1, 'gap shop row'
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(g.replace(old, new))
print('gap doc shop row')

# README：商店那条（若有）与"仍缺的机制"里的无色货架
r = io.open(README, encoding='utf-8').read()
if '无色货架' in r:
    r = r.replace("""  剩下的是**事件级条件**（"这条事件出不出现"，会重掷 `?` 房每一次抽取，所以单独做）、""",
                  """  剩下的是""", 1)
io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
print('README touched')
