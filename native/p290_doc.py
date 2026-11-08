"""§290 文档。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §290 `gold_all` / `card:<id>` / `The Nest`

§289 账上留的两个"缺原子"，加上它们的第一个真实用户。

### 290.1 `gold_all` —— 失去**全部**金币

wiki 的 `Masked Bandits` `[Pay]`："you lose **ALL** of your Gold"。它与 `gold_cost:<n>` 的区别
不是"数字大小"，而是**没有数字**：金额由局面决定（`self.gold`）。

* 写成 `gold_cost:0` 是错的（什么都不扣）；写成 `gold_cost:999` 也是错的（付不起 ⇒ 拒绝，
  而 wiki 的 `[Pay]` **永远付得起**）。
* 所以它是**裸词**：`gold_all`，走 `adjust_gold(-self.gold)`（`adjust_gold` 自己钳到 0）。

### 290.2 `card:<id>` —— 给**指定**的一张牌

`curse:<id>` 只能给诅咒（它**验**过池子里那一行是 `Rarity::Curse`）。有的奖励是**指定**的
普通/特殊卡 —— `The Nest` 的 `Ritual Dagger`（`Rarity::Special`）。所以：

    card:<card id>     任何稀有度都行（含 Special）

它**不写第二套加牌逻辑**：直接 `push_card`，于是 `omamori`（挡诅咒）、三个蛋（加牌升级）、
`ceramic_fish`（加牌给 9 金币）**照旧**生效 —— 判据用 `ceramic_fish` 证明这一点。

### 290.3 ★ 无色牌：一个开关，不是第二个池子

第一版 `card:ritual_dagger` 在真镜像上 `NoSuchCard`。根因不是词表，而是**池子**：

`full_pool`（商店与奖励共用）里有一条 §183/§185 的规则 ——"**无色牌不进牌组**"，当时的理由是
"这个内容没有无色入口"。`Ritual Dagger` 恰好是**无色**（`Tags: attack, colorless`），
于是它被剔掉了，`card:` 的校验（"这张在不在池里"）就失败。

修法：`full_pool(content, include_colorless)` —— **一个构造器 + 一个布尔参数**：

| 调用方 | 参数 | 理由 |
|---|---|---|
| 奖励屏 | `false` | 无色牌不进普通奖励池（§183 的原意） |
| 商店 | `false` | 与奖励同一条规则（`Masked Bandits` 的 `Red Mask` 那种"商店格"我们还没有） |
| **事件**（`rd_run_choose`） | `true` | 事件是"点名给这一张"，官方入口（`The Nest`） |

抄成两个池子构造器会让"商店卖不卖无色"与"事件给不给无色"漂成两个答案 —— 一个开关就没这事。

### 290.4 `The Nest`（Act 2，3 段）

    [Smash and Grab]  得 99 金币（A15 50）→ "They didn't even notice."
    [Stay in Line]    得 Ritual Dagger、掉 6 血 → 那一屏
    （没有"拒绝"选项 —— 两个都得选一个）

`Ritual Dagger` 本身早就在内容里（1 费、Special Attack、"Deal 15 damage. If Fatal,
permanently increase this card's damage by 3（+ 版 5）、Exhaust"），每副本成长
`standard.ritual_dagger_bonus` 也在 §253 实现过 —— 这一节只做"事件怎么给这张牌"。

### 290.5 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `gold_all_takes_everything_and_never_refuses`（run） | 有钱 ⇒ 归零；没钱 ⇒ 仍是 0（**不**报 `NotEnoughGold`） |
| `a_named_card_goes_through_the_one_add_card_path`（run） | 牌进牌组（Special 也能给）/ `ceramic_fish` 照旧给 9 金币（证明走 `push_card`）/ 拼错的 id ⇒ `NoSuchCard` 且**一个字节不改** |
| `the_nest_grants_the_dagger_and_the_gold`（wasm） | 走真镜像：金币 +99、牌进牌组、掉 6 血；A15 的 50 由内容判据钉 `EffectsAsc` |
| `the_unknown_room_events_are_readable`（core，§290 段） | `The Nest` 的两个选项、99/50、`card:ritual_dagger` + `damage 6`、两屏都有 `[Leave]` |
| 内容门 | `card:<id>` 的 payload 在 `Cards` 里（稀有度不限）；`gold_all` 不带 Amount |

**负控 3 条全 RED**：① `gold_all` 只扣固定 10；② 指名给牌绕过 `push_card`（`ceramic_fish`
不再给钱 ⇒ 判据红）；③ 事件池把无色牌剔掉（`The Nest` 的匕首选项变成死按钮）。

### 290.6 账

事件 **18 → 19**；step **74 → 77**；镜像 **162,144 B**（core 128,112 B）；
`rd-core` 797 / `rd-run` **166** / `rd-wasm` **135**；八道页面门 + `SOAK`；21/21。

### 290.7 还没做的

* `Masked Bandits`（`gold_all` 的真实用户）：仍缺三个**名册外**的敌人（`Pointy` / `Romeo` /
  `Bear`）与 25-35 金币的**区间**覆盖（今天只有定数 `fight_gold_set`）。
* `The Nest` 的 `Ritual Dagger` 是**未升级**的；wiki 的 Relic 影响（`Toxic Egg` 之类把事件牌
  升级）走的是 `push_card` 的同一套规则，所以有蛋时它会变成 `ritual_dagger+` —— 这是
  **同一条路**的副作用，不是新规则。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '### G. ★ 基础值偏差'
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.10 事件的两个原子（§290）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `The Nest` `[Smash and Grab]` | 99 金币（A15 50） | **已做** | 一致 |
| `The Nest` `[Stay in Line]` | 得 Ritual Dagger、掉 6 血 | **已做**（`card:<id>` 的第一位用户） | 一致 |
| `Ritual Dagger` 卡面 | 1 费 Special、15 伤害、Fatal 永久 +3（+5）、Exhaust | 内容里早就有；每副本成长 `standard.ritual_dagger_bonus` | 一致 |
| `Masked Bandits` `[Pay]` | 失去**全部**金币 | **原子已做**（`gold_all`），内容未接 | 缺：三个名册外敌人 + 25-35 的区间覆盖 |
| 无色牌的入口 | 事件 / 药水 / 商店无色格 | 事件与无色药水有；商店无色格没有 | 缺 |

### G. ★ 基础值偏差''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§289）', '（主计划 §1–§290）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§290 doc')


main()
