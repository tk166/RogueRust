# StS Act 1 内容清单（Ironclad / 出发 → Boss）

> **本文件只记录事实，不设计数据结构、不写实现计划。**
> 目标：为"复刻 Slay the Spire 铁甲战士第一张地图"提供可机读的数值基线，供后续逐个核对"我们搬完了没有"。

## 0. 版本锚定、来源与可信度

| 项 | 值 |
|---|---|
| 目标游戏版本 | **Slay the Spire PC 正式版 v2.3.4**（v2.3 大版本 + 2.3.1/2.3.3/2.3.4 hotfix；这是 PC 公开版最后的补丁线）【wiki】 |
| 我们**不**锚定的东西 | 主机/手机版、Early Access 的 weekly patch、Ascension（见 §11）、Slay the Spire 2 |
| 数值来源 A（主） | `nkhoit/spire-archive` 的 STS1 数据转储（直接从游戏 JAR 解析：`data/sts1/cards.json`、`monsters.json`、`relics.json`、`potions.json`、`relic_values.json`、`characters.json`） |
| 数值来源 B（主） | Slay the Spire Fandom Wiki（`slay-the-spire.fandom.com`）的 MediaWiki `action=parse&prop=wikitext` 原文，逐页引用 |
| 数值来源 C（辅） | 官方新 wiki `slaythespire.wiki.gg`（Map Generation / Patch Notes 两页） |

**没有现成的"第一幕内容"JSON。**`spire-archive` 给的是全局实体表（含 HP/伤害/描述/稀有度），但**不含**遭遇编成、遭遇权重、敌人 AI 权重、地图生成规则、事件分支数值——这几块只能从 wiki 手抄，本文件已逐条标注来源。

可信度标记（每条事实后附）：

| 标记 | 含义 |
|---|---|
| 【游戏文件】 | 直接来自游戏 JAR 解析出的数据（来源 A），数值层面最硬 |
| 【wiki】 | 来自 wiki 原文（来源 B/C），未与游戏文件交叉验证 |
| 【多源一致】 | 来源 A 与来源 B/C 数值一致 |
| 【单源】 | 只有一处来源，或只有一处来源给了该细节 |
| 【推断】 | 由已知规则推出来的，没有直接文本 |

**已知的数据源瑕疵（会影响你我核对时的判读）：**

1. `cards.json` 的 `upgrade.description` 是**把基础文本里的第一个数字替换掉**生成的，同一数字出现两次时第二处不会被替换。例：`Flex` 的升级描述写作"lose 2 Strength"，而 wiki 表格（`Gain 2(4) Strength, lose 2(4) Strength`）说明应为 lose 4。⇒ **升级后的文本一律以 wiki 的 `base(upgraded)` 记法为准，不用 `upgrade.description`。**
2. `monsters.json` 的 `moves[]` **不完整**：`Looter` 只列了 `MUG`/`SMOKE_BOMB`，缺 `LUNGE` 与 `ESCAPE`；`Gremlin Nob` 的 `Bellow` 只标了 intent=BUFF，没给 Enrage 层数。⇒ **HP 与伤害数值用来源 A，行动集合/AI/上状态层数用来源 B。**
3. `relics.json` 的 `color` 字段**不可靠**（`Captain's Wheel` 被标成 watcher 却在共享稀有池；`Pure Water` 是 Watcher 起始遗物却标 null）。⇒ **"哪些遗物是职业专属"以 wiki `Relics` 页的 `Class-Specific` 分节为准。**
4. `monsters.json` 的 `Gremlin Wizard` HP 记 21–25，wiki 信息框写 23–25（而同一信息框的 Asc 值 22–26 比基础值还低，自相矛盾）。⇒ 采信游戏文件的 **21–25**【游戏文件】，并在此标记冲突。
5. `relic_values.json` 里有 `TEST_5`/`TEST_6` 两条测试项；`monsters.json` 里有 `HEXAGHOSTBODY`/`HEXAGHOSTORB`（无 HP）与 `APOLOGY_SLIME`（存档损坏时的兜底怪）——**都不是可遭遇敌人**，已从清单里剔除。

## 1. 总数速查（后续核对的硬数字）

| # | 项目 | 数量 | 依据 |
|---|---|---|---|
| 1 | Ironclad 卡池总数（含基础牌） | **75** | 【多源一致】`cards.json` color=ironclad 计 75；wiki `Ironclad Cards` 表格 75 行 |
| 1a | ├ 基础牌 Basic | 3 | 【多源一致】strike / defend / bash |
| 1b | ├ 普通 Common | 20 | 【多源一致】 |
| 1c | ├ 罕见 Uncommon | 36 | 【多源一致】 |
| 1d | └ 稀有 Rare | 16 | 【多源一致】 |
| 2 | **第一幕卡牌奖励池** | **72** | 【推断】75 − 3 张 Basic；见 §2.5 |
| 3 | 第一幕普通遭遇（遭遇编成定义） | **14** | 【wiki】= 前 3 场 4 种 + 之后 10 种 |
| 4 | 第一幕精英遭遇 | **3** | 【wiki】Gremlin Nob / Lagavulin / 3× Sentry |
| 5 | 第一幕 Boss | **3** | 【wiki】The Guardian / Hexaghost / Slime Boss（三选一） |
| 6 | 第一幕敌人**实体**种类（可上场单位） | **25** | 【多源一致】19 普通 + 3 精英 + 3 Boss |
| 7 | 遗物：Ironclad 第一幕**可获取**（不含起始遗物） | **140** | 【推断】按 wiki 职业专属分节筛 |
| 7a | ├ Common / Uncommon / Rare / Shop / Boss / 事件 | 33 / 30 / 28 / 17 / 22 / 10 | 同上 |
| 7b | 起始遗物 | 1 | 【多源一致】Burning Blood |
| 8 | 第一幕地图事件（? 房可抽到） | **26** | 【wiki】11 幕专属 + Face Trader + 14 共享 |
| 8a | └ 其中幕专属（不含 Neow） | 11 | 【wiki】 |
| 8b | └ 其中共享（可跨幕） | 14 + Face Trader = 15 | 【wiki】`Events` 页列 16 个跨幕事件，`Designer In-Spire` 仅 Act 2/3 |
| 9 | 事件总数（全局，含 Act 2/3 与 Neow） | 52 | 【游戏文件】`events.json` 52 条；其中含自定义/未用项 |
| 10 | 药水：Ironclad 第一幕可获取 | **33** | 【多源一致】42 全局 − 9 个他职业专属 |
| 10a | └ Common / Uncommon / Rare | 17 / 9 / 7 | 同上 |
| 11 | 第一幕地图层数 | 15 层节点 + Boss 层 + Boss 宝箱层 = 17 floor | 【wiki】 |
| 12 | 地图列数 / 路径数 | 7 列 / 6 条路径 | 【wiki】（Steam 社区逆向 + wiki 互证） |

> 全局参考：`spire-archive` 的 STS1 转储共 **360 张卡**（Ironclad 75 / Silent 75 / Defect 76 / Watcher 76 / Colorless 44 / Curse 14）、**181 条遗物**、**42 瓶药水**、**68 个怪物条目**、**52 个事件**。【游戏文件】

---

## 2. 角色：The Ironclad

| 字段 | 值 | 来源 |
|---|---|---|
| id | `ironclad` | — |
| 起始 HP | **80** | 【多源一致】`characters.json` hp=80；`Ironclad` 页 80 |
| 起始能量 | **3** | 【多源一致】 |
| 起始遗物 | **Burning Blood**（`burning_blood`）: "At the end of combat, heal 6 HP." | 【多源一致】 |
| 起手抽牌 | 5（通用规则） | 【wiki】 |
| 起始牌组 | **10 张**：`strike` ×5、`defend` ×4、`bash` ×1 | 【多源一致】`characters.json` starting_deck |

### 2.1 起始牌组逐张

| id | 张数 | 费用 | 类型 | 数值 | 升级后 |
|---|---|---|---|---|---|
| `strike` | 5 | 1 | Attack | Deal 6 damage | Deal 9 damage |
| `defend` | 4 | 1 | Skill | Gain 5 Block | Gain 8 Block |
| `bash` | 1 | 2 | Attack | Deal 8 damage, apply 2 Vulnerable | Deal 10 damage, apply 3 Vulnerable |

### 2.2 开局：Neow（第一层之前，非地图节点）

| 情形 | 选项 |
|---|---|
| 上一局**已**打到第一幕 Boss | 4 选 1：①正面 ②正面 ③交易（给钱/给血换强力） ④用起始遗物换随机 Boss 遗物 【wiki】 |
| 上一局**没**打到第一幕 Boss | 2 选 1：①+10% 最大 HP ②获得 `Neow's Lament`（前 3 场战斗敌人 1 HP） 【wiki】 |

`Neow's Lament` 效果：`Enemies in your first 3 combats will have 1 HP.`【游戏文件】

---

## 3. 卡牌：Ironclad 全 75 张

读法（每张卡一行，固定字段）：

| 列 | 含义 |
|---|---|
| `id` | 本清单自定的稳定 snake_case 名（由英文卡名派生） |
| `type` | `attack` / `skill` / `power` |
| `cost` | 显示费用；`X` = 可变费用；`→` 右侧为升级后 |
| `target` | `enemy` / `all_enemies` / `self` / `none` / `self+enemy` |
| `dmg` `block` | 卡的**基础直伤/格挡**字段（`6→9` = 基础→升级）；空白 = 该卡没有这个字段 |
| `M` | 卡的"magicNumber"字段（**语义随卡而变**：层数 / 次数 / 抽牌数 / 上限，以 `mechanic` 列为准）；`→` 右侧为升级后 |
| `kw` | 关键词（由游戏文件的 exhaust/ethereal/innate/retain 标志 + 本清单补充的结构关键词） |
| `mechanic` | 机制精确描述，`base(upgraded)` 记法 = 基础(升级后) |

> 说明：`dmg`/`block`/`M` 是**结构化冗余**，用来快速比对；`mechanic` 才是语义真值。两者不一致时以 `mechanic` 为准并回查 wiki。

### 3.1 基础牌 Basic (3)

| `id` | name | type | cost | target | dmg | block | M | kw | mechanic (base → upgraded) |
|---|---|---|---|---|---|---|---|---|---|
| `bash` | Bash | attack | 2 | enemy | 8→10 |  | 2→3 | — | Deal 8(10) damage. Apply 2(3) Vulnerable. |
| `strike` | Strike | attack | 1 | enemy | 6→9 |  |  | — | Deal 6(9) damage. |
| `defend` | Defend | skill | 1 | self |  | 5→8 |  | — | Gain 5(8) Block. |

### 3.2 普通 Common (20)

