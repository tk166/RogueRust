"""§285 文档：port-plan + 缺口表（偏差与已做）+ event-gaps 更新 + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
EVENTS = 'D:/Vibe/sts-tui/docs/event-gaps.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §285 事件**概率**：`Chance`/`NextFail` + 区间金币，四个真事件

§277 的分析文档把"事件概率"列为**运行层**的随机（与战斗随机是两条流）。这一节把它做进
`EVND` 的选项，并补上 Act 1 的三个事件 + Act 2 的 `The Joust`。

### 285.1 两套原语（就这两个）

```
选项：{ Label, Effects, Chance: 70, Next: "<成功去的段>", NextFail: "<失败去的段>" }
效果：gold_random:20:50     （负区间 = 扣钱： -20:-50）
      relic_random          （随机一件遗物；抽签走 pick_relic 的稀有度权重）
```

* **掷骰在运行层**：`resolve_event_effects(... , roll: Option<EventRoll>)` 用
  `RunStream::Event` 掷一次，`< chance` 走成功边。掷骰在**写任何东西之前** —— 与
  `roll_unknown_room` 同一条纪律，所以 `Err` 时局面一个字节不动。
* `Chance` 与 `NextFail` **必须成对**（内容门 + 内核两步都查）：一条有概率却没有失败边的
  选项是内容错误；一条有失败边却没有概率的也一样。
* **没有 `Chance` 就不掷**：那是"一定成功"，**不消耗**随机流（Scrap Ooze 的第 9 段是
  wiki 的 105%，写成"没有 Chance"而不是 `Chance: 100` —— 前者不掷，后者掷一次再必然成功，
  两者对同一颗种子的后续抽取不同）。

### 285.2 内容：四个事件

| 事件 | 幕 | 机制用在哪 |
|---|---|---|
| `scrap_pile`（Scrap Ooze） | 1 | **9 段链**：每段 `damage 3..11`（A15 5..13）+ `Chance 25..95`，第 9 段必然成功；成功段的 `[Leave]` 带 `relic_random` |
| `world_of_goop` | 1 | `[Gather Gold]` 得 75、掉 11；`[Leave It]` `gold_random:-20:-50`（A15 `-35:-75`） |
| `wing_statue` | 1 | `[Pray]` 删牌 + 掉 7；`[Destroy]` `gold_random:50:80` |
| `the_joust` | 2 | 入口一个 `[Continue]`（过场屏）→ 两个押注项：`gold_cost:50` + `Chance 70/30` → 四个结果屏 |

★ **升级用段链，不用"事件计数器"**：wiki 的 Scrap Ooze 就是一张 9 行的表。加一个"事件内
计数器"是**新状态**（要进指纹、进存档、还要一条"什么时候清零"的规则），而段链不需要 ——
树本来就是干这个的（§278）。判据钉的是**每一段的代价与概率都递进**
（`[3,4,..,11]` 与 `[25,35,..,95]`），只验"有 9 段"是不够的：把同一段复制 9 次也满足它。

### 285.3 三个"判据帮我改对"的地方

1. **入口段"至少两个选项"**：`The Joust` 的第一屏只有一个 `[Continue]`。§279 定的规则
   （入口 ≥2）对它是错的 —— 放宽成 **≥1**（0 才是错误：那样房间没有按钮）。
   ⚠️ 这条同时改了**内核测试**与**内容门**两处，两边都写清了理由。
2. **孤儿段**：可达性只沿 `Next` 走，于是 Scrap Ooze 的 `try2..try9` 全被判成孤儿。
   `NextFail` 是**第二条边**，必须一起走（内核测试与内容门各一处）。
3. **负区间**：`gold_random:-20:-50` 一开始被内容门判成"区间倒置" —— 负区间的读法是
   "先小后大"的绝对值，所以比较要按 `abs()`，并且**不许跨零**（跨零的区间会让"得"和"失"
   混在一起，那不是一条规则）。

### 285.4 已知偏差

* **奖励/赔付在结果屏的 `[Leave]` 上兑**（`relic_random` / `gold:100` / `gold:250`）：
  效果挂在**选项**上，而"赢了没有"由掷骰决定去哪个屏 ⇒ 赢屏的 Leave 才给钱。比原作多一次
  点击；机制上不需要新东西（"进入某段时执行效果"是另一套，见 285.5）。
* **`Wing Statue` 的 `[Destroy]` 总是出现**：wiki 要求"牌组里有一张单次 ≥10 伤害的攻击牌"，
  而条件词表只能问"有没有这张牌"（问不了"某张牌打多少"）⇒ 记偏差。
* **`Scrap Ooze` 的遗物稀有度**：走 `pick_relic` 的 50/33/17（wiki 的 Relic Distribution），
  **排除已持有**（参考也排除）。

### 285.5 还没做的

* **"进入某段时执行效果"**（`EVND` 行的 `Effects`）：有了它，奖励就能在**到达**结果屏时兑，
  而不是在它的 Leave 上。这是 §285 明确留下的下一步（改动很小：`event_step` 多读一格 +
  `resolve_event_effects` 在推进后应用）。
* `Dead Adventurer`：它的"25%/35% 精英归来"要**事件中途开一场战斗**，我们没有那条路。
* `Wing Statue` 的牌组条件（见 285.4）。

### 285.6 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `an_event_roll_takes_both_branches` | `Chance 1` ⇒ 永远失败；`100` ⇒ 永远成功；`50` ⇒ 32 个种子**两侧都出现**；同种子同结果 |
| `gold_random_stays_inside_its_range_and_covers_it` | 64 个种子全在区间内、**两端都到过**、同种子同一个数；负区间夹在 0 |
| `the_unknown_room_events_are_readable`（§285 段） | Scrap Ooze 的 9 段代价 `3..11`、概率 `25..95` **逐段递进** |
| 内容门 `[6c]` | `gold_random` 两段整数/不跨零/不倒置/非 0:0；`relic_random` 不带载荷；`Chance`↔`NextFail` 成对且 1..=100；`NextFail` 也参与可达性 |

**负控**（`native/p285_negative.py`）：① 掷骰恒成功；② 区间退化成下限常数；
③ 升级链第 3 段抄第 2 段；④ 删掉 `NextFail` 留下 `Chance` —— 四条全 RED ✓。

### 285.7 账

事件 **13 → 16**；step **25 → 46**（Scrap Ooze 9 段 + Goop 3 + Statue 3 + Joust 6）；
镜像 **157,164 B**（core 123,132 B）；`rd-core` 797 / `rd-run` **154** / `rd-wasm` 130；
`STS_CONTENT PASS`；七道页面门 + `ACT1_SLICE` + `SOAK`；21/21。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '### G. ★ 基础值偏差'
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.5 事件概率（§285）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| 奖赏/赔付的时机 | 到达结果屏就生效 | 结果屏 `[Leave]` 上兑（多一次点击） | **偏差**：效果挂在选项上，"进入某段时执行"还没做 |
| `Wing Statue` `[Destroy]` | 只在牌组有"单次 ≥10 伤害的攻击牌"时出现 | **总是**出现 | **偏差**：条件词表问不了"某张牌打多少" |
| `Scrap Ooze` 的遗物 | 50/33/17 稀有度、随机 | 同（`pick_relic`），并排除已持有 | 一致 |
| `Dead Adventurer` | 25%/35% 精英归来（事件中途开战斗） | **没做** | 缺：事件里开战斗没有载体 |

### G. ★ 基础值偏差''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    e = io.open(EVENTS, encoding='utf-8').read()
    old = '''### 3.2 随机结果（`The Joust` 的 70/30）'''
    if old in e:
        e = e.replace(old, '''### 3.2 随机结果（`The Joust` 的 70/30）—— **§285 已做**

选项带 `Chance`/`NextFail`，掷骰走 `RunStream::Event`；`The Joust` 的 70/30 与
`Scrap Ooze` 的 9 段升级链都已落地。下面保留原文。

#### （原文）''')
    io.open(EVENTS, 'w', encoding='utf-8', newline='\n').write(e)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§284）', '（主计划 §1–§285）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§285 doc + gap rows + event-gaps + README')


main()
