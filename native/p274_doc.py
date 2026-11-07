"""§274 文档（port-plan）+ README 数字。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §274 拾取类 7 件 + 两份文档整理

### 274.1 `push_relic` 现在要卡池

四件拾取要看**牌的类型**与 **`+` 行**（`war_paint` 只升 Skills、`whetstone` 只升 Attacks、
`pandoras_box` 认 Strike/Defend、`astrolabe` 改造后还要升级），而运行层只存牌 id。

所以 `push_relic(&mut self, relic_id, pool: &[PoolCard])` —— 与 §270 的 `push_card(PoolCard)`
同一条纪律：**内容的事在有内容的那一层解析**，运行层不猜 `id + "+"`。
池子沿着既有签名流进去：`open_chest(card_pool, relic_pool)`、`buy_relic(slot, card_pool, relic_pool)`、
`take_relic(pool)`；`resolve_event` 本来就有 `pool`。

### 274.2 七件

| 遗物 | 稀有度 | 原文 | 落点 |
|---|---|---|---|
| `old_coin` | Rare | "Upon pickup, gain 300 Gold." | `adjust_gold`（`ectoplasm` 该拦就拦、`bloody_idol` 该回血就回血） |
| `lees_waffle` | Shop | "…raise your Max HP by 7 **and heal all** of your HP." | 上限 +7 **且**回满（不是"回 7 点"） |
| `war_paint` | Common | "Upgrade 2 random Skills." | 随机升级 2 张 Skill |
| `whetstone` | Common | "Upgrade 2 random Attacks." | 随机升级 2 张 Attack |
| `pandoras_box` | Boss | "Transform all Strike and Defend cards." | 逐格改造（命中时下标**不动**） |
| `astrolabe` | Boss | "Transform 3 cards, then Upgrade them." | 欠 3 次 `TransformAndUpgrade` |
| `empty_cage` | Boss | "remove 2 cards from your deck." | 欠 2 次 `Remove` |

### 274.3 两件"要玩家选"的走**新通道**，不抢 `pending`

`astrolabe` / `empty_cage` 在 StS 里是一个选择屏。我们的 `pending` 是**一个槽**、而且
"一个流程一个写者"（奖励屏/宝箱/事件各写一次），所以在 `push_relic` 里改 `pending` 会把玩家
正看着的那一屏顶掉 —— 最真实的那条路径是"打完 Boss 拿 Boss 遗物，然后还想拿卡牌奖励"。

所以它们记在 `pickup_change: Option<DeckChange>` + `pickup_picks: u8`（"欠着几次牌组编辑"），
`pending` 一个字节都不动；页面在 `pickupPicks > 0` 时**优先**画选择面板（`describe` 的第一条分支），
选完自然回到原来那一屏。判据 `the_pickup_picks_do_not_take_over_the_screen` 钉的就是这件事。

⚠️ `pickup_card` 的"拒绝"必须在**扣额度之前**：越界/Ascender's Bane/没有 `+` 行都先验。
反过来的话一次被拒的点击会白吃一次额度 —— 负控第 4 条专门打这个。

### 274.4 两处"同一个事实两种查法"被这一批暴露

**(1) `upgraded_id` vs `PoolCard::upgraded`。** `upgraded_id` 按**命名**在池子里找 `+` 行
（要求池子里同时有基础行与 `+` 行），而 `PoolCard::upgraded` 是 §270 引入的字段。
`whetstone` 第一版用前者 ⇒ 池里只有基础行时**静默升 0 张**，而"技能不动"那条照样绿。
修法：`upgraded_id` **先读字段**、字段缺席才按命名回落 —— 一处实现、一个顺序。

**(2) `pandoras_box` 的 off-by-one。** 命中后 `index += 1` 会跳过被 `remove_at` 前移过来的那张，
5 张基础牌只改 2 张。命中时下标**不动**。

### 274.5 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `the_pickup_number_relics_change_only_their_own_number` | `old_coin` +300（与 `ectoplasm` 一起时 **0**）；`lees_waffle` +7 上限**且回满** |
| `the_upgrade_eggs_upgrade_two_of_their_own_kind` | `whetstone` 升 2 张 Attack、Skill **0**；`war_paint` 反之；只有 1 张可升就升 1 张；**已升级的不吃名额** |
| `pandoras_box_transforms_every_staple_and_nothing_else` | Strike/Defend 全没了、别的牌一张不动、总数不变 |
| `the_pickup_picks_do_not_take_over_the_screen` | `empty_cage` 欠 2、`astrolabe` 欠 3，**`pending` 始终是 `Reward`**；越界拒绝**不扣额度**；`astrolabe` 改造出来的那 3 张**是升级版** |

**负控**（`native/p274_negative.py`）：`old_coin` 绕过 `adjust_gold`、升级不看类型、
`pandoras_box` 的 off-by-one 回来、`pickup_card` 先扣额度再验 —— 四处全 RED ✓。

### 274.6 两份文档（本次的第二、三件事）

1. **新写 `docs/function_scaling_up_for_relics.md`** —— 与 `..._for_cards.md` 同构：
   固定节拍、文件地图、**节次索引（§259–§274 每节拿到了什么载体）**、内容硬规则、
   **载体决策树**、七个结构陷阱、判据三要求 + 负控表、工具骗人的形态、
   以及"115/193 的现状与剩下 78 件的分档"。
2. **README 的遗物细节搬到 `docs/sts-wiki-gap.md` §D.2**，README 只留统计数字 + 两个指针。
   理由：README 是"现在有什么"，"某件遗物靠哪条管线成立、还缺哪块载体"属于缺口文档。

### 274.7 一处 id 事故（值得记）

`Lee's Waffle` 我先写成 `lee's_waffle`（带撇号），而 wiki 的 id 是 **`lees_waffle`**。
症状是内容门那句"内容里有 1 条内核不认识" —— 看起来像"内核漏了一件"，其实是 id 不一致。

### 274.8 账

遗物 **108 → 115 件**（`IMPLEMENTED: … 内核不认识` = **0**）；`rd-core` 788 / `rd-run` **146** /
`rd-wasm` 123；内容 124 状态 / 115 遗物；镜像 145,220 B（core 111,772 B）；
存档 `VERSION` 6 → **7**；四条对拍全过；四道页面门 PASS；`COVERAGE_MATRIX` 788 行；21/21。
"""


def main():
    doc = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(doc.rstrip('\n') + '\n' + DOC)

    s = io.open(README, encoding='utf-8').read()
    s = s.replace('145,220 B', '145,220 B')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(s)
    print('§274 doc written')


main()