| `id` | name | type | cost | target | dmg | block | M | kw | mechanic (base → upgraded) |
|---|---|---|---|---|---|---|---|---|---|
| `anger` | Anger | attack | 0 | enemy | 6→8 |  |  | — | Deal 6(8) damage. Add a copy of this card to your discard pile. |
| `body_slam` | Body Slam | attack | 1→0 | enemy |  |  |  | block-scaled | Deal damage equal to your current Block. |
| `clash` | Clash | attack | 0 | enemy | 14→18 |  |  | playable-only-if-all-attacks | Can only be played if every card in your hand is an Attack. Deal 14(18) damage. |
| `cleave` | Cleave | attack | 1 | all_enemies | 8→11 |  |  | — | Deal 8(11) damage to ALL enemies. |
| `clothesline` | Clothesline | attack | 2 | enemy | 12→14 |  | 2→3 | — | Deal 12(14) damage. Apply 2(3) Weak. |
| `headbutt` | Headbutt | attack | 1 | enemy | 9→12 |  |  | — | Deal 9(12) damage. Place a card from your discard pile on top of your draw pile. |
| `heavy_blade` | Heavy Blade | attack | 2 | enemy | 14 |  | 3→5 | strength-multiplier | Deal 14 damage. Strength affects Heavy Blade 3(5) times. |
| `iron_wave` | Iron Wave | attack | 1 | enemy | 5→7 | 5→7 |  | — | Gain 5(7) Block. Deal 5(7) damage. |
| `perfected_strike` | Perfected Strike | attack | 2 | enemy | 6 |  | 2→3 | strike-synergy | Deal 6 damage. Deals an additional 2(3) damage for ALL of your cards containing "Strike". |
| `pommel_strike` | Pommel Strike | attack | 1 | enemy | 9→10 |  | 1→2 | — | Deal 9(10) damage. Draw 1(2) card(s). |
| `sword_boomerang` | Sword Boomerang | attack | 1 | all_enemies | 3 |  | 3→4 | — | Deal 3 damage to a random enemy 3(4) times. |
| `thunderclap` | Thunderclap | attack | 1 | all_enemies | 4→7 |  |  | — | Deal 4(7) damage and apply 1 Vulnerable to ALL enemies. |
| `twin_strike` | Twin Strike | attack | 1 | enemy | 5→7 |  |  | — | Deal 5(7) damage twice. |
| `wild_strike` | Wild Strike | attack | 1 | enemy | 12→17 |  |  | — | Deal 12(17) damage. Shuffle a Wound into your draw pile. |
| `armaments` | Armaments | skill | 1 | self |  | 5 |  | — | Gain 5 Block. Upgrade a(ALL) card(s) in your hand for the rest of combat. |
| `flex` | Flex | skill | 0 | self |  |  | 2→4 | — | Gain 2(4) Strength. At the end of your turn, lose 2(4) Strength. |
| `havoc` | Havoc | skill | 1→0 | none |  |  |  | — | Play the top card of your draw pile and Exhaust it. |
| `shrug_it_off` | Shrug It Off | skill | 1 | self |  | 8→11 |  | — | Gain 8 Block. Draw 1 card. |
| `true_grit` | True Grit | skill | 1 | self |  | 7→9 |  | — | Gain 7(9) Block. Exhaust a random(not random) card from your hand. |
| `warcry` | Warcry | skill | 0 | self |  |  | 1→2 | exhaust | Draw 1(2) card(s). Place a card from your hand on top of your draw pile. Exhaust. |

### 3.3 罕见 Uncommon (36)

| `id` | name | type | cost | target | dmg | block | M | kw | mechanic (base → upgraded) |
|---|---|---|---|---|---|---|---|---|---|
| `blood_for_blood` | Blood for Blood | attack | 4→3 | enemy | 18→22 |  |  | cost-reduction | Costs 1 less energy for each time you lose HP in combat. Deal 18(22) damage. |
| `carnage` | Carnage | attack | 2 | enemy | 20→28 |  |  | ethereal | Ethereal. Deal 20(28) damage. |
| `dropkick` | Dropkick | attack | 1 | enemy | 5→8 |  |  | — | Deal 5(8) damage. If the enemy is Vulnerable, gain 1 energy and draw 1 card. |
| `hemokinesis` | Hemokinesis | attack | 1 | enemy | 15→20 |  | 2 | self-hp-cost | Lose 2 HP. Deal 15(20) damage. |
| `pummel` | Pummel | attack | 1 | enemy | 2 |  | 4→5 | exhaust | Deal 2 damage 4(5) times. Exhaust. |
| `rampage` | Rampage | attack | 1 | enemy | 8 |  | 5→8 | self-growth | Deal 8 damage. Increase this card's damage by 5(8) this combat. |
| `reckless_charge` | Reckless Charge | attack | 0 | enemy | 7→10 |  |  | — | Deal 7(10) damage. Shuffle a Dazed into your draw pile. |
| `searing_blow` | Searing Blow | attack | 2 | enemy | 12 |  |  | multi-upgrade | Deal 12(16) damage. Can be upgraded any number of times. |
| `sever_soul` | Sever Soul | attack | 2 | enemy | 16→22 |  |  | — | Exhaust all non-Attack cards in your hand. Deal 16(22) damage. |
| `uppercut` | Uppercut | attack | 2 | enemy | 13 |  | 1→2 | — | Deal 13 damage. Apply 1(2) Weak. Apply 1(2) Vulnerable. |
| `whirlwind` | Whirlwind | attack | X | all_enemies | 5→8 |  |  | X-cost | Deal 5(8) damage to ALL enemies X times. |
| `battle_trance` | Battle Trance | skill | 0 | none |  |  | 3→4 | — | Draw 3(4) cards. You cannot draw additional cards this turn. |
| `bloodletting` | Bloodletting | skill | 0 | self |  |  | 2→3 | self-hp-cost | Lose 3 HP. Gain 2(3) Energy. |
| `burning_pact` | Burning Pact | skill | 1 | none |  |  | 2→3 | — | Exhaust 1 card. Draw 2(3) cards. |
| `disarm` | Disarm | skill | 1 | enemy |  |  | 2→3 | exhaust | Enemy loses 2(3) Strength. Exhaust. |
| `dual_wield` | Dual Wield | skill | 1 | none |  |  | 1→2 | — | Create a(2) copy(s) of an Attack or Power card in your hand. |
| `entrench` | Entrench | skill | 2→1 | self |  |  |  | — | Double your current Block. |
| `flame_barrier` | Flame Barrier | skill | 2 | self |  | 12→16 | 4→6 | — | Gain 12(16) Block. Whenever you are attacked this turn, deal 4(6) damage to the attacker. |
| `ghostly_armor` | Ghostly Armor | skill | 1 | self |  | 10→13 |  | ethereal | Ethereal. Gain 10(13) Block. |
| `infernal_blade` | Infernal Blade | skill | 1→0 | none |  |  |  | exhaust | Add a random Attack to your hand. It costs 0 this turn. Exhaust. |
| `intimidate` | Intimidate | skill | 0 | all_enemies |  |  | 1→2 | exhaust | Apply 1(2) Weak to ALL enemies. Exhaust. |
| `power_through` | Power Through | skill | 1 | self |  | 15→20 |  | — | Add 2 Wound to your hand. Gain 15(20) Block. |
| `rage` | Rage | skill | 0 | self |  |  | 3→5 | — | Whenever you play an Attack this turn, gain 3(5) Block. |
| `second_wind` | Second Wind | skill | 1 | self |  | 5→7 |  | — | Exhaust all non-Attack cards in your hand and gain 5(7) Block for each card Exhausted. |
| `seeing_red` | Seeing Red | skill | 1→0 | none |  |  |  | exhaust | Gain 2 energy. Exhaust. |
| `sentinel` | Sentinel | skill | 1 | self |  | 5→8 |  | — | Gain 5(8) Block. If this card is Exhausted, gain 2(3) energy. |
| `shockwave` | Shockwave | skill | 2 | all_enemies |  |  | 3→5 | exhaust | Apply 3(5) Weak and Vulnerable to ALL enemies. |
| `spot_weakness` | Spot Weakness | skill | 1 | self+enemy |  |  | 3→4 | intent-conditional | If the enemy intends to attack, gain 3(4) Strength. |
| `combust` | Combust | power | 1 | self |  |  | 5→7 | hp-loss-trigger | At the end of your turn, lose 1 HP and deal 5(7) damage to ALL enemies. |
| `dark_embrace` | Dark Embrace | power | 2→1 | self |  |  |  | — | Whenever a card is Exhausted, draw 1 card. |
| `evolve` | Evolve | power | 1 | self |  |  | 1→2 | — | Whenever you draw a Status card, draw 1(2) card(s). |
| `feel_no_pain` | Feel No Pain | power | 1 | self |  |  | 3→4 | — | Whenever a card is Exhausted, gain 3(4) Block. |
| `fire_breathing` | Fire Breathing | power | 1 | self |  |  | 6→10 | — | Whenever you draw a Status or Curse card,  deal 6(10) damage to all enemies. |
| `inflame` | Inflame | power | 1 | self |  |  | 2→3 | — | Gain 2(3) Strength. |
| `metallicize` | Metallicize | power | 1 | self |  |  | 3→4 | — | At the end of your turn, gain 3(4) Block. |
| `rupture` | Rupture | power | 1 | self |  |  | 1→2 | hp-loss-trigger | Whenever you lose HP from a card, gain 1(2) Strength. |

### 3.4 稀有 Rare (16)

