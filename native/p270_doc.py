"""§270 文档 + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §270 轻资产档（二）：**加牌类** 6 件 + **金币/商店类** 5 件

### 270.1 `push_card` 拿到了整张 `PoolCard`（这一批的全部基建）

三个蛋的规则是"加**这种类型**的牌 ⇒ 换成它的 `+` 行"，`omamori` / `darkstone_periapt` 的规则是
"**诅咒**"。类型在内容里是 **tag**（`attack`/`skill`/`power`/`curse`），运行层原本看不到 ——
所以把"这张牌是什么"放进 `PoolCard`，而不是让 13 个调用点各自判断：

```rust
pub struct PoolCard<'a> {
    pub id: &'a str,
    pub rarity: Rarity,
    pub kind: CardKind,           // §270：内容里的 attack/skill/power/curse/status
    pub upgraded: Option<&'a str>, // §270：它的 `+` 行（由 `upgraded_id` 解析）
}
```

两处刻意的"只有一个来源"：

* **`+` 行**由 `upgraded_id`（A12 奖励升级用的就是它）在 `full_pool` 那一趟填好，**不是**
  `push_card` 自己拼 `id + "+"` —— 拼错了就是把一张内容不认识的牌塞进牌组，而那种错不会报错。
* **类型**由 `Content::card_tag_bits`（"tag → 位图"的唯一映射，`exec::CARD_HAS_TAG_*` 用的也是它）
  翻译成 `CardKind`，wasm 侧没有第二份类型词表。

`take_card(slot, card)` / `buy_card(slot, card)` 现在要求调用方把"那一张牌"带进来，并**校验**
它与屏幕上那一格是同一个 id：两个来源必须对得上（否则"点第 1 张拿走第 3 张"，而页面只显示结果）。

### 270.2 加牌类

| 遗物 | 稀有度 | wiki 原话 | 在 `push_card` 里做什么 |
|---|---|---|---|
| `omamori` | Common | "Negate the next 2 Curses you obtain." | 诅咒且还有次数 ⇒ **不加入**、次数 -1（这是**成功**） |
| `darkstone_periapt` | Uncommon | "Whenever you obtain a Curse, increase your Max HP by 6" | 加入之后上限 +6 |
| `molten_egg` | Uncommon | "Whenever you add an Attack card…, Upgrade it." | 类型对上 ⇒ 换成 `+` 行 |
| `toxic_egg` | Uncommon | "…a Skill card…" | 同上 |
| `frozen_egg` | Uncommon | "…a Power card…" | 同上（内容有 22 张 power 牌，这条**会**真的触发） |
| `ceramic_fish` | Common | "Whenever you add a card to your deck, gain 9 Gold." | 加入之后走 `adjust_gold` |

⚠️ **顺序是规则的一部分**：`omamori` 在**最前**。被挡掉的诅咒不算"得到"，所以
`darkstone_periapt` 不该加上限、`ceramic_fish` 也不该给钱。换一下顺序，`omamori` 就变成一个
"付 6 点上限加 9 金币"的遗物 —— 而两条判据都只测各自的数字，看不出这件事。
判据里专门有一块"两件一起拿、诅咒被挡 ⇒ 上限不动"。

### 270.3 金币 / 商店类

| 遗物 | 稀有度 | wiki 原话 | 落点 |
|---|---|---|---|
| `bloody_idol` | Event | "Whenever you gain Gold, heal 5 HP." | `adjust_gold`：金币**真的**涨了才回血 |
| `ectoplasm` | Boss | "Gain 1 Energy… You can no longer gain Gold." | `adjust_gold` 把正增量变 0 + 能量状态载体 |
| `maw_bank` | Common | "Whenever you climb a floor, gain 12 Gold. No longer works when you spend any Gold at a shop." | `enter_node`（楼层涨了）+ `maw_bank_broken` |
| `smiling_mask` | Common | "…card removal service now always costs 50 Gold." | `remove_card_price` 的固定档 |
| `membership_card` | Shop | "50% discount on all products!" | 新的 `shop_price(base)` |

三处刻意的决定：

**(1) `bloody_idol` 判的是"实际涨了多少"，不是 `delta > 0`。**
否则 `ectoplasm` 挡住的那一笔也会回血 —— 玩家没得到金币却回了 5 点血，而两个数字各自都"合理"，
页面上完全看不出来。判据里那条"两件一起 ⇒ 不回血"就是为了钉住它。

**(2) 折扣只有一个函数。**
货架上存的是**挂牌价**（`roll_shop` 在陈列时就把 A16 的涨价算进去了，见那里的注释），折扣**只在
付款时**算 —— 所以 `rd_run_shop_card_price` / `rd_run_shop_relic_price` / `buy_*` /
`remove_card_price` 全部走 `shop_price`。两条路各算一次，就会变成"显示 45 扣 90"。

**(3) 删牌价格的三个来源是三项，不是一个数。**
升阶的 +25/次、`smiling_mask` 的固定 50、商店折扣各自独立：`smiling_mask` 之下 `removed_cards`
不再参与（"always costs 50"），而折扣仍然在（那是另一件遗物）。

### 270.4 两个新的运行期计数器（`RunState` + 指纹 + 存档 v4）

| 字段 | 语义 | 为什么必须进指纹 |
|---|---|---|
| `omamori_charges: u8` | 还剩几次挡诅咒（0..=2） | "还剩 1 次"与"还剩 2 次"是两条规则的全部区别 |
| `maw_bank_broken: bool` | 在商店花过钱 ⇒ 失效 | 同上 |

存档 `VERSION` 3 → **4**。为什么必须抬版本而不是"末尾多写两个字节"：旧存档读到末尾会缺字段，
而"缺字段"与"字段是 0"在字节上无法区分 —— 那正是版本号要回答的问题。读到 `omamori_charges > 2`
是 `BadField`（**存档坏了**，不是夹到 2）。

`RELIC_SECOND_HALVES`（§269 的 `EXTRA_REWARD_CARD_DELTAS` 升级而来）：一件遗物要做两件事、
而 `relic_effect` 只返回一个变体时，第二半写在这张**唯一**的表里 —— 两个消费者各自挑自己认识的
变体、忽略其余。现在表里两条：`busted_crown`（奖励卡数 -2）、`ectoplasm`（每回合 +1 能量）。

### 270.5 没做的两件（写下来而不是绕过去）

* `singing_bowl`（"When adding cards to your deck, you **may** raise your Max HP by 2 instead"）
  是一个**运行层的问句**；`PendingChoice` 目前只存在于战斗里。归中资产。
* `the_courier`（"restocks … all prices are reduced by 20%"）里的 -20% 已经能在 `shop_price` 里
  表达，但"补货"要一个商店刷新动作。折扣那一半归轻资产、补货那一半归中资产 —— **拆开做会让
  同一件遗物有两处认识**，所以整件留着。

### 270.6 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `the_add_card_relics_fire_at_the_one_add_point` | omamori 挡 2 个**且**非诅咒一次都不挡/不吃次数；darkstone 只认诅咒；两件一起 ⇒ 被挡的诅咒**不加上限**；三个蛋各自升自己那一类、别的类型原样、没有 `+` 行不报错；ceramic_fish 加任何牌 +9、被挡的诅咒不给钱 |
| `the_gold_and_shop_relics_change_only_their_own_number` | ectoplasm 拦正增量但**花出去不受影响**且能量载体仍在（逐条比 id）；bloody_idol 只在金币真涨时 +5、与 ectoplasm 一起时不回血；maw_bank 爬两层各 +12、没有这件不加钱；smiling_mask 固定 50；membership_card 半价 |
| `a_discounted_purchase_charges_the_discounted_price` | 真买一次：扣的是 `shop_price(挂牌价)`（**比挂牌价少**）、`maw_bank` 从此失效、失效后爬层不给钱 |

**负控**（`native/p270_negative.py`，跑完自动还原）：三处切口各改一次，必须看到 `FAILED`。

| 切口 | 结果 |
|---|---|
| `omamori` 不再"拦下就返回"（拦了但还是加牌） | RED ✓ |
| `adjust_gold` 改成"先按原始参数回血、再拦金币" | RED ✓ |
| `shop_price` 的折扣改回 100% | RED ✓ |

⚠️ 负控本身错过两次，值得记下来：前两版把变异插在 `let delta = if … {0}` **之后**，
那里 `delta` 已经被清零，所以判据当然还是绿的 —— **负控没变红先怀疑负控**。

### 270.7 一处容量常量被内容撑爆

`browser_test` 的全幕回放报"回放脚本 25,983 字节，超过缓冲容量 24,576"：`MAX_SCRIPT` 的注释
写着"24 KiB ≈ 10x headroom"，那是脚本还只有 2.4 KB 时量的。抬到 48 KiB，并把实测数字写进注释。
这条常量**随内容增长而变**，所以每次内容变大之后都要用真实回放验证一次，而不是相信注释里的倍数。

### 270.8 账

遗物 **89 → 100 件**；`rd-core` 788 / `rd-run` **132** / `rd-wasm` 120；内容 122 状态 / 100 遗物；
镜像 144,028 B（core 110,972 B）；四条对拍全过；`ACT1_SLICE` / `SOAK` / `MAP_RENDER` /
`BROWSER_TEST` PASS；`COVERAGE_MATRIX` 771 行 / 1042 测试；21/21。
"""


def main():
    doc = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(doc.rstrip('\n') + '\n' + DOC)

    s = io.open(README, encoding='utf-8').read()
    s = s.replace('* **遗物**：**89 / 193**', '* **遗物**：**100 / 193**')
    s = s.replace('所以缺的 104 件', '所以缺的 93 件')
    s = s.replace('/ 121 状态 /', '/ 122 状态 /').replace('/ 89 遗物 /', '/ 100 遗物 /')
    s = s.replace('143,316 B 的 `rdcf` 镜像（core 镜像 110,504 B）。',
                  '144,028 B 的 `rdcf` 镜像（core 镜像 110,972 B）。')
    s = s.replace('（主计划 §1–§269）', '（主计划 §1–§270）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(s)
    print('doc §270 + README')


main()
