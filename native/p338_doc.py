"""§338 的 port-plan 章节。

八轮 Review（`docs/vibe/Review_094d34e_c448ff0_08_Act.md`）的 1.1 / 1.2 / 1.3 与复核 B1，
一次提交解决。这一节写清"为什么三处必须一起改"，以及**为什么旧测试看起来是对的**。
"""

import io

PATH = 'docs/port-plan.md'

SECTION = """
## §338 商店价格与交易时序：三处一起改才算修完

八轮 Review 的三条 P1 落在同一段代码上，而且**互相咬住**：只修一条会让另外两条更难看见。

### 三件事

| # | 症状 | 根因 |
|---|---|---|
| 1.1 | 页面按折后价启用按钮，内核按挂牌价拒绝 | `buy_*` 用 `offer.price` 校验、用 `shop_price(offer.price)` 扣款 |
| 1.2 | 双折扣算成 30% 而不是 40% | `percent -= discount`（加法），且 `base * percent / 100` **截断** |
| 1.3 | 买 `membership_card` 时它给自己打折 | `buy_relic` 先 `push_relic` 再 `shop_price` |

### 1.1 的真实后果不是"少买一次"

`rd_run_shop_card_price` 走的就是 `shop_price`（§270 的注释明说"显示价 = 折扣价"），所以持有
`membership_card`、金币 60、货架 100 时：

* 页面按 **50** 判断"买得起" ⇒ **按钮是启用的**；
* 点下去被拒，回一句 `NotEnoughGold { price: 100, gold: 60 }`。

**屏幕上写着 50，内核说 100 不够。** 这是本项目最恨的形态（"显示一个数、内核用另一个数"），
比"按钮干脆禁用"糟得多。所以判据里必须有一条：**页面显示价 == 扣款价**。

### 修法

```rust
// ① 折扣乘法叠加 + 最后 ceil 一次
let mut numerator = 1i64; let mut denominator = 1i64;
for ... ShopDiscountPercent(discount) {
    numerator *= i64::from(100 - discount.clamp(0, 100));
    denominator *= 100;
}
((base as i64 * numerator + denominator - 1) / denominator) as i32

// ② 四类 buy_*：due 在**任何 push_* 之前**冻结，校验 / 错误消息 / 扣款全用它
let due = self.shop_price(offer.price);
if self.gold < due { return Err(RunError::NotEnoughGold { price: due, gold: self.gold }); }
...
self.adjust_gold(-due);
```

`shop_price(-1)` 现在**原样返回 -1**（售罄哨兵不过折扣）。原来那句 `.max(0)` 会把它变成 0，
于是页面把卖掉的格子画成"0 金可买"—— §276 在 ABI 那一侧已经挡过一次，这是第二道。

### 为什么"一次 ceil"而不是"每个折扣各 ceil 一次"

`107` 是分水岭：`ceil(107*0.4) = 43`，而 `ceil(ceil(107*0.5)*0.8) = ceil(54*0.8) = 44`。
wiki 把公式写成一次性的 `0.5 * 0.8 = 0.4`，所以按有理数相乘、最后取整一次。

取整方向是**向上**：wiki 自己举了 `101 * 0.5 = 50.5 → 51`。顺带修正了删卡服务：
`75 * 0.5 = 37.5 → 38`，旧断言写的是 `SHOP_REMOVE_BASE / 2 = 37`（截断）。

### ★ 旧测试把错公式写成了规范

`the_courier_restocks_the_slot_it_sells` 里那句
`assert_eq!(run.shop_price(100), 30, "the two discounts add up (50 + 20)")`
不是"漏测"，是**把错的行为写成了期望值**。只改实现不改它，修完反而红，而红的样子像是
"实现改错了"。同类还有 `SHOP_REMOVE_BASE / 2`。

⇒ 一条通用教训：**预期值不许用生产函数生成**，也不许"照着当前输出抄"。新判据
`shop_discounts_stack_multiplicatively_and_round_up` 全部用字面量（`100→50/80/40`、`101→51`、
`99→50`、`107→43`、`75→38`）。

### 判据

| 判据 | 钉住什么 |
|---|---|
| `shop_discounts_stack_multiplicatively_and_round_up` | 乘法 + 一次 ceil + 售罄哨兵穿过去（全字面量） |
| `every_purchase_charges_the_price_the_page_shows` | 四排各一次：`gold = due-1` 被拒且**错误里的数 == 页面显示的数**；`gold = due` 成交且金币归零；被拒时牌组/金币一个字节都不动 |
| `buying_the_discount_relic_does_not_discount_itself` | 挂牌 100、金币 150 ⇒ 买 `membership_card` 扣 **100**（不是 50），随后另一格显示 50 |

负控 3/3（`native/p338_negative.py`）：折扣改回加法 / 校验改回挂牌价 / `due` 挪到 `push_relic`
之后，三条判据**各自**变红（不是"有测试红了就算"—— 每条都钉住指定的测试名）。

### 待核偏差（**没有**照单全收）

fandom 说 Courier 与 Membership Card 在**删卡服务**上"取更好的那一个折扣"（⇒ 50%），
wiki.gg 说 Courier 对删卡"照常"生效（⇒ 40%）。**两源互斥，单源不足以定规则**，所以这里
不为删卡开特例，统一走 `shop_price`。记在这里，等第三个来源或实测。

### 数字

`rd-run 218`（215 + 3）、`rd-core 819`、`rd-wasm 182`、units **1219**（下限 1216 → 1219）；
四条对拍不动；`WEB_SMOKE PASS`；23/23 闸门。
"""

t = io.open(PATH, encoding='utf-8').read()
assert '## §338' not in t
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + '\n' + SECTION)
print('port-plan §338 added')
