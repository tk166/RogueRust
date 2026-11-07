"""§280 文档：port-plan 新一节 + 缺口文档交叉引用 + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §280 事件条件补全：`RequiresAsc` + 三个新原子 + 两条真事件

§279 把条件做成了机制，但只被 `forgotten_altar` 用了一次。这一节是**扫描 + 补全**：
先按 wiki 逐条核对真事件的 `Requires:` 行（结果写进 **`docs/event-gaps.md`**），再把能用
现有机制表达的全部补上。

### 280.1 扫描结论（`docs/event-gaps.md`）

* 真事件里带 `Requires:` 的有 **9 条**，其中 **4 条**是**选项级**（能给按钮判定）、
  **4 条**是**事件级**（"这个事件本身出不出现"，我们还没有载体）、1 条两者都有。
* 选项级那 4 条现在补了 **3 条**（`the_cleric`×2 选项、`the_moai_head`×1 选项，
  加上已有的 `forgotten_altar`）。剩下 1 条（`vampires`）被**两张牌**挡住：
  "移除所有 Strike"（`remove_all`）与"得到 5 张 Bite"（`card:<id>`×N + Bite 这张牌本身）。
* 事件级那 4 条（`the_cleric` 要 ≥35 金币、`the_moai_head` 要"有金像或 HP ≤ 50%"、
  `the_joust` 要 >50 金币、`tomb_of_lord_red_mask` 要红面具）**故意没做** —— 理由写在
  §280.5，因为它会重掷每一次 `?` 房的抽取。

### 280.2 `RequiresAsc`：条件也有 A15 变体

`The Cleric` 的 `Purify` 在 A15 是 **75** 金币（A0-14 是 50）。只写一条 `gold at_least 50`
会让"50..74 金币 + A15"看到一个点下去被拒的按钮；只写 75 又会让低难度下付得起的人看不到。
所以条件与效果**成对**：

```
"Requires":    [ {"Kind":"gold","Op":"at_least","Amount":50} ]
"RequiresAsc": [ {"Kind":"gold","Op":"at_least","Amount":75} ]
"Effects":     [ gold_cost:50, remove_card ]
"EffectsAsc":  [ gold_cost:75, remove_card ]
```

语义与 `EffectsAsc` 相同：A15 起**取代**基础那一串。内容门钉三条：非空、必须与基础不同、
逐条走**同一个** `check_requirement_atom`（两条清单共用一份实现，因为"两份清单一定会漂"）。

★ `rd-core::run_expr::A15 = 15` 是 `rd_run::state::A_EVENTS_WORSE` 的第二份（`rd-core`
不能依赖 `rd-run`）。漂开会让"价目"与"条件"分家，所以 `rd-wasm` 有一条判据钉住两者相等。

### 280.3 三个新原子

| content says | means |
|---|---|
| `gold_cost:<n>` | **付** `n` 金币；付不起 ⇒ `RunError::NotEnoughGold`（**不是**扣到 0） |
| `heal_pct:<n>` | 回复 `floor(max HP × n / 100)` |
| `heal_full` | 回满（回到**当前上限**，不是回 999） |

★ `gold_cost` 存在的理由是 `adjust_gold` 的行为：它把 `(gold + delta).max(0)` 写回去，
所以 `gold: -75` 在只有 50 金币时会把金币夹成 0 —— 玩家**白拿了服务**，而屏幕上一切正常。
判据 `paying_more_gold_than_you_have_is_refused_not_clamped` 钉的是"整份局面不动一个字节"。

### 280.4 百分比改成**千分**（12.5%）

`The Moai Head` 的 `[Jump Inside]` 是"失去最大 HP 的 **12.5%**"（A15 18%）。整数百分比
表达不了它，而"取整到 12%"是**另一个规则**，不是同一个规则的近似。所以：

* 内容仍然写人话：`max_hp_pct:12.5`；
* 内部单位改成**千分**（`125` = 12.5%），`percent_of` 改名 `permille_of`（留着旧名字而语义
  变成千分，是那种"看着对、算出来差十倍"的错）；
* 解析 `parse_permille` 只接受 1..=100、**可选一位小数**、无符号；`12.` / `12.55` / `100.5`
  都是词表外（它们表达同一件事的不同拼法，两套拼法迟早有一处被忘掉）。
* ABI 的 amount 因此返回千分（`250`），页面用 `permilleText` 显示 `25%` / `12.5%`。

⚠️ 这一改把 §278/§279 的判据与 `a15_swaps_...` 的断言一起搬到了千分（`350` / `100`）。

### 280.5 事件级条件**没做**（这是有意的）

`the_cleric` / `the_moai_head` / `the_joust` / `tomb_of_lord_red_mask` 的 wiki 原文都有
"**can only be encountered if …**"。那是**池子过滤**，不是选项过滤。补它要：
`EV` 加一格 `Requires`（与选项**同一个**求值器）+ "抽中的事件全都不可选"时的退路
（我们还没有"退回一场普通战斗"这条路径）。而它叠在 §272 的 `?` 房分流**同一个掷骰**上 ——
在那层加过滤会改变每一次 `?` 房的抽取，所有跑法的覆盖整片重掷。所以它单独排期，
写进 `docs/event-gaps.md` §3.1。

### 280.6 内容：两条事件 + 两条幕数修正

```
the_cleric (Act 1)      [Heal (35 Gold)]    Requires gold≥35        gold_cost:35 + heal_pct:25
                        [Purify (50 Gold)]  Requirements gold≥50/75  gold_cost:50/75 + remove_card
                        [Leave]
                        → 三个后续屏（各一个 `[Leave]`）

the_moai_head (Act 3)   [Jump Inside]       heal_full 然后 max_hp_pct:12.5 / A15 18
                        [Offer: Golden Idol] Requires relic has golden_idol
                                            relic_lose:golden_idol + gold:333
                        [Leave]
                        → 三个后续屏
```

⚠️ `Jump Inside` 的**顺序**是 wiki 的：先回满血，再失去上限（反过来的话上限先掉，回血就少回）。
顺手修正两条幕数错位：`the_ssssserpent` 是 Act 1（原来在 Act 3 池）、`forgotten_altar` 是 Act 2
（原来在 Act 1 池）。

### 280.7 ★ 三个 walker 里同一个洞

`web/map_test.mjs`、`rd-wasm` 的 `settle_here` 与 `walk_calm_nodes` 都在**盲选槽 0**。事件
一旦有锁着的选项，盲选就点空：内核拒（-2）→ 屏幕没变 → 下一格报"step refused / walk 失败"，
**指到地图**而不是指到这一行。§279 修了第一个，这一节在 `rd-wasm` 里发现**另外两个**
（`an_elite_node_fights_the_sentries_and_pays_the_elite_tier` 就是这么红的）。

修法不是各修一遍，而是**一个**助手 `settle_event()`（挑第一个可用选项 + 多段一路点到收尾），
两处都调它。这与 §277 的教训同形：**同一件事被抄三份，改一份不够**。

### 280.8 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `paying_more_gold_than_you_have_is_refused_not_clamped` | 付不起 ⇒ `NotEnoughGold` 且**整份局面不动**；付得起 ⇒ 金币真的少了 35、血真的回了 25% |
| `heal_full_reaches_the_current_maximum` | 回到**当前上限** |
| `a_fractional_percentage_reaches_the_arithmetic` | 80 上限的 12.5% **恰好**是 10；`12.5`/`12` 是两个不同的数；`12.55`/`12.`/`100.5`/`0` 全拒 |
| `the_a15_requirement_variant_gates_the_cleric_price` | 同一个 60 金币的局：A0/A14 可选、**A15/A20 不可选**；A15 + 80 金币又可选。★ 两侧 |
| `the_a15_requirement_variant_...` 的首行 | `rd_core::run_expr::A15 == rd_run::state::A_EVENTS_WORSE` |
| 内容门 `[6c]` | `RequiresAsc` 非空/必须与基础不同/逐条同词表；`gold_cost` 正整数；百分比一位小数 |
| `the_unknown_room_events_are_readable` | 13 个事件、走遍每一段、词表（含新原子） |

**负控**（`native/p280_negative.py`）：① `RequiresAsc` 与基础**一模一样**；
② `max_hp_pct:12.55`（两位小数）；③ `gold_cost:0`；④ **删掉 `RequiresAsc`** ⇒
`the_a15_requirement_variant_gates_the_cleric_price` 必须红 —— 四条全 RED ✓
（第 ④ 条是唯一能证明"那一条 A15 判据真的在判 A15"的）。

### 280.9 账

事件 **11 → 13**（`the_cleric` 4 段、`the_moai_head` 4 段）；段 **17 → 25**；选项 **32 → 44**
（**4 条条件**、5 个原子）；效果 **53 → 73**（21 条在 A15 列表里）。
镜像 **152,588 B**（core 118,904 B）；`rd-core` 795 / `rd-run` **152** / `rd-wasm` **125**；
8/8 tables 16 checks；`STS_CONTENT PASS`；七道页面门全过；`COVERAGE_MATRIX` 805 行；21/21。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    old = '''| ~~真实事件的**剧情分支**被合并 + 条件选项~~ | **§278/§279 已做**：`EVND` 段表（选项数不固定）+ `EV.Entry` + `Requires`（闭词表，6 数值 kind / 2 存在 kind）+ `relic_lose`；`golden_idol` 补成两段三选一，`forgotten_altar` 补成 4 选项（1 条条件）+ 3 个后续屏。 |'''
    new = '''| ~~真实事件的**剧情分支**被合并 + 条件选项~~ | **§278/§279/§280 已做**：`EVND` 段表（选项数不固定）+ `EV.Entry` + `Requires`/`RequiresAsc`（闭词表，6 数值 kind / 2 存在 kind）+ `relic_lose` / `gold_cost` / `heal_pct` / `heal_full` / 小数百分比（千分）。**事件级条件（"这个事件出不出现"）仍未做** —— 见 `docs/event-gaps.md` §3.1。 |'''
    assert g.count(old) == 1
    g = g.replace(old, new)
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§279）', '（主计划 §1–§280）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§280 doc + gap row + README')


main()
