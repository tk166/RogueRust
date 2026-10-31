"""Append §158 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 158. 药水稀有档补到 wiki 的数目（20 / 33）：先补不需要新机制的十一瓶

§157 把药水从 10 瓶做到 11 瓶，同时钉下了"Rare 档是空的"这件事。这一节回答的是**到底差多少**：
wiki 的 `Potions` 页对**铁甲战士**能拿到的是 **17 Common / 9 Uncommon / 7 Rare = 33 瓶**
（42 瓶总数减去 Silent 的 2、Defect 的 3、Watcher 的 3 —— 逐个从表里数的）。

这次补了 **9** 瓶，它们都不需要内核有新的机制：**20 瓶（C12 / U4 / R4）**。
剩下 13 瓶每一瓶都要一样新东西，逐条列在 §158.7 ——这张清单比"还差 13"有用。

### 158.1 三处"声明了但内核没读"，这次先补最要命的两处

* **`standard.dexterity` 在内容里没有行**。内核的 `BLOCK_MODIFIERS`（`status_catalog.rs`）
  有它，但**内容存在时那张表是关掉的**（`exec.rs` 的 `NAMESPACE_BRIDGE` 只在
  `content == None` 时用它）⇒ 内容侧必须自己声明
  `BlockGain / AddPerStack / 1 / Priority 100`（参考 `StandardCombatPackage.cs:360-363`）。
  ⚠️ 管线串是 `"BlockGain"`，**不是** `"Block"`（`status_bind.rs:60-65` 专门写了这一条）。
* **`PotionTables` 是死数据 + 会被静默截断**。三幕各一份药水池这件事**在 wiki 里没有出处**
  （药水不分幕），而 `MAX_POOL_IDS = 8` 会把 33 项清单截成 8 项 —— `id_pool` 里那个
  `.min(MAX_POOL_IDS)` 就是本项目最忌讳的形状：内容说有，实际只有前 8 个能掉。
  ⇒ 删掉整张表，药水池 = **`POT` 表的全部行**，`potion_pool` 读取器随之删除。

### 158.2 `Effect` 变成**逗号分隔的原子列表**

Flex Potion 的 wiki 原文是两句："Gain 5 Strength. At the end of your turn, lose 5 Strength."
`POT` 行只有一个 `Effect` 格，而这是**两个状态**（`standard.strength` 与
`standard.lose_strength`，后者是内容侧新加的：`TurnEnded` 触发里把自己的层数从力量上减回去，
然后把自己减到 0）。所以加了逗号列表，**所有原子共用一个 `Amount`** —— 正好这两瓶的两半数量相同。

内核侧的实现是"逐个原子执行"，`combat_status` 与 `combat_status_target` 各带自己的前缀，
所以一瓶药水理论上可以同时打自己和敌人。内容门 `[3b]` 逐个原子检查词汇表，
并且要求**不能把"要目标的原子"和"不要目标的原子"混在一瓶里**（页面只问一次目标）。

### 158.3 运行层原子：`max_hp` / `potion_fill` 可以在**战斗外**用

wiki：Fruit Juice 和 Entropic Brew 是"most scenarios 都能用"的两瓶。此前的实现把
"不在战斗里就拒绝"写在了**效果分派之前**，于是这两瓶只有在战斗里才喝得下去 —— 词汇表里有，
可达性只有一半。现在先按原子分类：全部是运行层原子 ⇒ 走运行层分支，一个战斗都不用开。

`potion_fill`（Entropic Brew）还有一个顺序问题：**它必须先把自己从腰带上拿下来**，否则
一个 3/3 的满腰带"填空格"是零个。判据就写在这上面："喝之前 3 瓶，喝之后还是 3 瓶" ——
如果先填后消耗，读数会是 2，做不对就红。

`pick_potion` 也从 `roll_reward` 里提出来了：掉落和"这瓶药水变成哪瓶"必须是**同一个**答案，
两个挑选器就是两套要记得改的权重。

### 158.4 又一处 wiki 与内容不符：Energy Potion 是 Common

内容里写成 `Uncommon`。顺手改了 —— 这类"一格之差"不会让任何测试红，但它会让 65/25/10 的
分布整体偏一点，而分布是**统计量**，单种子证不了。

### 158.5 这次改动照出**两条死了的测试**

`cargo test` 的警告里有两行 `duplicated attribute` / `never used`，追下去是同一个形状：
**一次 `edit` 的锚点是一行裸文档注释，把紧跟其后的 `#[test]` 吞掉了**（FACT.md §3 记的就是这个）。

1. `content::the_encounter_pools_are_readable` —— 没了 `#[test]`，于是它那个 `#[test]`
   叠到了上面 `no_encounter_places_more_enemies_than_a_fight_allows` 头上。它**编译、跑零次、
   不报任何东西**。补回属性后立刻红：它断言的"weak 池 3 项"已经两年是 7 项了。
   ⇒ 顺手把断言换成**结构**而不是当天的数字：9 个池子的 id 都必须是真 `ENCT` 行、
   池子之间**不重叠**、并且并集 == 全部遭遇（没有不可达的遭遇）。这条以后不会再过期。
2. `host::a_split_spawns_two_combatants_when_the_boss_dies` —— 同一个形状，补回 `#[test]`。

两处都不是"断言写错"，是**测试根本没跑**。它不会让任何闸门变红，只会让覆盖率这个数字虚高。

### 158.6 判据

* `dexterity_from_the_content_scales_a_real_defend`（rd-core）：用**内容的起始牌**打一张
  `defend`（5 格挡），英雄身上 2 层 `standard.dexterity` ⇒ 要 **7**。
  ⚠️ 负控做过：把那个 spec 的 `Pipeline` 改成 `"BlockGained"`，测试**红**，
  而且是响亮的 `Play(Effect(Bind(Pipeline)))` ——
  绑定器拒绝未知管线，不是"静默不生效"。
* `flex_potion_gives_strength_and_takes_it_back`（rd-wasm）：喝下去立刻 +5 力量 **且**挂上
  5 点 `standard.lose_strength`；结束回合后两者都是 0（= 实例已被移除）。
* `entropic_brew_fills_the_belt_after_freeing_its_own_slot`：满腰带 3 → 喝完仍是 3。
* `fruit_juice_works_outside_a_fight`：一局但没有战斗，`+5` 最大生命，且生命同额提升。
* `the_potions_are_readable`（rd-core）：20 瓶、`bands == [12, 4, 4]`、每个原子都在词汇表里、
  `potion_fill` 是唯一不读 `Amount` 的原子。

### 158.7 还差 13 瓶，每一瓶要一样**新机制**

| 要的机制 | 药水 |
|---|---|
| 战斗中选牌（1/3 张）| Attack / Skill / Power / Colorless Potion |
| 战斗中升级手牌 | Blessing of the Forge |
| 战斗中多选弃/消耗 | Elixir、Gambler's Brew |
| 从弃牌堆检索一张并免费 | Liquid Memories |
| 自动打出牌堆顶 | Distilled Chaos |
| 把下一张牌打两次 | Duplication Potion |
| 改写卡牌费用 | Snecko Oil |
| 死亡拦截（`DeathPrevention` 字段**已经能解出来但没人读**）| Fairy in a Bottle |
| 逃跑（`FightOutcome` 需要一个 "escaped"）| Smoke Bomb |

### 158.8 数字

聚合验收 **18/18**；单测 748 → **752**（rd-core 630 → **631**、rd-run 77、rd-wasm 41 → **44**）。
内容：**20 种药水（C12 / U4 / R4）**、**24 条状态**（+3）、31 怪 / 22 遭遇 / 30 卡 / 13 遗物。
镜像 full **36,880 B** / core **30,360 B**（**没有** `--repin`：这次只动 `sts` 的数据，
`REL`/`POT` 的**格式**一格没变，所以 `tools/contentc/out/` 那两份 roguedeck 镜像字节不变）。
"""

with io.open(PATH, "rb") as handle:
    raw = handle.read()
assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
text = raw.decode("utf-8")
assert "## 158." not in text, "already appended"
if not text.endswith("\n"):
    text += "\n"
text += SECTION
with io.open(PATH, "wb") as handle:
    handle.write(text.encode("utf-8"))
print("port-plan.md now", len(text.split("\n")), "lines")
