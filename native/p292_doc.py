"""§292 文档：Wave 1 的十一件 + `Rarity::Shop` 的既有缺口 + 剩下 30 件各自缺什么。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §292 轻/中资产遗物 Wave 1：十一件 + 一个**既有的静默缺口**

`docs/sts-wiki-gap.md` D.2 把剩下 77 件按"缺哪块载体"分了档。这一节做掉**运行层**那一批
（不需要动战斗语义的），并在摸底时挖出一个**早就存在、没有任何闸门会红**的缺口。

### 292.1 ★ 摸底发现的既有缺口：`Shop` 稀有度**根本不存在**

`Rarity` 枚举里只有 `Basic/Common/Uncommon/Rare/Status/Curse/Event/Starter/Boss/Special`
—— **没有 `Shop`**。而内容里已经有 `Rarity: "Shop"` 的遗物行（`membership_card`、
`lees_waffle` … 共 6 件），它们在 `Rarity::from_name` 里解析成 `None`，于是
`relic_pool` 把整条丢掉。

后果有两层：

* `membership_card`（wiki：商店打折卡）**永远拿不到** —— 它既不在掉落权重表里，也不在池子里；
* 而"拿不到"看起来就像"这件遗物是事件专属"，**没有任何判据会红**（`audit_relic_gap.py` 只比
  内容 vs wiki，不比"内容里的这件能不能发出来"）。

修法：加 `Rarity::Shop`，并且给商店货架一条**自己的**抽样路
（`pick_shop_relic_avoiding`：候选集 = 可掉落三档 ∪ `Shop`，`Shop` 按 **Rare** 档计权与计价 ——
wiki 只给了商店价 143–157，没说"Shop 档该多常见"，所以那是一个**模型**，写在注释里）。

判据：宝箱那条路抽不到它（`relic_rarity_is_droppable(Rarity::Shop) == false`），
而**只放一件 Shop 档**时货架必须抽得到它 —— 那才是"候选集真的包含它"。

### 292.2 十一件：载体与判据

| 遗物 | wiki | 载体 | 判据 |
|---|---|---|---|
| `cultist_headpiece` `spirit_poop` | 一句 flavor，**没有效果** | `RelicEffect::Nothing` | 被承认（不报 `UnsupportedRelic`）+ 不动金币/血/上限 |
| `face_of_cleric` | 战斗结束上限 +1 | `EndOfCombatMaxHealthUp`（`end_of_combat`） | 每场 +1、**累积**；没有它时不动 |
| `matryoshka` | 接下来 **2** 个非 Boss 宝箱给 2 件遗物 | `ChestExtraRelic{chests:2}` + `open_chest` | 计数从 2 起、开一个宝箱多一件、计数递减；没有它只给一件 |
| `nloths_hungry_face` | 下一个非 Boss 宝箱是空的 | `NextChestEmpty(1)` + `open_chest` | 金币/遗物都为 0（**回报的数也是 0**，见 292.3）；没有它照常 |
| `cursed_key` | 每回合 +1 能量 + **非 Boss 宝箱多一张诅咒** | 第一半 `standard.cursed_key`（`TurnStartEnergy`）+ 第二半 `ChestAddsCurse` | 表里是能量载体；宝箱后牌组多一张**池子里的诅咒**（不是 Status 行）；没有它不长 |
| `calling_bell` | 拾取时给一张诅咒 + 3 件遗物 | `PickupCurseAndRelics` | 诅咒**当场**进牌组、欠 3 件；池子里没那条诅咒 ⇒ `NoSuchCard` 且**整局不变** |
| `cauldron` | 拾取时酿 5 瓶药水 | `PickupPotions(5)`（欠账） | 欠 5 瓶、腰带 3 格 ⇒ 装 3、剩 2 留账（**偏差**） |
| `dollys_mirror` | 拾取时复制一张牌 | `PickupDuplicate` + `DeckChange::Duplicate` | 复制原件到末尾、欠账清；满牌组 ⇒ `Capacity` 且**欠账不被吃掉** |
| `nloths_gift` | 战斗奖励稀有牌"三倍" | `RareCardChanceMultiplier(3)` | 倍率 100→3；放大后仍**夹在**非稀有档下界 |
| `sacred_bark` | 药水效果翻倍 | `PotionEffectPercent(200)`（在 `rd_env_use_potion` 那一处乘） | 100→200；`POT` 行**不被改**（基准就是内容自己的数） |

**拾取欠账**（`pickup_relics` / `pickup_potions`）是这一节唯一的新形状：`push_relic` 只拿得到
**卡池**，而 `calling_bell` 要遗物池、`cauldron` 要药水池 —— 两个池都在 `rd-wasm`。所以运行层
只记"欠多少"（**进 run hash**），wasm 在三个 `push_relic` 入口后兑现（宝箱 / 取奖励 / 买遗物）。

### 292.3 ★ 判据自己抓到的一个真 bug：空宝箱**报告**掷到的金币

`nloths_hungry_face` 的第一版只跳过了 `adjust_gold`，但 `ChestOutcome.gold` 仍然返回**掷到的
那个数**（47）。页面会显示"你拿到了 47 金币"，而实际一分没加 —— 正是 §4.10 的"尺寸说谎"
同一形态（报告与实际不一致，谁都不会红，因为两边都"成功"了）。

修法：空宝箱把 `gold` 也置 0。判据 `assert_eq!(outcome.gold, 0)` 现在钉住它。

### 292.4 负控 10 条（全红）

| 改坏的地方 | 应当红的判据 |
|---|---|
| `face_of_cleric` 只涨上限不回血 | `face_of_cleric_raises_the_maximum_after_every_fight` |
| `matryoshka` 的第二件不给 | `matryoshka_queues_two_chests_and_pays_a_second_relic` |
| 空宝箱照旧扣金币 | `nloths_hungry_face_empties_exactly_one_chest` |
| `cursed_key` 不塞诅咒 | `cursed_key_carries_its_energy_and_its_chest_curse` |
| `calling_bell` 不记欠账 | `calling_bell_pays_a_curse_and_owes_three_relics` |
| `cauldron` 不记欠账 | `cauldron_owes_five_potions_and_the_belt_caps_it` |
| `dollys_mirror` 复制变空操作 | `dollys_mirror_duplicates_the_chosen_card_and_refuses_a_full_deck` |
| `nloths_gift` 的倍率读不出来 | `nloths_gift_triples_the_rare_band_never_passes_uncommon` |
| `sacred_bark` 的倍率读不出来 | `sacred_bark_doubles_potion_effectiveness` |
| 货架看不见 `Shop` 档 | `shop_rarity_relics_are_reachable_only_from_the_shelf` |

### 292.5 账

内容遗物 **116 → 127**（缺 77 → 66）；镜像 **162,916 B**（core 128,644 B）；状态 128 → 129；
`rd-core` 797 / `rd-run` **177**（+11）/ `rd-wasm` **138**（+2）；COVERAGE_MATRIX 836 行；
21/21 闸门。§289 那条"第二幕只有一件被筛掉"的判据在 §291 已改成两件（`the_colosseum` 的
`MaxFloor` + `the_joust` 的 `MinGold`）。

### 292.6 剩下 30 件各自缺什么（Wave 2/3 的清单）

**A. 战斗侧的一个新事实**（`rd-core`，每件几十行，但共享同一条新通道）：

| 缺的事实 | 遗物 |
|---|---|
| `DeckShuffled` 触发器（洗牌那一刻） | `the_abacus`（+6 格挡）、`sundial`（每 3 次 +2 能量） |
| `BlockBroken` 触发器（打破格挡） | `hand_drill`（+2 易伤） |
| "打出的牌带某 tag 时伤害 +N" | `strike_dummy`（+3） |
| 每回合出牌**上限** | `velvet_choker`（6 张） |
| 战斗中治疗倍率 | `magic_flower`（+50%） |
| X 费牌的 X 加数 | `chemical_x`（+2） |
| 不可打出（`unplayable`）牌的放行 | `medical_kit`、`blue_candle` |
| 隐藏敌人意图（运行层 → 观测 → 页面） | `runic_dome` |

**B. 运行层还差一个"拾取时让玩家挑一张牌加进牌组"的问句**（一次做，三件受益）：

`tiny_house`（50 金币 +5 上限 +1 药水 +1 张牌）、`orrery`（选 5 张）、`singing_bowl`
（加牌时可以不拿牌、改 +2 上限）。今天的 `PickupPick` 只能"选**已有**的一张去删/升/改"，
不能"从候选里**加**一张"。

**C. 已经有 `createRandomCardInstance` / `offerRandomCards`，可以直接写成内容程序的**：

`dead_branch`（`CardExhausted` → 往手牌加一张随机牌）、`nilrys_codex`（`TurnEnded` → 三选一进抽牌堆）、
`warped_tongs`（`TurnStarted` → 手牌随机升级）、`enchiridion`（开战加一张 Power、费 0 ——
§292 摸底确认内容里**有** 22 张 Power，旧文档"0 张 power 牌"是过期信息）、
`mummified_hand`（打 Power ⇒ 手牌一张变 0 费）、`orange_pellets`（三种类型各打一张 ⇒ +3 力量）。

**D. 需要"打两次"这种机制**（明确不做，StS 的 `Necronomicon`）：

`necronomicon`。

**E. 地图/页面**：`wing_boots`（忽略路径 3 次）、`frozen_eye`（抽牌堆显示顺序）。

**F. 需要"消耗改成丢弃 50%"**：`strange_spoon`（要在出牌的落区判定里用 RNG）。

**G. 开局三场的敌人 1 血**：`neows_lament`（运行层计数 + 开战时覆盖敌人血量）。

**H. 需要一个新的"开战前三选一"问句**：`gambling_chip`（开局任意张换牌）、`toolbox`（三选一无色）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    old = '''**剩下 78 件按"缺哪块载体"分档**（细节见方法论文档 §3 / §8）：'''
    new = '''**§292 之后是 66 件**（Wave 1 做了 11 件 + 修了 `Shop` 档的静默缺口；逐件清单见
`port-plan.md` §292.6）。按"缺哪块载体"分档（细节见方法论文档 §3 / §8）：'''
    assert g.count(old) == 1
    g = g.replace(old, new)

    marker = '''### F.11 F.5 的审计与"付不起就别画"（§291）'''
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.12 遗物：Wave 1 与 `Shop` 档（§292）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `Shop` 稀有度的遗物 | 只在商人处卖（14 件） | **已修**：`Rarity::Shop` + 货架抽样 | 一致（§292.1；此前**永远拿不到**） |
| `cultist_headpiece` / `spirit_poop` | 一句 flavor | **已做**：`RelicEffect::Nothing` | 一致 |
| `face_of_cleric` / `matryoshka` / `nloths_hungry_face` / `cursed_key` / `calling_bell` / `cauldron` / `dollys_mirror` / `nloths_gift` / `sacred_bark` | 见 §292.2 | **已做**（各带两侧判据） | 一致 |
| `cauldron` 装不下的 2 瓶 | 一瓶一瓶问"要不要丢掉旧的" | **丢在欠账上**（不静默消失，进 run hash） | **偏差**（缺丢弃问句） |
| `matryoshka` 的第二件 | 分别进奖励屏 | 直接进腰带 | **偏差**（与 `black_star` 同一条：奖励屏只有一个遗物槽） |

### F.11 F.5 的审计与"付不起就别画"（§291）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§291）', '（主计划 §1–§292）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
