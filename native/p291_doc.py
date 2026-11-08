"""§291 文档：审计 + `MinGold` + G1，并把 F.5/F.6/F.7 的旧行改成"已修（§X）"。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §291 F.5 的审计：三条偏差其实早修了，一条**卡死**是真的

用户让我"分析 F.5 的那几条偏差"。逐条对**代码与内容**查（不看旧表）：

| F.5 的行 | 现状（证据） | 谁修的 |
|---|---|---|
| 奖赏/赔付时机（结果屏 `[Leave]` 上兑，多一次点击） | `scrap_pile.found` / `the_joust.*_won` 的 `Effects` 挂在**段**上，`[Leave]` 是空效果 | §286 段的进入效果 |
| `Wing Statue` `[Destroy]` 总是出现 | `Requires: card_damage at_least 10`；起始牌组（单次最高 8）下按钮**不画** | §287 |
| `Dead Adventurer` 伏击"没有载体" | `Fight: "elite"` + `Encounter: "EliteEvent"` + 战后欠账 | §286 / §287 |
| `Scrap Ooze` 的遗物稀有度 | `relic_random` → `pick_relic`（50/33/17、排除已持有） | 一直一致 |

⇒ **文档腐烂**：每一节都新加一张表，却没人回头改旧表那一行。两张表互相矛盾时，读者只信他
先看到的那张 —— 这正是"同一份常量抄第二份就是腐烂的开始"的另一种形态（**同一件事有两份
结论**）。这一节把三张旧表的相关行都改成"已修（§X）"。

### 291.1 审计时发现的**真**问题：`The Joust` 会卡死

wiki："This event can only be encountered with **more than 50 Gold**." 而我们的内容：

* `the_joust.offer` 的两个选项都是 `gold_cost:50`，**没有 `Requires`** ⇒ 付不起时按钮
  **照样画**，点下去内核 `-2`（`NotEnoughGold`），屏幕不变；
* 这个事件**没有 `[Leave]`**（wiki 也是 "no option to avoid betting"）⇒
  **零可用按钮 = 玩家卡死，节点永远结算不了**。

两处修，**必须一起**：

1. **`MinGold` 事件池门槛**（与 `MinFloor` / `MaxFloor` 同一族的"先筛后掷"）：
   `the_joust` 的池条目加 `MinGold: 51` —— 金币 ≤ 50 时这个事件**不出现**，正好是 wiki 那句。
   只加 `Requires` 不行：金币 ≤ 50 时进来就是"零按钮"（换个方式卡死）。
2. **内容门 G1："付不起就别画"** —— 任何带 `gold_cost:<n>` 的选项**必须**带
   `Requires: gold at_least n`。只加 `MinGold` 也不行：有人绕过池子（`RD_DEBUG.startAnEvent`、
   存档）时仍会画出死按钮。

G1 立刻抓到第二处**潜在**问题：`The Cleric` 的 Purify 在 A15 是 **75** 金币 —— 但它的
`RequiresAsc` 也写了 75，**内容是对的**。所以第一版 G1 判据写错了配对（拿 A15 的价去对
基础的 `Requires`），改成**同版本配对**（`Effects` ↔ `Requires`，`EffectsAsc` ↔ `RequiresAsc`，
后者缺席才退回基础）—— 那正是 `effects_at` 本来就有的语义：`Asc` **取代**基础，不是叠加。

### 291.2 ★ 负控被骗了一次：门的**崩溃**看起来像"抓住了"

第一版 G1 在"两个 `Requirements` 都缺席"时 `any(None)` 崩掉：退出码非 0、但没有那句话。
负控脚本按"退出码 + 消息"判红，于是把崩溃读成了"门抓到了"——**它其实什么都没判**。

修两处：
* 门里 `option.get(...) or []`（缺席是空列表，不是 `None`）；
* 负控**多一条反证**（③）：把 G1 关掉、喂同一份坏内容，必须变**绿** —— 只有这样才能证明
  "红是 G1 抓的"，而不是别处崩的。

同一轮里负控的**恢复**也骗过一次：它从 `git HEAD` 恢复再"重打一遍补丁"，而 `HEAD` 落后于
工作树 ⇒ 恢复出来是坏的（下一轮的 `STS_CONTENT` 直接红）。改成**开始时拷一份原样内容**，
恢复就是把那份拷回来 —— 恢复里不许再有第二份"内容该怎么写"的合同。

### 291.3 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `the_unknown_room_events_are_readable`（core，§291 段） | `MinGold` 两侧：50 金币 ⇒ `the_joust` **不出现**；51 ⇒ 出现。押注项**可用性两侧**：50 金币可选、49 金币**不画** |
| 内容门 | `MinGold` 是 1..=999；**G1**：`gold_cost:<n>` ⇒ 同版本 `Requires: gold at_least n` |
| 负控 ① | 内核忽略 `MinGold` ⇒ 判据红 |
| 负控 ② | 删掉押注项的 `Requires` ⇒ 门 G1 红（两条，逐项报） |
| 负控 ③ | **关掉 G1** 喂同一份坏内容 ⇒ 必须**绿**（证明红是 G1 抓的） |

### 291.4 账

镜像 **162,192 B**（core 128,160 B）；`rd-core` 797 / `rd-run` 166 / `rd-wasm` 136；
八道页面门 + `SOAK`；21/21。

### 291.5 还没做的

* 一条**结构性**的假设：某一段的**所有**选项都带 `Requires` 时，"零按钮"取决于局面 ——
  这在内容里不可静态验证，只能靠"池子门槛把会失败的局面挡在外面"（`MinGold` 就是这样）。
  今天的审计脚本（A 段）能列出"带 `gold_cost` 却没条件"的选项，B 段能列出"整段都带条件"的
  步骤；后者今天**一个都没有**。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()

    # ── F.5：三条已修 + 一条一致
    old_f5 = '''| 奖赏/赔付的时机 | 到达结果屏就生效 | 结果屏 `[Leave]` 上兑（多一次点击） | **偏差**：效果挂在选项上，"进入某段时执行"还没做 |
| `Wing Statue` `[Destroy]` | 只在牌组有"单次 ≥10 伤害的攻击牌"时出现 | **总是**出现 | **偏差**：条件词表问不了"某张牌打多少" |
| `Scrap Ooze` 的遗物 | 50/33/17 稀有度、随机 | 同（`pick_relic`），并排除已持有 | 一致 |
| `Dead Adventurer` | 25%/35% 精英归来（事件中途开战斗） | **没做** | 缺：事件里开战斗没有载体 |'''
    new_f5 = '''| 奖赏/赔付的时机 | 到达结果屏就生效 | **已修**：段的进入效果（`Effects` 挂在 `EVND` 行上） | 一致（§286） |
| `Wing Statue` `[Destroy]` | 只在牌组有"单次 ≥10 伤害的攻击牌"时出现 | **已修**：`Requires: card_damage at_least 10`（从效果程序读） | 一致（§287） |
| `Scrap Ooze` 的遗物 | 50/33/17 稀有度、随机 | 同（`pick_relic`），并排除已持有 | 一致 |
| `Dead Adventurer` | 25%/35% 精英归来（事件中途开战斗） | **已修**：`Fight` + `Encounter` + 战后欠账 | 一致（§286 / §287） |
| `The Joust` 的**出现条件** | 只有 **>50 金币**时才遇到（且没有"不赌"的选项） | **已修**：`MinGold: 51` + 押注项 `Requires: gold at_least 50` | 一致（§291；此前会**卡死**） |'''
    assert g.count(old_f5) == 1
    g = g.replace(old_f5, new_f5)

    # ── F.6：三条已修
    old_f6 = '''| `Dead Adventurer` 战后补偿 | 战斗胜利补发"还没搜到"的奖励，另加 25-35 金币 | **不补**（奖励流程 `roll_reward(kind)` 不知道差额） | **偏差**：缺"把奖励差额带进战斗结算"的通道 |
| `Dead Adventurer` 的 Lagavulin | 这场伏击**不睡觉**，开局直接 Siphon Soul | 睡眠是遭遇的静态属性，没按"这次不睡"覆盖 | **偏差**：`ENCT` 没有这一列 |
| `Dead Adventurer` 的出现楼层 | 只出现在第 7 层之后 | 事件池无按楼层筛 | 缺：`EV` 没有楼层门槛 |'''
    new_f6 = '''| `Dead Adventurer` 战后补偿 | 战斗胜利补发"还没搜到"的奖励，另加 25-35 金币 | **已修**：`fight_gold_bonus` / `fight_no_relic` | 一致（§287） |
| `Dead Adventurer` 的 Lagavulin | 这场伏击**不睡觉**，开局直接 Siphon Soul | **已修**：事件自己的池 `EliteEvent` + `enc_lagavulin_awake` | 一致（§287） |
| `Dead Adventurer` 的出现楼层 | 只出现在第 7 层之后 | **已修**：`MinFloor: 7` | 一致（§288） |'''
    assert g.count(old_f6) == 1
    g = g.replace(old_f6, new_f6)

    # ── F.7 最后一行
    old_f7 = '''| `Dead Adventurer` 的出现楼层 | 第 7 层之后 | 事件池无按楼层筛 | 缺 |'''
    new_f7 = '''| `Dead Adventurer` 的出现楼层 | 第 7 层之后 | **已修**：`MinFloor: 7`（§288），§291 又把上界与金币门槛补齐 | 一致 |'''
    assert g.count(old_f7) == 1
    g = g.replace(old_f7, new_f7)

    # ── 新增 F.11：审计与 G1
    marker = '### G. ★ 基础值偏差'
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.11 F.5 的审计与"付不起就别画"（§291）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `The Joust` 的出现条件 | 只有 >50 金币时遇到 | **已修**（`MinGold: 51`） | 一致 |
| `The Joust` 押注项的可用性 | 付不起就不该有这条路 | **已修**（`Requires: gold at_least 50` + 门 G1 强制） | 一致 |
| 某段**全部**选项都带条件 | （StS 用"事件根本不会出现"来避免） | 不可静态验证；今天内容里没有这种段（审计脚本 B 段） | 结构性假设 |

### G. ★ 基础值偏差''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§290）', '（主计划 §1–§291）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§291 doc + F.5/F.6/F.7 rows updated')


main()