| `id` | name | type | cost | target | dmg | block | M | kw | mechanic (base → upgraded) |
|---|---|---|---|---|---|---|---|---|---|
| `bludgeon` | Bludgeon | attack | 3 | enemy | 32→42 |  |  | — | Deal 32(42) damage. |
| `feed` | Feed | attack | 1 | enemy | 10→12 |  | 3→4 | exhaust,max-hp-gain | Deal 10(12) damage. If this kills a non-minion enemy, gain 3(4) permanent Max HP. Exhaust. |
| `fiend_fire` | Fiend Fire | attack | 2 | enemy | 7→10 |  |  | exhaust | Exhaust all cards in your hand. Deal 7(10) damage for each Exhausted card. Exhaust. |
| `immolate` | Immolate | attack | 2 | all_enemies | 21→28 |  |  | — | Deal 21(28) damage to ALL enemies. Add a Burn into your discard pile. |
| `reaper` | Reaper | attack | 2 | all_enemies | 4→5 |  |  | exhaust,lifesteal | Deal 4(5) damage to ALL enemies. Heal HP equal to unblocked damage. Exhaust. } |
| `double_tap` | Double Tap | skill | 1 | self |  |  | 1→2 | attack-duplication | This turn, your next (2) Attack(s) is(are) played twice. |
| `exhume` | Exhume | skill | 1→0 | none |  |  |  | exhaust | Put a card from your Exhaust pile into your hand. Exhaust. |
| `impervious` | Impervious | skill | 2 | self |  | 30→40 |  | exhaust | Gain 30(40) Block. Exhaust. |
| `limit_break` | Limit Break | skill | 1 | self |  |  |  | exhaust,strength-multiplier | Double your Strength. Exhaust(Don't Exhaust). |
| `offering` | Offering | skill | 0 | self |  |  | 3→5 | exhaust,self-hp-cost | Lose 6 HP. Gain 2 energy. Draw 3(5) cards. Exhaust. |
| `barricade` | Barricade | power | 3→2 | self |  |  |  | block-retention | Block is not removed at the start of your turn. |
| `berserk` | Berserk | power | 0 | self |  |  | 2→1 | self-debuff | Gain 2(1) Vulnerable. At the start of your turn, gain 1 Energy. |
| `brutality` | Brutality | power | 0 | self |  |  |  | innate,hp-loss-trigger | (Innate.) At the start of your turn, lose 1 HP and draw 1 card. |
| `corruption` | Corruption | power | 3→2 | self |  |  | 3 | cost-modifier | Skills cost 0. Whenever you play a Skill, Exhaust it. |
| `demon_form` | Demon Form | power | 3 | none |  |  | 2→3 | — | At the start of each turn, gain 2(3) Strength. |
| `juggernaut` | Juggernaut | power | 2 | self |  |  | 5→7 | block-trigger | Whenever you gain Block, deal 5(7) damage to a random enemy. |

### 3.5 卡牌奖励池规则（第一幕）

| 规则 | 值 | 来源 |
|---|---|---|
| 池子构成 | 角色色（ironclad）的所有**非 Basic** 卡 = **72 张**（20C / 36U / 16R） | 【推断】来源 A 只给出 color 与 rarity，没有直接给"奖励池"表；wiki 只说"按角色 + 稀有度" |
| **是否按幕筛** | **不按幕筛。**StS 的卡牌奖励池**没有**"第一幕专用卡"的概念：同一角色的 72 张卡从第 1 层到第 3 幕权重相同，唯一的按幕规则是"升级概率"（见下） | 【wiki】`Card Rewards` 页只按"战斗类型"分档，未出现任何按幕的池子 |
| 每屏张数 | 3 张，**互不相同**（逐个独立掷出，后掷的不会与已掷出的重复） | 【wiki】 |
| 稀有度（普通战斗） | Rare 3% / Uncommon 37% / Common 60% | 【多源一致】 |
| 稀有度（精英战斗） | Rare 10% / Uncommon 40% / Common 50% | 【wiki】 |
| 稀有度（Boss 战斗） | Rare **100%** | 【wiki】 |
| 稀有度偏移（保底机制） | 偏移量初始 **−5%**；**每次卡牌掷点之后**：落在 Rare → **重置为 −5%**，**否则 +1%**（⚠️ 是"否则"不是"Common"——**Uncommon 也会 +1%**，这是 2026-10-20 校准时改的，原先写成"每掷出一次 Common +1%"），上限 **+40%**。三张牌**从左到右共用同一个偏移**；一屏三张是一次性掷完的，所以**跳过也照样 tick 3 次**。只有"战斗奖励"的掷点会改动偏移（商店角色卡槽读偏移但不改；Boss 奖励不读偏移但会重置它） | 【wiki】`Card Rewards` |
| 掷点方式（**叠加带**，不是三次独立roll） | 掷**一个** 0–99 的数，按带判定：Rare 带 = `基础值 + 偏移`（**下限 0**）；Uncommon 带是**固定宽度**（普通战 37、精英 40），**直接贴在 Rare 带上面**；剩下全是 Common。⇒ 当 `基础值 + 偏移` 为**负**时，Rare 带归零，而那点亏空是**从 Uncommon 带底部被吃掉、归给 Common** 的。所以刚重置（普通战 3 − 5 = −2）的真实概率是 **Rare 0% / Uncommon 35% / Common 65%**；把 Rare 夹到 0 却仍给 Uncommon 37% 的实现是**错的**，而它照样能通过"大致 3/37/60"的检验 | 【wiki】`Card Rewards`（原文 "Actual at reset (offset -5%)"） |
| 表里那三档是什么时刻的概率 | 上面 3/37/60 与 10/40/50 是**偏移为 0 时**的值。刚重置时看不到它们，要几次非 Rare 之后偏移才回到 0 | 【wiki】 |
| 升级概率（第一幕） | **0%**（第一幕卡牌奖励永远不出升级版） | 【多源一致】`Card Rewards` 与 `Gameplay` 两页一致 |
| 升级概率（Boss/后续幕） | Act 2 **25%**、Act 3 **50%**；**Rare 卡永不被自动升级** | 【wiki】`Card Rewards` |
| 升级概率（参考） | Act 2: 25%，Act 3: 50% | 【wiki】 |
| 可跳过 | 可以 | 【wiki】 |

> **2026-10-20 校准**：本节按 `spire-codex.com/mechanics/card-rarity`（页内标题 `Card Rarity Odds`）
> 与 `slaythespire.wiki.gg/wiki/Potions` 复核过一遍。复核改了三处：偏移的触发条件（"否则 +1%"，
> 不是"Common +1%"）、**叠加带**的画法（负的 Rare 带要吃掉 Uncommon 的底部）、以及 Boss 奖励
> 不读偏移但会重置它。三张互不重复、可跳过、第一幕 0% 升级这几条与原文一致。
> ⚠️ 那份页面是 **StS2** 站点（`sts2`）的机制页；60/37/3、50/40/10、100% Rare、−5%→+40% 这些
> 数值与 StS1 的多源记载相同，所以按它校准；**若某天两者分叉，以 StS1 为本项目的目标**。

> **2026-10-20（同日，实现）**：`CARD` 行加了 `Rarity` 格（第 16 格，**stride 仍是 32**：
> `align4(2×15) == align4(2×16) == 32`）。本内容：`strike`/`defend`/`bash` 及其升级版 = `Basic`、
> `slimed` = `Status`。于是本节的两处"做不到"都能做了：奖励池按稀有度集结、**商店价格按稀有度分档**
> （`inv:§8.2`，那条 `[推断]` 已消除）。⚠️ schema 变更把 `FORMAT_VERSION` 从 1 推到 **2** ——
> 内核的格表是固定的，旧镜像必须**响亮地**被拒，而不是把旧的 `extra` 当 `Rarity` 读成垃圾。

> ⚠️ **冻结方描述有误**：任务里写"卡牌奖励池是按角色 + 稀有度 + **是否在第一幕出现**的规则筛的"。现实是**只有角色 + 稀有度**两维；"是否在第一幕出现"是**事件池 / 药水池 /？（问号）房**的属性，卡牌池没有这个维度。第一幕真正独有的卡牌规则只有"升级概率 0%"。

---

### 3.6 无色牌（本项目用到的 3 张）

`Colorless_Cards`（wiki，核对于 2026-11-03）：全局 67 张，**不属于任何职业色**。本项目只做
三张 —— 它们唯一的入口是 Colorless Potion（§183/§185），**不进任何牌组**。

| `id` | name | 稀有度 | 类型 | 费用 | 效果（基准） |
|---|---|---|---|---|---|
| `bandage_up` | Bandage Up | **Uncommon** | Skill | 0 | Heal 4 HP. **Exhaust.** |
| `blind` | Blind | **Uncommon** | Skill | 0 | Apply 2 **Weak to ALL enemies**. **不 Exhaust** |
| `dark_shackles` | Dark Shackles | **Uncommon** | Skill | 0 | Enemy loses 9 **Strength this turn**. **Exhaust.** |

> 「升级」一列**故意不写**：本项目没有这三张的 `+` 行（它们只由药水在战斗内给出，没有任何牌组
> 装得下），写一个没人能到达的升级值只会变成下一个过期数字。

> ⚠️ **两处容易抄错的格子**（本项目第一次就抄错了，风景一样）：
> * **Blind 是 Uncommon**，不是 Common —— 无色牌里 Common 只有少数几张；
> * **Blind 不 Exhaust**（Bandage Up 与 Dark Shackles 才 Exhaust）。
>
> ⚠️ Dark Shackles 的 "**this turn**" 在我们的实现里是**两个状态**：`standard.lose_strength 9`
> （回合末把力量还回去）+ `standard.strength -9`（当场的减益）。净效果与 wiki 等价（这一回合少 9 点），
> 但状态面板上能看到两条 —— 这是**写明了的表示差异**，不是两条规则。

## 4. 敌人

约定：HP 给 **A0（无进阶）** 区间；行动给 **A0** 数值，进阶改动不在 v1 范围（§11）。

### 4.2 精英（第一幕 3 种，本项目先做 1 种）

原作第一幕有 3 个精英：Gremlin Nob（Enrage：打出技能时 +2 力量）、Lagavulin（睡 3 回合 + Metallicize
8）、**3 × Sentry**（Bolt 10 伤害 / Beam 9 伤害 + 洗 2 张 Dazed 进弃牌堆，各自带 Artifact 1）。

选 Sentry 是因为它是三者里**唯一能用现有节点表达**的：两个招式交替就是 `Actions` 的两项循环
（`blue_slaver` 同一写法），不需要新触发。

| 项 | 值 | 来源 / 降级 |
|---|---|---|
| `sentry` HP | 38–42 | wiki |
| `sentry.bolt` | 10 伤害 | wiki |
| `sentry.beam` | 9 伤害 | wiki；⚠️ **原作还会洗 2 张 `Dazed`** —— 本内容没有该卡，也没有 Ethereal（回合末在手则消耗）的任何一行在用那个钩子 |
| `enc_three_sentries` | 3 × sentry | §5.3 精英池 |
| Artifact 1 | **未实现** | 内核没有 Artifact 状态，也没有"抵消一次 debuff"的触发 |

> ⚠️ 结论写在这里而不是藏起来：**这个精英比原作容易**。少了 Dazed 的牌堆污染与 Artifact 的
> debuff 免疫，它是"同一只怪、更弱的一场仗"，不是等价替换。等 `Dazed`（含 Ethereal）与 Artifact
> 有了，这两处要补回来。

### 4.1 普通敌人（19 种实体）

| `id` | name | hp | 行动（A0） | AI 权重 / 限制（A0） | 特殊机制 |
|---|---|---|---|---|---|
| `acid_slime_s` | Acid Slime (S) | 8-12 | Tackle: 3 dmg. / Lick: apply 1 Weak. | 第 1 回合 50% Lick / 50% Tackle，之后两招交替。 | 无。 |
| `acid_slime_m` | Acid Slime (M) | 28-32 | Corrosive Spit: 7 dmg + shuffle 1 Slimed into discard. / Lick: apply 1 Weak. / Tackle: 10 dmg. | 每回合 30% Corrosive Spit / 40% Tackle / 30% Lick；Tackle 与 Lick 不能连续两次，其它招不能连三次。 | 不会分裂。 |
| `acid_slime_l` | Acid Slime (L) | 65-69 | Corrosive Spit: 11 dmg + shuffle 2 Slimed into discard. / Lick: apply 2 Weak. / Tackle: 16 dmg. | 同 (M)：30% / 40% / 30%，同样的连用限制。 | **Split**：HP ≤ 50% 时打断当前意图，死亡并生成 2 只 Acid Slime (M)，各自 HP = 分裂瞬间的当前 HP。 |
| `spike_slime_s` | Spike Slime (S) | 10-14 | Tackle: 5 dmg. | 只有一招。 | 无。 |
| `spike_slime_m` | Spike Slime (M) | 28-32 | Flame Tackle: 8 dmg + shuffle 1 Slimed into discard. / Lick: apply 1 Frail. | 30% Flame Tackle / 70% Lick；同一招不能连三次。 | 不会分裂。 |
| `spike_slime_l` | Spike Slime (L) | 64-70 | Flame Tackle: 16 dmg + shuffle 2 Slimed into discard. / Lick: apply 2 Frail. | 30% Flame Tackle / 70% Lick；同一招不能连三次。 | **Split**：HP ≤ 50% 时死亡并生成 2 只 Spike Slime (M)，HP = 当前 HP。 |
| `cultist` | Cultist | 48-54 | Incantation: gain 3 Ritual. / Dark Strike: 6 dmg. | 第 1 回合**必定** Incantation，之后**每回合** Dark Strike。 | **Ritual 3**（可叠层）：在它自己回合结束时 +3 Strength（永久）。 |
| `jaw_worm` | Jaw Worm | 40-44 | Chomp: 11 dmg. / Thrash: 7 dmg + 5 Block. / Bellow: gain 3 Strength + 6 Block. | 第 1 回合**必定** Chomp；之后 45% Bellow / 30% Thrash / 25% Chomp。Bellow 不能连续两次、Thrash 不能连三次、Chomp 不能连续两次。 | 无。 |
| `louse_red` | Red Louse（源内名 FuzzyLouseNormal） | 10-15 | Bite: D dmg，D 在战斗开始时从 5–7 中随机定一次。 / Grow: gain 3 Strength. | 每回合 25% Grow / 75% Bite；同一招不能连三次。 | 开场带 **Curl Up 3–7**（强度 3–7 随机）：第一次受到**攻击伤害**时获得等量 Block，只触发一次（多段攻击要等全部段数结算后才触发）。 |
| `louse_green` | Green Louse（源内名 FuzzyLouseDefensive） | 11-17 | Bite: D dmg，D ∈ {5,6,7} 开场随机。 / Spit Web: apply 2 Weak. | 每回合 25% Spit Web / 75% Bite；同一招不能连三次。 | 开场带 **Curl Up 3–7**，同上。 |
| `fungi_beast` | Fungi Beast | 22-28 | Bite: 6 dmg. / Grow: gain 3 Strength. | 每回合 60% Bite / 40% Grow；Bite 不能连三次、Grow 不能连续两次。 | **Spore Cloud 2**：死亡时给玩家 2 Vulnerable。 |
| `looter` | Looter | 44-48 | Mug: 10 dmg（并偷钱）. / Lunge: 12 dmg. / Smoke Bomb: gain 6 Block. / Escape: 逃跑（带走偷到的钱）. | 前两回合 Mug；第 3 回合 50% Lunge / 50% Smoke Bomb；若第 3 回合走了 Lunge，则下一回合 Smoke Bomb；Smoke Bomb 之后接 Escape。 | **Thievery 15**：每次攻击偷 15 金币（逃跑则永久失去）；击杀则全部归还。 |
| `blue_slaver` | Blue Slaver | 46-50 | Stab: 12 dmg. / Rake: 7 dmg + apply 1 Weak. | 每回合 40% Rake / 60% Stab；同一招不能连三次。 | 无。 |
| `red_slaver` | Red Slaver | 46-50 | Stab: 13 dmg. / Scrape: 8 dmg + apply 1 Vulnerable. / Entangle: apply 1 Entangled. | 第 1 回合**必定** Stab；之后每回合 25% 用 Entangle，未用则固定走 Scrape→Scrape→Stab 循环；Entangle 用掉之后 55% Scrape / 45% Stab；Stab 与 Scrape 都不能连三次。 | **Entangled**：该回合玩家不能打出 Attack。 |
| `fat_gremlin` | Fat Gremlin | 13-17 | Smash: 4 dmg + apply 1 Weak. | 只有一招。 | 无。 |
| `mad_gremlin` | Mad Gremlin | 20-24 | Scratch: 4 dmg. | 只有一招。 | **Angry 1**：每次受到攻击伤害 +1 Strength（强度可叠）。 |
| `sneaky_gremlin` | Sneaky Gremlin | 10-14 | Puncture: 9 dmg. | 只有一招。 | 无。 |
| `shield_gremlin` | Shield Gremlin | 12-15 | Protect: 给**另一个**敌人 7 Block. / Shield Bash: 6 dmg. | 有队友时**永远** Protect 队友（绝不 Protect 自己）；没有队友时用 Shield Bash，若该回合本应 Protect 则 Protect 自己。 | 无。 |
| `gremlin_wizard` | Gremlin Wizard | 21-25 | Charging: 无效果. / Ultimate Blast: 25 dmg. | 先 Charge 2 回合，第 3 回合 Ultimate Blast；之后每 Charge 3 回合放一次 Blast。 | 注意：HP 采信游戏文件 21–25，wiki 信息框写 23–25（见 §0 瑕疵 4）。 |

### 4.2 精英（3 种遭遇）

| `id` | name | hp | 行动（A0） | AI 权重 / 限制（A0） | 特殊机制 |
|---|---|---|---|---|---|
| `gremlin_nob` | Gremlin Nob | 82-86 | Bellow: gain 2 Enrage. / Rush: 14 dmg. / Skull Bash: 6 dmg + apply 2 Vulnerable. | 第 1 回合**必定** Bellow；之后 33% Skull Bash / 67% Rush；Rush 不能连三次。 | **Enrage 2**：玩家每打出一张 Skill，它 +2 Strength（层数可叠）。 |
| `lagavulin` | Lagavulin | 109-111 | Asleep: 不行动，但每回合开始获得 8 Block（Metallicize 8）. / Attack: 18 dmg. / Siphon Soul: 先 −1 Dexterity 再 −1 Strength. | 前 3 回合**必定** Asleep（第 3 回合结束时自己醒来，第 4 回合照常行动）；若中途因**穿透格挡的 HP 伤害**被唤醒，则先**眩晕 1 回合**。醒后循环：Attack → Attack → Siphon Soul。 | 唤醒时失去 Metallicize 8。`Dead Adventurer` 事件里的 Lagavulin **不睡**，直接以 Siphon Soul 起手。 |
| `sentry` | Sentry（精英遭遇 = 3 只） | 38-42 | Beam: 9 dmg. / Bolt: shuffle 2 Dazed into your discard pile. | 3 只时：**第 1、3 只**第 1 回合 Bolt，**第 2 只**第 1 回合 Beam；之后每只都在两招之间交替。 | 开场带 **Artifact 1**（抵消 1 次 debuff）。 |

### 4.3 Boss（三选一，全列）

| `id` | name | hp | 行动（A0） | 行动顺序（A0） | 特殊机制 |
|---|---|---|---|---|---|
| `the_guardian` | The Guardian | 240 | Charging Up: gain 9 Block. / Fierce Bash: 32 dmg. / Vent Steam: apply 2 Weak **然后** 2 Vulnerable. / Whirlwind: 5 dmg × 4. / （防御态）Defensive Mode: gain 3 Sharp Hide. / Roll Attack: 9 dmg. / Twin Slam: 8 dmg × 2. | **进攻态**固定循环 Charging Up → Fierce Bash → Vent Steam → Whirlwind。从防御态切回进攻态后的第一招是 Whirlwind，然后回到上述循环。**防御态**固定循环 Defensive Mode → Roll Attack → Twin Slam。 | **Mode Shift 30**：每受到 1 点 HP 伤害减 1；归零时打断当前意图、立刻切防御态并**立即获得 20 Block**。切回进攻态时 Mode Shift **+10**。Twin Slam 会移除 Sharp Hide 并切回进攻态。Sharp Hide 3：玩家每**打出**一张 Attack 就受 3 伤害（**可被 Block 抵挡**；多段攻击卡只触发 1 次）。 |
| `hexaghost` | Hexaghost | 250 | Activate: 无效果. / Divider: **6 × (H+1) dmg**，H = floor(玩家当前 HP / 12). / Sear: 6 dmg + shuffle 1 Burn into discard. / Tackle: 5 dmg × 2. / Inflame: gain 2 Strength + 12 Block. / Inferno: 2 dmg × 6 + shuffle 3 Burn into discard + 把所有 Burn 升级成 Burn+. | 第 1 回合 Activate，第 2 回合 Divider。之后用"绿色火焰计数"驱动固定序列：Sear(0) → Tackle(1) → Sear(2) → Inflame(3) → Tackle(4) → Sear(5) → **Inferno(6)** → 计数归零重来。 | 第一次 Inferno 之后，Sear 塞入的是 **Burn+**（每张 4 伤害，而非 Burn 的 2）。 |
| `slime_boss` | Slime Boss | 140 | Goop Spray: shuffle 3 Slimed into discard. / Preparing: 无效果. / Slam: 35 dmg. / Split. | 固定循环 Goop Spray → Preparing → Slam，直到分裂。 | **Split**：HP ≤ 50% 时打断当前意图，分裂成 1 只 **Acid Slime (L)** + 1 只 **Spike Slime (L)**，HP 都等于分裂瞬间的当前 HP。 |

> 三只 Boss 各自独立随机（不是"同一个种子固定三只"）：进入第 16 层时从 3 只里等概率选 1 只。【推断】（wiki 只说"三选一"，未给权重；`spire-archive` 不含遭遇表）

#### 4.3.1 本项目先做哪一只：**Slime Boss**（2026-10-22）

三只 Boss 各有一处**内核还表达不了**的机制，所以"先做一只"是选择**哪一处降级可以接受**：

| Boss | 缺的机制 | 为什么现在做不到 |
|---|---|---|
| The Guardian | **Mode Shift 30** + 防御态循环 | 需要"受到 HP 伤害时计数、归零则打断当前意图并切形态"的**受伤触发器 + 形态状态机** |
| Hexaghost | **Inferno 把所有 Burn 升级成 Burn+** | 需要"升级牌堆里的卡"这个节点；Divider 的 `6 × (floor(HP/12) + 1)` 反而**可以**做（`currentHealth` 已实现） |
| **Slime Boss** | **Split**（HP ≤ 50% 分裂成 Acid/Spike Slime L） | 需要"战斗中途生成敌人"；`CombatState` 的战斗员集合在建战斗时定下 |

选 Slime Boss：它的**循环**（Goop Spray → Preparing → Slam）三个动作都能照原样表达，
而 Split 是一次性的形态转换 —— 降级后它仍是"会塞 Slimed、会砸 35 的大怪"。

> ✅ **2026-11-03 更新**：Slime Boss **现在会分裂**（§178 的 `node.destroyCombatant` 到位后，
> "本体消失 + 两只顶替"才第一次能正确表达；§180 之前它靠"再生成两只"近似，会被同一回合的
> 多次伤害反复触发直到战斗员容器溢出）。
>
> 仍然缺的是另外两只 Boss 的机制：Guardian 的 **Mode Shift**（受伤计数 + 形态状态机）、
> Hexaghost 的 **Burn 升级**。"三选一"这一层仍然无从体现 —— `Boss` 池只有 1 个。

> `inv:§4.3` 说三只等概率三选一【推断】；本内容只有一只，所以"三选一"这一层现在无从体现。

---

### 4.4 第 2 / 3 幕的精英（本项目已实现，2026-11-03 回 wiki 复核）

第一幕的 3 个精英在 §4.2；第二、三幕的这 6 个是 §173 / §175 加的，数字来自各自的单怪页面。

| `id` | name | HP（A0） | AscHP | 行动（A0） | 特殊机制 |
|---|---|---|---|---|---|
| `book_of_stabbing` | Book of Stabbing | 160-164 | 168-172 | Multi-Stab: **6 × N**（N = 本场战斗已用次数 + 2）/ Single Stab: 21 | 每次 Multi-Stab 的段数**在场内递增** |
| `lagavulin` | Lagavulin | 109-111 | 112-115 | Asleep（不行动，Metallicize 8 每回合给 8 Block）/ Attack 18 / Siphon Soul（先 −1 Dexterity 再 −1 Strength） | 睡 3 回合自醒；被**穿透格挡的 HP 伤害**打醒则先眩晕 1 回合；醒后失去 Metallicize |
| `taskmaster` | Taskmaster（Slavers 遭遇） | 54-60 | 57-64 | Scouring Whip: 7 dmg + 往弃牌堆塞 1 张 **Wound**（A2 起 2 张，A18 起 3 张 + 1 力量） | 与 Slaver × 2 同场 |
| `nemesis` | Nemesis | 185 | 200 | Debuff / Attack 45 / Scythe 45（塞 3 Burn） | **每两回合 Intangible**（`standard.phantom_veil` 的载体） |
| `reptomancer` | Reptomancer | 180-190 | 190-200 | Spawn Dagger（召唤 Dagger，**最多 4 只**）/ Snake Strike 13×2 + 1 Weak / Big Bite 30（A3 起 34） | 匕首 Explode 会自毁 —— 我们**做不到**（见 `sts-wiki-gap.md` §C） |
| `giant_head` | Giant Head | **500** | **520** | Glare（1 Weak）/ It Is Time（30 dmg，**每次 +5**）/ Count | **本项目是简化版**：HP **320** + Metallicize 4 + 只有 Glare/Count 两招，**没有** It Is Time 的递增（§130 记录了这个偏差）。wiki 的 500 HP 对一局切片太长 |

> ⚠️ **召唤上限**：wiki 对 Reptomancer 写的是"最多 4 只 Dagger"，本项目的 `node.createCombatant`
> **没有上限参数**，唯一的界是 6 个敌人槽 —— 这是写明了的偏差。

## 5. 遭遇编成（Encounter）

### 5.1 规则

| 规则 | 内容 | 来源 |
|---|---|---|
| 池子 | 普通战斗分 **weak（前 3 场）/ strong（之后）** 两个池 | 【多源一致】`Act 1` 与 `Monsters` 两页分节一致 |
| 前 3 场 | 前 3 场普通战斗只从 weak 池抽，4 种等概率 25% | 【wiki】 |
| 之后 | 从 strong 池抽，权重见下表（权重和 = 100%） | 【wiki】 |
| 去重 | **同一遭遇不会在接下来 2 场普通战斗里重复**（连续 3 场必不同） | 【wiki】`Monsters` 页 |
| 精英去重 | 同一精英不能连续两场（Dead Adventurer 事件不受此限） | 【wiki】`Elites` 页 |
| 战斗类型统计 | 精英/普通/事件等由地图节点决定，遭遇表本身不带节点类型 | 【wiki】 |

### 5.2 weak 池（floor 1 节点 + 前 3 场普通战斗）

| `id` | 编成 | 权重 | 备注 |
|---|---|---|---|
| `enc_cultist` | Cultist ×1 | 25% | — |
| `enc_jaw_worm` | Jaw Worm ×1 | 25% | — |
| `enc_two_louses` | Louse ×2 | 25% | 每只独立 50% 红 / 50% 绿 |
| `enc_small_slimes` | Slime (M) ×1 + Slime (S) ×1 | 25% | M 独立 50% Acid / 50% Spike；S 独立 50% Acid / 50% Spike |

### 5.3 strong 池（第 4 场普通战斗起）

| `id` | 编成 | 权重 | 备注 |
|---|---|---|---|
| `enc_gremlin_gang` | Gremlin ×4（从 2 Mad / 2 Sneaky / 2 Fat / 1 Wizard / 1 Shield 里随机取 4） | 6.25% | 按名额抽，不重复取同一名额 |
| `enc_large_slime` | Acid Slime (L) 或 Spike Slime (L) ×1 | 12.5% | 50/50 二选一 |
| `enc_lots_of_slimes` | Spike Slime (S) ×3 + Acid Slime (S) ×2 | 6.25% | 固定编成 |
| `enc_blue_slaver` | Blue Slaver ×1 | 12.5% | — |
| `enc_red_slaver` | Red Slaver ×1 | 6.25% | — |
| `enc_three_louses` | Louse ×3 | 12.5% | 每只独立 50% 红 / 50% 绿 |
| `enc_two_fungi_beasts` | Fungi Beast ×2 | 12.5% | — |
| `enc_exordium_thugs` | (Louse ×1 或 Acid/Spike Slime (M) ×1) + (Looter ×1 或 Cultist ×1 或 任一 Slaver ×1) | 9.375% | 两段各自随机 |
| `enc_exordium_wildlife` | (Fungi Beast ×1 或 Jaw Worm ×1) + (Louse ×1 或 Acid/Spike Slime (M) ×1) | 9.375% | 两段各自随机 |
| `enc_looter` | Looter ×1 | 12.5% | 第 6 周补丁把它从前 3 场池移出 |

合计 10 项，权重和 = 100%。【wiki】

### 5.4 精英遭遇（3 种，等概率 1/3）

| `id` | 编成 | 权重 | 备注 |
|---|---|---|---|
| `enc_gremlin_nob` | Gremlin Nob ×1 | 33.33% | 【推断】等概率 |
| `enc_lagavulin` | Lagavulin ×1 | 33.33% | 【推断】等概率 |
| `enc_three_sentries` | Sentry ×3 | 33.33% | 【推断】等概率 |

### 5.5 Boss（1 只，等概率）

| `id` | 编成 | 权重 |
|---|---|---|
| `enc_the_guardian` | The Guardian ×1 | 33.33% |
| `enc_hexaghost` | Hexaghost ×1 | 33.33% |
| `enc_slime_boss` | Slime Boss ×1 | 33.33% |

---

## 6. 遗物（Ironclad 第一幕可获取 140 件 + 起始 1 件）

**遗物池不按幕筛**（同一个 Common 池从第 1 幕到第 3 幕一致），所以"第一幕能拿到的遗物"= "Ironclad 能拿到的遗物"，差别只在**获取渠道**：普通战斗不掉遗物，精英/宝箱/商店/事件/Boss 宝箱才掉。【wiki】

**筛选口径**：

- 以 wiki `Relics` 页的 `Class-Specific` 分节判定职业归属，只保留 **shared + ironclad-only**。【wiki】
- 剔除 `Discerning Monocle`（`relics.json` 有、wiki 汇编清单没有 ⇒ 未实装/废弃）与 `Red Circlet`（占位）【游戏文件 + wiki 对比】。
- `Special`（事件专属）只保留**第一幕事件**产出的 10 件；其余 8 件来自 Act 2/3 事件（Forgotten Altar / Cursed Tome / Mind Bloom / Tomb of Lord Red Mask / Augmenter / N'loth），第一幕拿不到。【wiki】

> 效果文本里的 `[Energy]` / `[R]` 是游戏内的能量图标，表示 **1 点能量**（Ironclad 的能量图标为红色 `[R]`，其余角色为 `[Energy]`）。

| 池 | 件数 | 获取渠道 |
|---|---|---|
| Common | 33 | 宝箱（小箱为主）/ 精英战利品 / 商店 / Neow / 事件 |
| Uncommon | 30 | 宝箱（中箱为主）/ 精英 / 商店 / 事件 |
| Rare | 28 | 宝箱（大箱为主）/ 精英 / 商店 / 事件 |
| Shop | 17 | **仅商店第 3 个遗物位** |
| Boss | 22 | **仅 Boss 宝箱**（每幕 3 选 1） |
| 事件专属（第一幕可达） | 10 | 对应事件 |
| 起始 | 1 | Burning Blood（Ironclad 初始） |

### 6.1 Common（33 件）

| `id` | name | effect | 归属 |
|---|---|---|---|
| `akabeko` | Akabeko | Your first Attack each combat deals 8 additional damage. | shared |
| `anchor` | Anchor | Start each combat with 10 Block. | shared |
| `ancient_tea_set` | Ancient Tea Set | Whenever you enter a Rest Site, start the next combat with [Energy] [Energy]. | shared |
| `art_of_war` | Art of War | If you do not play any Attacks during your turn, gain an additional [Energy] next turn. | shared |
| `bag_of_marbles` | Bag of Marbles | At the start of each combat, apply 1 Vulnerable to ALL enemies. | shared |
| `bag_of_preparation` | Bag of Preparation | At the start of each combat, draw 2 additional cards. | shared |
| `blood_vial` | Blood Vial | At the start of each combat, heal 2 HP. | shared |
| `bronze_scales` | Bronze Scales | Start each combat with 3 Thorns. | shared |
| `centennial_puzzle` | Centennial Puzzle | The first time you lose HP each combat, draw 3 cards. | shared |
| `ceramic_fish` | Ceramic Fish | Whenever you add a card to your deck, gain 9 Gold. | shared |
| `dream_catcher` | Dream Catcher | Whenever you Rest, you may add a card into your deck. | shared |
| `happy_flower` | Happy Flower | Every 3 turns, gain [Energy]. | shared |
| `juzu_bracelet` | Juzu Bracelet | Normal enemy combats are no longer encountered in ? rooms. | shared |
| `lantern` | Lantern | Start each combat with an additional [Energy] | shared |
| `maw_bank` | Maw Bank | Whenever you climb a floor, gain 12 Gold. No longer works when you spend any Gold at a shop. | shared |
| `meal_ticket` | Meal Ticket | Whenever you enter a shop, heal 15 HP. | shared |
| `nunchaku` | Nunchaku | Every 10 Attacks, gain [Energy]. | shared |
| `oddly_smooth_stone` | Oddly Smooth Stone | Start each combat with 1 Dexterity. | shared |
| `omamori` | Omamori | Negate the next 2 Curses you obtain. | shared |
| `orichalcum` | Orichalcum | If you end your turn without Block, gain 6 Block. | shared |
| `pen_nib` | Pen Nib | Every 10th Attack you play deals double damage. | shared |
| `potion_belt` | Potion Belt | Upon pickup, gain 2 Potion slots. | shared |
| `preserved_insect` | Preserved Insect | Enemies in Elite combats have 25 % less HP. | shared |
| `red_skull` | Red Skull | While your HP is at or below 50%, you have 3 additional Strength. | ironclad-only |
| `regal_pillow` | Regal Pillow | Whenever you Rest, heal an additional 15 HP. | shared |
| `smiling_mask` | Smiling Mask | The Merchant's card removal service now always costs 50 Gold. | shared |
| `strawberry` | Strawberry | Upon pickup, raise your Max HP by 7. | shared |
| `the_boot` | The Boot | Whenever you would deal 4 or less unblocked attack damage, increase it to 5. | shared |
| `tiny_chest` | Tiny Chest | Every 4th ? room is a Treasure room. | shared |
| `toy_ornithopter` | Toy Ornithopter | Whenever you use a potion, heal 5 HP. | shared |
| `vajra` | Vajra | Start each combat with 1 Strength. | shared |
| `war_paint` | War Paint | Upon pickup, Upgrade 2 random Skills. | shared |
| `whetstone` | Whetstone | Upon pickup, Upgrade 2 random Attacks. | shared |

### 6.2 Uncommon（30 件）

| `id` | name | effect | 归属 |
|---|---|---|---|
| `blue_candle` | Blue Candle | Unplayable Curse cards can now be played. Whenever you play a Curse, lose 1 HP and Exhaust it. | shared |
| `bottled_flame` | Bottled Flame | Upon pickup, choose an Attack. Start each combat with this card in your hand. | shared |
| `bottled_lightning` | Bottled Lightning | Upon pickup, choose a Skill. Start each combat with this card in your hand. | shared |
| `bottled_tornado` | Bottled Tornado | Upon pickup, choose a Power card. Start each combat with this card in your hand. | shared |
| `darkstone_periapt` | Darkstone Periapt | Whenever you obtain a Curse, increase your Max HP by 6. | shared |
| `eternal_feather` | Eternal Feather | For every 5 cards in your deck, heal 3 HP whenever you enter a Rest Site. | shared |
| `frozen_egg` | Frozen Egg | Whenever you add a Power card into your deck, Upgrade it. | shared |
| `gremlin_horn` | Gremlin Horn | Whenever an enemy dies, gain [Energy] and draw 1 card. | shared |
| `horn_cleat` | Horn Cleat | At the start of your 2nd turn, gain 14 Block. | shared |
| `ink_bottle` | Ink Bottle | Whenever you play 10 cards, draw 1 card. | shared |
| `kunai` | Kunai | Every time you play 3 Attacks in a single turn, gain 1 Dexterity. | shared |
| `letter_opener` | Letter Opener | Every time you play 3 Skills in a single turn, deal 5 damage to ALL enemies. | shared |
| `matryoshka` | Matryoshka | The next 2 non-Boss chests you open contain 2 Relics. | shared |
| `meat_on_the_bone` | Meat on the Bone | If your HP is at or below 50% at the end of combat, heal 12 HP. | shared |
| `mercury_hourglass` | Mercury Hourglass | At the start of your turn, deal 3 damage to ALL enemies. | shared |
| `molten_egg` | Molten Egg | Whenever you add an Attack into your deck, Upgrade it. | shared |
| `mummified_hand` | Mummified Hand | Whenever you play a Power card, a random card in your hand costs 0 that turn. | shared |
| `ornamental_fan` | Ornamental Fan | Every time you play 3 Attacks in a single turn, gain 4 Block. | shared |
| `pantograph` | Pantograph | At the start of Boss combats, heal 25 HP. | shared |
| `paper_phrog` | Paper Phrog | Enemies with Vulnerable take 75% more damage rather than 50%. | ironclad-only |
| `pear` | Pear | Upon pickup, raise your Max HP by 10. | shared |
| `question_card` | Question Card | Future card rewards have 1 additional card to choose from. | shared |
| `self_forming_clay` | Self-Forming Clay | Whenever you lose HP, gain 3 Block next turn. | ironclad-only |
| `shuriken` | Shuriken | Every time you play 3 Attacks in a single turn, gain 1 Strength. | shared |
| `singing_bowl` | Singing Bowl | When adding cards into your deck, you may raise your Max HP by 2 instead. | shared |
| `strike_dummy` | Strike Dummy | Cards containing Strike deal 3 additional damage. | shared |
| `sundial` | Sundial | Every 3 times you shuffle your draw pile, gain [Energy] [Energy]. | shared |
| `the_courier` | The Courier | The Merchant restocks cards, relics, and potions. All prices are reduced by 20%. | shared |
| `toxic_egg` | Toxic Egg | Whenever you add a Skill into your deck, Upgrade it. | shared |
| `white_beast_statue` | White Beast Statue | Potions always appear in combat rewards. | shared |

### 6.3 Rare（28 件）

| `id` | name | effect | 归属 |
|---|---|---|---|
| `bird_faced_urn` | Bird-Faced Urn | Whenever you play a Power card, heal 2 HP. | shared |
| `calipers` | Calipers | At the start of your turn, lose 15 Block rather than all of your Block. | shared |
| `captains_wheel` | Captain's Wheel | At the start of your 3rd turn, gain 18 Block. | shared |
| `champion_belt` | Champion Belt | Whenever you apply Vulnerable, apply 1 Weak. | ironclad-only |
| `charons_ashes` | Charon's Ashes | Whenever you Exhaust a card, deal 3 damage to ALL enemies. | ironclad-only |
| `dead_branch` | Dead Branch | Whenever you Exhaust a card, add a random card into your hand. | shared |
| `du_vu_doll` | Du-Vu Doll | For each Curse in your deck, start each combat with 1 Strength. | shared |
| `fossilized_helix` | Fossilized Helix | Prevent the first time you would lose HP each combat. | shared |
| `gambling_chip` | Gambling Chip | At the start of each combat, discard any number of cards, then draw that many cards. | shared |
| `ginger` | Ginger | You can no longer become Weakened. | shared |
| `girya` | Girya | You can now gain Strength at Rest Sites (up to 3 times). | shared |
| `ice_cream` | Ice Cream | Energy is now conserved between turns. | shared |
| `incense_burner` | Incense Burner | Every 6 turns, gain 1 Intangible. | shared |
| `lizard_tail` | Lizard Tail | When you would die, heal to 50% of your Max HP instead (works once). | shared |
| `magic_flower` | Magic Flower | Healing is 50% more effective during combat. | ironclad-only |
| `mango` | Mango | Upon pickup, raise your Max HP by 14. | shared |
| `old_coin` | Old Coin | Upon pickup, gain 300 Gold. | shared |
| `peace_pipe` | Peace Pipe | You can now remove cards from your deck at Rest Sites. | shared |
| `pocketwatch` | Pocketwatch | Whenever you play 3 or less cards during your turn, draw 3 additional cards at the start of your next turn. | shared |
| `prayer_wheel` | Prayer Wheel | Normal enemies drop an additional card reward. | shared |
| `shovel` | Shovel | You can now Dig for relics at Rest Sites. | shared |
| `stone_calendar` | Stone Calendar | At the end of turn 7, deal 52 damage to ALL enemies. | shared |
| `thread_and_needle` | Thread and Needle | Start each combat with 4 Plated Armor. | shared |
| `torii` | Torii | Whenever you would receive 5 or less unblocked attack damage, reduce it to 1. | shared |
| `tungsten_rod` | Tungsten Rod | Whenever you would lose HP, lose 1 less. | shared |
| `turnip` | Turnip | You can no longer become Frail. | shared |
| `unceasing_top` | Unceasing Top | Whenever you have no cards in hand during your turn, draw a card. | shared |
| `wing_boots` | Wing Boots | You may ignore paths when choosing the next room to travel to 3 times. | shared |

### 6.4 Shop（仅商店）（17 件）

| `id` | name | effect | 归属 |
|---|---|---|---|
| `brimstone` | Brimstone | At the start of your turn, gain 2 Strength and ALL enemies gain 1 Strength. | ironclad-only |
| `cauldron` | Cauldron | Upon pickup, brews 5 random potions. | shared |
| `chemical_x` | Chemical X | The effects of your cost X cards are increased by 2 | shared |
| `clockwork_souvenir` | Clockwork Souvenir | Start each combat with 1 Artifact. | shared |
| `dollys_mirror` | Dolly's Mirror | Upon pickup, obtain an additional copy of a card in your deck. | shared |
| `frozen_eye` | Frozen Eye | When viewing your Draw Pile, the cards are now shown in order. | shared |
| `hand_drill` | Hand Drill | Whenever you break an enemy's Block, apply 2 Vulnerable. | shared |
| `lees_waffle` | Lee's Waffle | Upon pickup, raise your Max HP by 7 and heal all of your HP. | shared |
| `medical_kit` | Medical Kit | Unplayable Status cards can now be played. Whenever you play a Status card, Exhaust it. | shared |
| `membership_card` | Membership Card | 50% discount on all products! | shared |
| `orange_pellets` | Orange Pellets | Whenever you play a Power, Attack, and Skill in the same turn, remove all of your debuffs. | shared |
| `orrery` | Orrery | Upon pickup, choose and add 5 cards to your deck. | shared |
| `prismatic_shard` | Prismatic Shard | Combat reward screens now contain Colorless cards and cards from other colors. | shared |
| `sling_of_courage` | Sling of Courage | Start each Elite combat with 2 Strength. | shared |
| `strange_spoon` | Strange Spoon | Cards which Exhaust when played will instead discard 50% of the time. | shared |
| `the_abacus` | The Abacus | Whenever you shuffle your draw pile, gain 6 Block. | shared |
| `toolbox` | Toolbox | At the start of each combat, choose 1 of 3 random Colorless cards and add the chosen card into your hand. | shared |

### 6.5 Boss（仅 Boss 宝箱）（22 件）

| `id` | name | effect | 归属 |
|---|---|---|---|
| `astrolabe` | Astrolabe | Upon pickup, Transform 3 cards, then Upgrade them. | shared |
| `black_blood` | Black Blood | Replaces Burning Blood. At the end of combat, heal 12 HP. | ironclad-only |
| `black_star` | Black Star | Elites drop an additional relic when defeated. | shared |
| `busted_crown` | Busted Crown | Gain [Energy] at the start of your turn. Future card rewards have 2 less cards to choose from. | shared |
| `calling_bell` | Calling Bell | Upon pickup, obtain a unique Curse and 3 relics. | shared |
| `coffee_dripper` | Coffee Dripper | Gain [Energy] at the start of your turn. You can no longer Rest at Rest Sites. | shared |
| `cursed_key` | Cursed Key | Gain [Energy] at the start of your turn. Whenever you open a non-boss chest, obtain a Curse. | shared |
| `ectoplasm` | Ectoplasm | Gain [Energy] at the start of your turn. You can no longer gain Gold. | shared |
| `empty_cage` | Empty Cage | Upon pickup, remove 2 cards from your deck. | shared |
| `fusion_hammer` | Fusion Hammer | Gain [Energy] at the start of your turn. You can no longer Smith at Rest Sites. | shared |
| `mark_of_pain` | Mark of Pain | Gain [R] at the start of your turn. At the start of combat, shuffle 2 Wounds into your draw pile. | ironclad-only |
| `pandoras_box` | Pandora's Box | Upon pickup, Transform all Strike and Defend cards. | shared |
| `philosophers_stone` | Philosopher's Stone | Gain [Energy] at the start of your turn. ALL enemies start combat with 1 Strength. | shared |
| `runic_cube` | Runic Cube | Whenever you lose HP, draw 1 card. | ironclad-only |
| `runic_dome` | Runic Dome | Gain [Energy] at the start of your turn. You can no longer see enemy Intents. | shared |
| `runic_pyramid` | Runic Pyramid | At the end of your turn, you no longer discard your hand. | shared |
| `sacred_bark` | Sacred Bark | Double the effectiveness of potions. | shared |
| `slavers_collar` | Slaver's Collar | Gain [Energy] at the start of your turn during Boss and Elite combats. | shared |
| `snecko_eye` | Snecko Eye | At the start of your turn, draw 2 additional cards. Start each combat Confused. | shared |
| `sozu` | Sozu | Gain [Energy] at the start of your turn. You can no longer obtain Potions. | shared |
| `tiny_house` | Tiny House | Upon pickup, obtain 1 potion. Gain 50 Gold. Raise your Max HP by 5. Obtain 1 card. Upgrade 1 random card. | shared |
| `velvet_choker` | Velvet Choker | Gain [Energy] at the start of your turn. You cannot play more than 6 cards per turn. | shared |

### 6.6 事件专属（第一幕可达）（10 件）

| `id` | name | effect | 归属 |
|---|---|---|---|
| `cultist_headpiece` | Cultist Headpiece | You feel more talkative. | event-only |
| `face_of_cleric` | Face Of Cleric | At the end of combat, raise your Max HP by 1. | event-only |
| `golden_idol` | Golden Idol | Enemies drop 25% more Gold. | event-only |
| `gremlin_visage` | Gremlin Visage | Start each combat with 1 Weak. | event-only |
| `nloths_hungry_face` | N'loth's Hungry Face | The next non-Boss chest you open is empty. | event-only |
| `neows_lament` | Neow's Lament | Enemies in your first 3 combats will have 1 HP. | event-only |
| `odd_mushroom` | Odd Mushroom | When Vulnerable, take 25% more attack damage rather than 50%. | event-only |
| `spirit_poop` | Spirit Poop | It's unpleasant. | event-only |
| `ssserpent_head` | Ssserpent Head | Whenever you enter a ? room, gain 50 Gold. | event-only |
| `warped_tongs` | Warped Tongs | At the start of your turn, Upgrade a random card in your hand for the rest of combat. | event-only |

---

## 7. 地图与节点生成

### 7.1 版式

| 参数 | 值 | 来源 |
|---|---|---|
| 网格 | **7 列 × 15 行**（不规则等距网格；每行最多 6 个可用节点） | 【wiki】Steam 逆向指南 + wiki.gg `Map Generation` |
| 总层数 | 15 层节点 + 第 16 层 Boss + 第 17 层 Boss 宝箱 = **17 floor** | 【wiki】 |
| 路径数 | **6 条** | 【wiki】 |
| 连线 | 每个节点有 1–3 条上行连边；从第 1 层某节点出发，连到第 2 层最近的 3 个节点之一，逐层向上 | 【wiki】 |
| 前 2 条路径 | 第 1 层起点**不能相同**（保证至少 2 个不同开局） | 【wiki】 |
| 交叉 | **路径不可交叉**（同一层上两条路径的相对左右次序在上一层保持不变） | 【wiki】 |
| 孤点 | 生成结束后裁掉没有任何连边的节点 | 【wiki】 |

### 7.2 固定楼层（不参与随机）

| floor | 内容 |
|---|---|
| 1 | 全部节点 = 普通战斗，从 **weak 池**抽（玩家可任选一个开局） |
| 9 | 全部节点 = **宝箱房** |
| 15 | 全部节点 = **篝火** |
| 16 | 全部路线汇入**同一个 Boss** |
| 17 | Boss 宝箱（地图上不显示，但计入 floor 数） |

### 7.3 其余节点的类型掷点（A0）

| 节点类型 | 权重 |
|---|---|
| 普通战斗 | **53%** |
| 精英 | **8%** |
| 篝火 | **12%** |
| 商店 | **5%** |
| ？（未知） | **22%** |

【wiki】wiki.gg `Map Generation`。A1 起精英权重改成 16%、普通战斗降到 45%（**超出 v1 范围，见 §11**）。

### 7.4 掷点后的硬性覆写规则

| # | 规则 | 来源 |
|---|---|---|
| 1 | **精英与篝火不出现在第 6 层以下**（floor 1–5 不会有精英/篝火） | 【wiki】 |
| 2 | **精英、商店、篝火都不能"连续"**（同一路径上不能出现两个相邻的同类节点） | 【wiki】 |
| 3 | 一个节点若有 ≥2 条出边，**其所有目的节点的类型必须互不相同** | 【wiki】 |
| 4 | **篝火不出现在第 14 层**（避免紧邻第 15 层篝火） | 【wiki】 |
| 5 | 违反上述任一条就按 7.3 的权重**重掷**，直到满足 | 【wiki】 |

> 规则 1+3 的耦合后果（值得记一笔）：floor 1–5 上一个 3 岔口必然是 **1 普通战斗 + 1 事件 + 1 商店**，因为精英/篝火在此区间不可用、而目的节点类型又必须互异。【推断】

### 7.5 ？（未知）房的实际内容

进入时按下列概率决定（**是"累计递增"的概率，不是固定权重**）：

| 内容 | 初始概率 | 每次该内容未出现 | 命中后 |
|---|---|---|---|
| 普通战斗 | 10% | +10% | 重置 10% |
| 宝箱 | 2% | +2% | 重置 2% |
| 商店 | 3% | +3% | 重置 3% |
| 事件 | 以上都没命中时的兜底 | — | — |

【wiki】`Unknown Location`。三个计数在**每一幕开始时重置**。（`Deadly Events` 自定义修饰符才会让 ? 房出精英，不在 v1 范围。）

---

## 8. 非战斗节点

### 8.1 篝火 Rest Site

| 选项 | 效果 | 条件 |
|---|---|---|
| Rest | 回复 **30% 最大 HP**（向下取整） | 默认 |
| Smith | 升级 1 张自选卡 | 默认 |
| Lift | 永久 +1 Strength，**每局最多 3 次** | 需遗物 Girya |
| Toke | 删除 1 张自选卡 | 需遗物 Peace Pipe |
| Dig | 获得 1 个随机遗物 | 需遗物 Shovel |

【wiki】每次进篝火只能选一项。第 15 层必定是篝火（Boss 前必有篝火）。

### 8.2 商店 Merchant

| 位置 | 内容 | 价格 |
|---|---|---|
| 彩色卡 ×5 | 固定 2 Attack + 2 Skill + 1 Power（角色色） | Common 45–55 / Uncommon 68–82 / Rare 135–165；**其中 1 张必定半价** |
| 无色卡 ×2 | 左 Uncommon、右 Rare | Uncommon 81–99 / Rare 162–198 |
| 遗物 ×3 | 第 3 个**必定是 Shop 池** | Common 143–157 / Uncommon 238–262 / Rare 285–315 / Shop 143–157 |
| 药水 ×3 | 随机 | Common 48–52 / Uncommon 72–78 / Rare 95–105 |
| 删卡服务 | 每次进店限 1 次 | 首次 **75**，此后**每次使用时 +25**（跨店累计） |

**【wiki】** 卡牌稀有度掷点受 §3.5 的偏移量影响，但商店**不修改**偏移量。

### 8.3 宝箱 Treasure Room

| 箱型 | 出现率 | Common | Uncommon | Rare | 出金币概率 | 金币量 |
|---|---|---|---|---|---|---|
| 小箱 | 50% | 75% | 25% | 0% | 50% | 23–27 |
| 中箱 | 33% | 35% | 50% | 15% | 35% | 45–55 |
| 大箱 | 17% | 0% | 75% | 25% | 50% | 68–82 |

【wiki】`Chest`。普通宝箱给 1 个遗物（Common/Uncommon/Rare 池），可以跳过不开。Boss 宝箱（第 17 层）给 **3 个 Boss 遗物里选 1**。

### 8.4 事件（第一幕 26 个）

事件只从 **？房** 出现。每个事件一行一分支，字段固定。

| `id` | event | 池 | option | effect | 前置/备注 |
|---|---|---|---|---|---|
| `big_fish` | Big Fish | act1 | Banana | 回复 floor(最大HP/3) 的 HP |  |
| `big_fish` | Big Fish | act1 | Donut | 最大 HP +5（并回复等量 HP） |  |
| `big_fish` | Big Fish | act1 | Box | 获得 1 个随机 Common/Uncommon/Rare 遗物；获得诅咒 Regret |  |
| `the_cleric` | The Cleric | act1 | Heal | 支付 35 金币，回复 25% 最大 HP | 只有金币 ≥35 时才会遇到本事件 |
| `the_cleric` | The Cleric | act1 | Purify | 支付 50 金币，删除 1 张卡 |  |
| `the_cleric` | The Cleric | act1 | Leave | 什么都不发生 |  |
| `dead_adventurer` | Dead Adventurer | act1 | Search | 每次搜索随机得到 {30 金币, 1 个随机遗物, 空} 之一（各只出一次）；每次搜索有 25% 触发精英回来打你，且每次搜查后再 +25%；成功搜 3 次事件结束 | 只在 floor ≥ 7 出现 |
| `dead_adventurer` | Dead Adventurer | act1 | Escape | 立刻结束事件，保留已搜到的东西 |  |
| `dead_adventurer` | Dead Adventurer | act1 | （精英战） | 按开场文本决定：Lagavulin（**不睡**，直接 Siphon Soul）/ 3× Sentry / Gremlin Nob；打赢得到"还没搜到的那部分奖励" + 25–35 金币；若已搜到遗物则不再额外给遗物 |  |
| `golden_idol_event` | Golden Idol | act1 | Take → Outrun | 获得遗物 Golden Idol；获得诅咒 Injury |  |
| `golden_idol_event` | Golden Idol | act1 | Take → Smash | 获得遗物 Golden Idol；受到 25% 最大 HP 的伤害 |  |
| `golden_idol_event` | Golden Idol | act1 | Take → Hide | 获得遗物 Golden Idol；**最大 HP −8%** |  |
| `golden_idol_event` | Golden Idol | act1 | Leave | 什么都不发生 |  |
| `hypnotizing_colored_mushrooms` | Hypnotizing Colored Mushrooms | act1 | Stomp | 与 3 只 Fungi Beast 战斗；胜利必得遗物 Odd Mushroom | 只在 floor ≥ 7 出现 |
| `hypnotizing_colored_mushrooms` | Hypnotizing Colored Mushrooms | act1 | Eat | 回复 25% 最大 HP；获得诅咒 Parasite |  |
| `living_wall` | Living Wall | act1 | Forget | 删除 1 张卡 |  |
| `living_wall` | Living Wall | act1 | Change | Transform 1 张卡（变成随机同色卡） |  |
| `living_wall` | Living Wall | act1 | Grow | 升级 1 张卡 |  |
| `scrap_ooze` | Scrap Ooze | act1 | Reach Inside | 失去 3 HP，25% 概率摸到 1 个遗物；没摸到可重复，每次额外 +1 HP 代价、+10% 概率 |  |
| `scrap_ooze` | Scrap Ooze | act1 | Leave | 什么都不发生 |  |
| `shining_light` | Shining Light | act1 | Enter | 随机升级 2 张卡；受到 20% 最大 HP 的伤害 |  |
| `shining_light` | Shining Light | act1 | Leave | 什么都不发生 |  |
| `the_ssssserpent` | The Ssssserpent | act1 | Agree | 获得 175 金币；获得诅咒 Doubt |  |
| `the_ssssserpent` | The Ssssserpent | act1 | Disagree | 什么都不发生 |  |
| `world_of_goop` | World of Goop | act1 | Gather Gold | 获得 75 金币；失去 11 HP |  |
| `world_of_goop` | World of Goop | act1 | Leave It | 失去 20–50 金币（不超过当前金币） |  |
| `wing_statue` | Wing Statue | act1 | Pray | 删除 1 张卡；失去 7 HP |  |
| `wing_statue` | Wing Statue | act1 | Destroy | 获得 50–80 金币 | 前置：卡组里有一张**单段 ≥10 伤害**的攻击卡 |
| `wing_statue` | Wing Statue | act1 | Leave | 什么都不发生 |  |
| `face_trader` | Face Trader | act1+2 | Touch | 失去 10% 最大 HP；获得 75 金币 |  |
| `face_trader` | Face Trader | act1+2 | Trade | 随机获得 1 件事件遗物：40% 好脸（Face of Cleric / Ssserpent Head）/ 20% 中性（Cultist Headpiece）/ 40% 坏脸（Gremlin Visage / N'loth's Hungry Face） |  |
| `face_trader` | Face Trader | act1+2 | Leave | 什么都不发生 |  |
| `a_note_for_yourself` | A Note For Yourself | shared | Take and Give | 取走存档里存的卡、并把卡组里 1 张卡存进去（首次存档里是 Iron Wave） |  |
| `a_note_for_yourself` | A Note For Yourself | shared | Ignore | 什么都不发生 |  |
| `bonfire_spirits` | Bonfire Spirits | shared | Offer（Curse） | 删掉该诅咒；获得遗物 Spirit Poop |  |
| `bonfire_spirits` | Bonfire Spirits | shared | Offer（Basic） | 删掉该基础牌；没有回报 |  |
| `bonfire_spirits` | Bonfire Spirits | shared | Offer（Common/Special） | 删掉该卡；回复 5 HP |  |
| `bonfire_spirits` | Bonfire Spirits | shared | Offer（Uncommon） | 删掉该卡；回满 HP |  |
| `bonfire_spirits` | Bonfire Spirits | shared | Offer（Rare） | 删掉该卡；回满 HP 且最大 HP +10 |  |
| `the_divine_fountain` | The Divine Fountain | shared | Drink | 删除卡组里**所有**诅咒 | 仅当卡组里有可删的诅咒时才出现 |
| `duplicator` | Duplicator | shared | Pray | 复制 1 张卡（升级状态一起复制） |  |
| `duplicator` | Duplicator | shared | Leave | 什么都不发生 |  |
| `golden_shrine` | Golden Shrine | shared | Pray | 获得 100 金币 |  |
| `golden_shrine` | Golden Shrine | shared | Desecrate | 获得 275 金币；获得诅咒 Regret |  |
| `golden_shrine` | Golden Shrine | shared | Leave | 什么都不发生 |  |
| `lab` | Lab | shared | Search | 获得 3 瓶随机药水 |  |
| `match_and_keep` | Match and Keep | shared | Play | 翻牌配对小游戏，5 次机会；配上的卡全部加入卡组。牌面 6 对：1 对基础牌（Bash/Neutralize/Zap/Eruption 按角色）、1 对 Common、1 对 Uncommon、1 对 Rare、1 对诅咒、1 对 Uncommon 无色 |  |
| `ominous_forge` | Ominous Forge | shared | Forge | 升级 1 张卡 | 需有可升级的卡 |
| `ominous_forge` | Ominous Forge | shared | Rummage | 获得遗物 Warped Tongs；获得诅咒 Pain |  |
| `ominous_forge` | Ominous Forge | shared | Leave | 什么都不发生 |  |
| `purifier` | Purifier | shared | Pray | 删除 1 张卡 |  |
| `purifier` | Purifier | shared | Leave | 什么都不发生 |  |
| `transmogrifier` | Transmogrifier | shared | Pray | Transform 1 张卡 |  |
| `transmogrifier` | Transmogrifier | shared | Leave | 什么都不发生 |  |
| `upgrade_shrine` | Upgrade Shrine | shared | Pray | 升级 1 张卡 | 仅当有可升级的卡时出现 |
| `upgrade_shrine` | Upgrade Shrine | shared | Leave | 什么都不发生 |  |
| `we_meet_again` | We Meet Again! | shared | Give Potion | 交出 1 瓶药水；获得 1 个随机 Common/Uncommon/Rare 遗物 | 需至少有 1 瓶药水 |
| `we_meet_again` | We Meet Again! | shared | Give Gold | 交出 50–150 金币；获得 1 个随机 Common/Uncommon/Rare 遗物 | 需至少 50 金币 |
| `we_meet_again` | We Meet Again! | shared | Give Card | 删掉 1 张卡；获得 1 个随机 Common/Uncommon/Rare 遗物 | 该卡不能是诅咒/基础牌/Bottled 卡 |
| `we_meet_again` | We Meet Again! | shared | Attack | 什么都不发生 |  |
| `wheel_of_change` | Wheel of Change | shared | Play（无选择） | 6 个等概率格子：①100 金币（第一幕） ②随机 Common/Uncommon/Rare 遗物（不含 Bottled Flame/Lightning/Tornado/Whetstone） ③回满 HP ④获得诅咒 Decay ⑤删除 1 张卡 ⑥受到 10% 最大 HP 的伤害 | 本事件是 Shrine，更罕见且每幕最多 1 次 |
| `the_woman_in_blue` | The Woman in Blue | shared | Buy 1 | 支付 20 金币，得 1 瓶随机药水（可拒收） | 需至少 50 金币 |
| `the_woman_in_blue` | The Woman in Blue | shared | Buy 2 | 支付 30 金币，得 2 瓶随机药水 |  |
| `the_woman_in_blue` | The Woman in Blue | shared | Buy 3 | 支付 40 金币，得 3 瓶随机药水 |  |
| `the_woman_in_blue` | The Woman in Blue | shared | Leave | 什么都不发生 |  |

> 事件池选择算法（哪个事件被抽中）**没有任何来源给出权重表**：三个来源都只给"哪些事件属于哪一幕"。已知的只有：`Wheel of Change` 被标为 Shrine（更罕见、每幕最多 1 次），以及两个事件带 floor 门槛（Dead Adventurer、Hypnotizing Colored Mushrooms 只在 floor ≥ 7）。⇒ **这一条是本清单最大的空洞**。

---

## 9. 奖励与进度

### 9.1 战斗奖励

| 战斗类型 | 金币 | 卡牌奖励 | 遗物 | 药水 |
|---|---|---|---|---|
| 普通战斗 | 10–20 | 3 选 1（或跳过），3%/37%/60% | 无 | 40% 基准，见 9.3 |
| 精英战斗 | 25–35 | 3 选 1，10%/40%/50% | **1 个随机 Common/Uncommon/Rare 遗物** | 同上 |
| Boss 战斗 | 95–105 | 3 选 1，**100% Rare** | 无（改走 Boss 宝箱） | 同上 |
| Boss 宝箱（floor 17） | — | — | **3 个 Boss 遗物里选 1**（Ironclad Boss 池 22 件） | — |

【wiki】`Gold` / `Card Rewards` / `Elites` / `Chest`。

### 9.2 宝箱金币

| 箱型 | 出金币概率 | 金币 |
|---|---|---|
| 小箱 | 50% | 23–27 |
| 中箱 | 35% | 45–55 |
| 大箱 | 50% | 68–82 |

### 9.3 药水掉落与稀有度

| 规则 | 值 | 来源 |
|---|---|---|
| 掉率 | 基准 **40%**；掉了则下次 **−10%**，没掉则下次 **+10%**；**每幕开始时重置为 40%** | 【wiki】 |
| 稀有度 | Common **65%** / Uncommon **25%** / Rare **10%** | 【wiki】 |
| 持有限 | 3 个（`Potion Belt` +2；A11 起 −1） | 【wiki】 |
| 使用 | 不消耗能量、不算"打出一张卡" | 【wiki】 |

### 9.4 药水（Ironclad 可获取 33 瓶）

全局 42 瓶，其中 12 瓶是职业专属（每职业 3 瓶：Common/Uncommon/Rare 各 1）。Ironclad 能拿到 42 − 9 = **33** 瓶。【多源一致】

#### Common（17 瓶）

| `id` | name | effect | 归属 |
|---|---|---|---|
| `attack_potion` | Attack Potion | Choose 1 of 3 random Attack cards to add to your hand; it costs 0 this turn. | shared |
| `blessing_of_the_forge` | Blessing of the Forge | Upgrade all cards in your hand for the rest of combat. | shared |
| `block_potion` | Block Potion | Gain 12 Block. | shared |
| `blood_potion` | Blood Potion | Heal for 20% of your Max HP. | ironclad-only |
| `colorless_potion` | Colorless Potion | Choose 1 of 3 random Colorless cards to add to your hand; it costs 0 this turn. | shared |
| `dexterity_potion` | Dexterity Potion | Gain 2 Dexterity. | shared |
| `energy_potion` | Energy Potion | Gain 2 Energy. | shared |
| `explosive_potion` | Explosive Potion | Deal 10 damage to ALL enemies. | shared |
| `fear_potion` | Fear Potion | Apply 3 Vulnerable. | shared |
| `fire_potion` | Fire Potion | Deal 20 damage. | shared |
| `flex_potion` | Flex Potion | Gain 5 Strength. At the end of your turn, lose 5 Strength. | shared |
| `poison_potion` | Poison Potion | Apply 6 Poison. | shared |
| `power_potion` | Power Potion | Choose 1 of 3 random Power cards to add to your hand; it costs 0 this turn. | shared |
| `skill_potion` | Skill Potion | Choose 1 of 3 random Skill cards to add to your hand; it costs 0 this turn. | shared |
| `speed_potion` | Speed Potion | Gain 5 Dexterity. At the end of your turn, lose 5 Dexterity. | shared |
| `strength_potion` | Strength Potion | Gain 2 Strength. | shared |
| `weak_potion` | Weak Potion | Apply 3 Weak. | shared |

#### Uncommon（9 瓶）

| `id` | name | effect | 归属 |
|---|---|---|---|
| `ancient_potion` | Ancient Potion | Gain 1 Artifact. | shared |
| `distilled_chaos` | Distilled Chaos | Play the top 3 cards of your draw pile. | shared |
| `duplication_potion` | Duplication Potion | This turn, your next card is played twice. | shared |
| `elixir` | Elixir | Exhaust any number of cards in your hand. | ironclad-only |
| `essence_of_steel` | Essence of Steel | Gain 4 Plated Armor. | shared |
| `gamblers_brew` | Gambler's Brew | Discard any number of cards, then draw that many. | shared |
| `liquid_bronze` | Liquid Bronze | Gain 3 Thorns. | shared |
| `liquid_memories` | Liquid Memories | Choose a card in your discard pile and return it to your hand; it costs 0 this turn. | shared |
| `regen_potion` | Regen Potion | Gain 5 Regen. | shared |

#### Rare（7 瓶）

| `id` | name | effect | 归属 |
|---|---|---|---|
| `cultist_potion` | Cultist Potion | Gain 1 Ritual. | shared |
| `entropic_brew` | Entropic Brew | Fill all your empty potion slots with random potions. | shared |
| `fairy_in_a_bottle` | Fairy in a Bottle | When you would die, heal to 30% of your Max HP instead and discard this potion. | shared |
| `fruit_juice` | Fruit Juice | Gain 5 Max HP. | shared |
| `heart_of_iron` | Heart of Iron | Gain 6 Metallicize. | ironclad-only |
| `smoke_bomb` | Smoke Bomb | Escape from a non-boss combat. Receive no rewards. | shared |
| `snecko_oil` | Snecko Oil | Draw 5 cards. Randomize the cost of cards in your hand. | shared |

---

## 10. 关键词 / 状态（第一幕 Ironclad 内容用到的）

| 关键字 | 精确机制 | 来源 |
|---|---|---|
| Block | 到下次自己回合开始前抵挡伤害（默认回合开始清空，除非有 Barricade/Calipers） | 【wiki】 |
| Vulnerable | 受到的**攻击**伤害 +50% | 【wiki】 |
| Weak | 造成的**攻击**伤害 −25% | 【wiki】 |
| Frail | 从卡牌获得的 Block −25% | 【wiki】 |
| Strength | 每点让每次攻击伤害 +1（可负） | 【wiki】 |
| Dexterity | 每点让卡牌获得的 Block +1（可负） | 【wiki】 |
| Exhaust | 打出后本场战斗移除 | 【wiki】 |
| Ethereal | 回合结束还在手里则 Exhaust | 【wiki】 |
| Innate | 开局必定在起手牌里 | 【wiki】 |
| Retain | 回合结束不弃掉 | 【wiki】 |
| Ritual | 自己回合结束时 +X Strength | 【wiki】 |
| Curl Up | 第一次受到攻击伤害时获得 X Block（多段攻击全部结算后触发一次） | 【wiki】 |
| Spore Cloud | 死亡时给玩家 X Vulnerable | 【wiki】 |
| Thievery | 每次攻击偷 X 金币；被击杀则全数归还 | 【wiki】 |
| Entangled | 本回合不能打出 Attack | 【wiki】 |
| Angry | 每次受到攻击伤害 +X Strength | 【wiki】 |
| Enrage | 玩家每打出一张 Skill，自己 +X Strength | 【wiki】 |
| Artifact | 抵消接下来 X 次 debuff | 【wiki】 |
| Metallicize | 自己回合结束获得 X Block（Lagavulin 的"回合开始"版本只在 Asleep 态出现） | 【wiki】 |
| Sharp Hide | 玩家每**打出**一张 Attack 就受 X 伤害（可被 Block 抵挡；多段卡只触发一次） | 【wiki】 |
| Mode Shift | The Guardian 的阶段计数：受 1 点 HP 伤害减 1，归零切防御态 | 【wiki】 |
| Split | HP ≤ 50% 时分裂成两只小史莱姆，HP = 分裂瞬间当前 HP | 【wiki】 |
| Slimed | 状态卡：不可打出（费用 1，无效果），回合结束留在手里；战斗结束移除 | 【游戏文件】 |
| Dazed | 状态卡：不可打出，Ethereal | 【游戏文件】 |
| Wound | 状态卡：不可打出 | 【游戏文件】 |
| Burn / Burn+ | 状态卡：不可打出，回合结束在手里时受 2 / 4 伤害 | 【wiki】 |
| Poison | 回合开始失去等量 HP 然后层数 −1（**Ironclad 与第一幕敌人都不产生**，列在此仅为排除） | 【wiki】 |

---

## 11. 边界：进阶（Ascension）不在 v1 范围

**本清单所有数值都是 A0（无进阶）。**Ascension 1–20 会改动敌人 HP/伤害/行动组合、精英出现权重（A1：8% → 16%，普通战斗 53% → 45%）、卡牌奖励升级概率（A12 减半）、商店价格（A16 +10%）、事件好坏分支（A15）、起始状态（A6 带伤、A10 带诅咒、A14 降最大 HP）等，**全部不在 v1 范围内**，也不应进入本里程碑的验收口径。

各实体在进阶下的具体数值**已经存在于来源 A 的数据里**（`monsters.json` 的 `*_ascension` 字段、wiki 的 `{{Asc|N+|…}}` 记法），搬运时不要把它们混进 A0 基线。

---

## 12. 未决项 / 单源 / 推断（搬运前必须补的洞）

| # | 项 | 状态 | 影响 |
|---|---|---|---|
| 1 | **事件抽取权重**（26 个事件里抽中哪个、Shrine 权重、去重规则） | 三个来源都没给 ⇒ 【推断】 | 事件节点无法做得像原作，只能先等概率 |
| 2 | **敌人 AI 的 RNG 细节**（"不能连用 N 次"在边界上的实际回退方式、以及相同权重下如何取整） | 【wiki】给了权重与限制，但没给实现的取整/回退 | 可能出现"权重对但分布不同" |
| 3 | **Gremlin Wizard HP** | 游戏文件 21–25 vs wiki 23–25，冲突 ⇒ 采信 21–25【游戏文件】 | 需实机核对 |
| 4 | **Boss / 精英 / 遭遇的内部权重**（是否真的等概率） | 【推断】wiki 只说"三选一"、"随机" | 可能不是 1/3 |
| 5 | **Searing Blow 的逐级升级值** | wiki 只给首级 12(16)；后续每级 +4、+5、+6… 递增 ⇒ 【单源】 | 需要单独建模多级升级 |
| 6 | **Curse 卡清单**（Regret / Injury / Doubt / Parasite / Pain / Decay 等的精确机制） | 本文件只在事件分支里点名，未展开 | 事件效果无法结算 |
| 7 | **Wheel of Change 6 格是否真等概率** | 【推断】 | 影响金币/诅咒分布 |
| 8 | **事件池是否"每幕最多 1 次 Shrine"之外还有每局去重** | 【单源】（Wheel of Change 页提到 Shrine 属性） | 可能重复遇到同一事件 |

---

## 13. 复现方式（这份清单怎么来的）

```text
# 1) 拉 STS1 数据转储（直接从游戏 JAR 解析）
https://raw.githubusercontent.com/nkhoit/spire-archive/main/data/sts1/<name>.json
#    cards / monsters / relics / relic_values / potions / characters / events / powers / keywords

# 2) 拉 wiki 原文（MediaWiki parse API，返回 wikitext）
https://slay-the-spire.fandom.com/api.php?action=parse&page=<PAGE>&prop=wikitext&format=json&formatversion=2

# 3) 版本锚点
https://slaythespire.wiki.gg/wiki/Patch_Notes   # V2.3.4 - Hotfix 是 PC 公开版最后一条
```

本文档的**卡牌表**由 `Ironclad_Cards` 页的 `基础(升级后)` 记法与 `cards.json` 的`damage`/`block`/`magic_number`/`upgrade` 双源生成；**敌人 HP 与伤害**取 `monsters.json`，**行动集合/AI/上状态层数**取各自 wiki 页；**遗物/药水效果**取 `relics.json`/`potions.json` 的描述字段（已修掉 3 处占位符残缺，见 §0 瑕疵 5 之外的三条：Happy Flower / Nunchaku / Sundial 的缺失数字）。
