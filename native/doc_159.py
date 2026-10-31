"""Append §159 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 159. Ascension 框架 + 开局前的种子设定

wiki 的 `Ascension` 页有 **20 条**修饰，**累计生效**（A3 同时带着 A1 和 A2）。这一节把框架立起来，
并实现了其中 **9 条**；没实现的 11 条在 §159.6 逐条写了"要什么"，因为"支持到 A20"而其中八条
静默不生效，正是这个项目一直在抓的那种谎。

### 159.1 一个数，一条规则一个号

`RunState.ascension: u8`（`0..=20`，超出**夹取不拒绝**：页面一个 off-by-one 不该变成死按钮），
以及 **唯一的比较** `at_least(level)`。规则号是常量：

`A_BOSS_HEAL`=5、`A_START_DAMAGED`=6、`A_NORMAL_HP`=7、`A_ELITE_HP`=8、`A_BOSS_HP`=9、
`A_POTION_SLOT`=11、`A_BOSS_GOLD`=13、`A_MAX_HP`=14、`A_SHOP_PRICE`=16。

调用点于是读作"这条规则"，而不是散落一地的 `>= 5`。**累计是断言的形状**：每条规则都在自己阈值的
两侧各测一次（`a_boss_heals_…` 测 A4 与 A5、`the_ascension_rules_…` 测 A13 与 A14/A15 与 A16），
因为"`>=` 写早了一级"正是这种代码最容易犯且最不容易看出来的错。

### 159.2 两条**改初始状态**的规则，顺序是规则的一部分

`A14` 减最大生命（铁甲战士 **−5**，内容里只有这一个角色），`A6` 掉 10% 生命。
顺序决定数字：**先 A14 再 A6** ⇒ 80 → 75 → 68；反过来是 80 → 72 → 67。

它们**不在同一个函数里**，这是有意的：`A14` 改的是最大值，属于构造（`new_with_ascension`）；
`A6` 要作用在**内容声明的 `StartingHealth`** 之上，而那个数字只有调用方（`rd-wasm` 的
`rd_run_start`）知道。若两条都写在构造函数里，`rd_run_start` 里那句
`adjust_health(starting_health - health)` 会把 A6 的伤害**覆盖掉**，而覆盖与否取决于两行的先后 ——
那是最糟的一类耦合。

### 159.3 Boss 战之后**本来就没有回血**

`A5` 的 wiki 原文是 "heal 75% of missing health **instead of 100%**"。查下去才发现**那条 100%
压根不存在**：`mark_boss_beaten` 只换幕、不回血。所以这一节先把基础规则补上（打完一幕的 Boss
回满），`A5` 才有意义。一个"关于不存在的治疗的分数"是这次差点写出来的东西。

### 159.4 `A7`/`A8`/`A9` 的百分比是**我们的模型**，不是 StS 的数据

wiki 只说 "have more HP"，真游戏是逐怪的**手调数字**。所以 `+10%` 落在**一个常量**
（`ASCENDED_ENEMY_HEALTH_PERCENT`）上，注释写明它没有出处，以及哪天 `ENCT` 长出 ascension 列，
这是唯一要删的东西。它不是"猜"，它是"标了价的近似"。

落在 `ENCT` 行的 `MaxHealth` 上（唯一写着敌人血量的地方），由
`build_session_at(…, enemy_health_percent)` 应用 —— `build_session_with` 变成它的 `0` 便利入口。

### 159.5 开局前的种子：`(seed, level)` 才是一局

页面此前 `runSeed = Math.floor(Math.random()*2e9)`，**种子不可输入**，等级不存在。现在地图面板上方
两格：**种子** + **爬塔等级**，加一个"开始 / 重开"按钮；顶栏在等级 > 0 时显示 `A<n>`。

三条纪律写进了实现：

* `#seedInput` 只有**一个写者** `setSeed()` —— 一个和实际开局不一致的种子输入框，比没有输入框更糟；
* `startRun()` **读**这两格再调 `rd_run_start(seed, level)`，并把夹取后的值写回去（页面显示的就是
  内核真收到的）；
* 顶栏里的等级从 `rd_run_ascension()` 读，**不**从输入框读 —— 输入框描述的是"下一局"。

`rd_run_start` 的签名因此从 `(seed)` 变成 `(seed, ascension)`：`web/index.html`、`web/map.html`、
`map_test.mjs` 的 5 处调用一起改。⚠️ 少改一处**不会**报错（wasm 缺参数会当 0），所以这一节还让
`browser_test` **从输入框驱动**一遍：填种子 2222、等级 14、点按钮，然后断言内核的等级是 14、
种子是 2222、最大生命是 75、顶栏里有 `A14`。

⚠️ 这个场景自己踩了两次**反引号/转义**：`browser_test` 的整段注入代码是一个模板字符串，
注释里一个 `` ` `` 就直接把它截断（`SyntaxError`），注释里一个 `\\n` 会变成真换行、把下一行变成代码。
FACT.md §2 记的就是这个坑，这次它换了个位置复发。

### 159.6 没实现的 11 条，各自要什么

| 规则 | 要什么 |
|---|---|
| A1 精英更常见 | 地图的 `kind_for_roll` 是**累计上界表**（53/8/12/5/22），要按等级换一张并把差额从 Combat 里扣。**下一节和精英池一起做**（改表要连 12 条地图测试）|
| A2 / A3 / A4 敌人/精英/Boss 伤害更高 | 内容每条 `EACT` 只有**一个**伤害数字，没有 ascension 列。要么给 `EACT` 加列（格式 v5），要么写成"开局给敌人力量"——后者是**换机制**，会改变多段攻击的缩放，不打算偷偷做 |
| A10 开局带 Ascender's Bane | 一条 Curse 卡行 + "不可移除"（`remove_card` 要拒）。卡行好加，"不可移除"是新规则 |
| A12 强化牌更少出现 | 我们的**奖励里根本不出现强化牌**，所以 A12 是在给一个不存在的基数打折：要么先做基数（奖励按概率给 `+` 版），要么留空 |
| A15 事件更不利 | 每个事件要有 A15 分支（内容 + 运行层）|
| A17 / A18 / A19 更强的招式 | 每只怪要有 ascension 招式表（内容 + `intent`）|
| A20 双 Boss | 打完第一只再打另一只；`Boss3` 目前只有 `enc_time_eater` 一个，需要先有第二只 |

### 159.7 判据

* `the_ascension_rules_are_each_their_own_level`（rd-run）：A13 不动最大生命、A14 才动；
  A11 的格子 3 → 2 且腰带仍在**基数**上 +2（⇒ 4，正是 wiki 的"5，或 A11 以上的 4"）；
  A15 不打折、A16 打；A99 夹到 20。
* `a_boss_heals_to_full_and_ascension_five_heals_three_quarters`：A0 回满、A4 仍回满、A5 回 75%。
* `the_enemy_health_bonus_belongs_to_its_own_fight_kind`：A7 只动普通、A8 动精英、A9 动 Boss。
* `the_ascension_level_reaches_the_run`（rd-wasm）：A0 = 80/80、A6 = 80/72、A14 = 75/68、
  A20 = 75/68（A6 与 A14 是唯一两条改初始状态的规则），99 夹到 20，且同一个种子仍然给出同一局。
* `ascension_seven_makes_a_normal_fight_tougher`：同种子同一场战斗，敌人最大生命正好 +10%。
* `browser_test`：**从输入框**驱动 A14，断言等级/种子/最大生命/顶栏四处。

### 159.8 数字

聚合验收 **18/18**；单测 752 → **757**（rd-core 631、rd-run 77 → **80**、rd-wasm 44 → **46**）。
内容未动（31 怪 / 22 遭遇 / 30 卡 / 24 状态 / 13 遗物 / 20 药水），镜像字节不变。
"""

with io.open(PATH, "rb") as handle:
    raw = handle.read()
assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
text = raw.decode("utf-8")
assert "## 159." not in text, "already appended"
if not text.endswith("\n"):
    text += "\n"
text += SECTION
with io.open(PATH, "wb") as handle:
    handle.write(text.encode("utf-8"))
print("port-plan.md now", len(text.split("\n")), "lines")
