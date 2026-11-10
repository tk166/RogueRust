"""§322 文档 —— README / wiki-gap / event-gaps / port-plan。

数字来自 `native/gap_check.py` 的 pastable 区块（events 33 = 三幕池 10+13+10；镜像 183,716 /
core 146,784 B）。
"""

import io

README = 'README.md'
WIKI = 'docs/sts-wiki-gap.md'
GAPS = 'docs/event-gaps.md'
PLAN = 'docs/port-plan.md'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(README, encoding='utf-8').read()
t = sub(t, '**26 个事件**（三幕池 10+9+10 = 29 条，跨幕复用 3 条）',
        '**30 个事件**（三幕池 10+13+10 = 33 条，跨幕复用 3 条）', 'README events')
t = sub(t, '编译成 181,940 B 的 `rdcf` 镜像（core 镜像 145,008 B）',
        '编译成 183,716 B 的 `rdcf` 镜像（core 镜像 146,784 B）', 'README image')
io.open(README, 'w', encoding='utf-8', newline='\n').write(t)
print('README ok')

t = io.open(WIKI, encoding='utf-8').read()
t = sub(t, 'enemy actions 159 / relics 152 / potions 33 / events 29 (10+9+10) / start deck 10',
        'enemy actions 159 / relics 152 / potions 33 / events 33 (10+13+10) / start deck 10',
        'wiki-gap counts')
t = sub(t, '`29` 是三个幕的事件池之和（`10+9+10`）', '`33` 是三个幕的事件池之和（`10+13+10`）',
        'wiki-gap pool sum')
io.open(WIKI, 'w', encoding='utf-8', newline='\n').write(t)
print('wiki-gap ok')

t = io.open(GAPS, encoding='utf-8').read()
t = sub(t,
        '| 2（The City，13 条） | Ancient Writing / Augmenter / The Colosseum / Council of Ghosts / Cursed Tome / Forgotten Altar / The Library / Masked Bandits / The Mausoleum / The Nest / Pleading Vagrant / Old Beggar / Vampires | **6**（§320 补了 `the_library`）（另有 `the_joust`：wiki 这一版页面没列它，我们按 2 幕放） | `augmenter` / `council_of_ghosts` / `cursed_tome` / `the_library` / `masked_bandits` / `pleading_vagrant` / `old_beggar` / `vampires` |',
        '| 2（The City，13 条） | Ancient Writing / Augmenter / The Colosseum / Council of Ghosts / Cursed Tome / Forgotten Altar / The Library / Masked Bandits / The Mausoleum / The Nest / Pleading Vagrant / Old Beggar / Vampires | **10**（§320 `the_library`，§322 `council_of_ghosts` / `pleading_vagrant` / `old_beggar` / `vampires`；另有 `the_joust`：wiki 这一版页面没列它，我们按 2 幕放） | 其余 **3**：`augmenter`（要"两张随机变形"）、`masked_bandits`（要三名册外敌人 Pointy / Romeo / Bear）、`cursed_tome`（`necronomicon` **明确不做**，所以这条也不做） |',
        'gap act2 row')
for name, done in [
    ('council_of_ghosts', '**§322 已做**：`card:apparition` ×5（A15 ×3）+ `max_hp_pct:50` + 两段（Accept/Refuse 都去 `[Leave]`）'),
    ('pleading_vagrant', '**§322 已做**：`gold_cost:85` + `relic_random` / `[Rob]` = `relic_random` + `curse:shame`'),
    ('old_beggar', '**§322 已做**：池子 `MinGold: 75` + `gold_cost:75` + `remove_card`（wiki 是**删牌**，不是给遗物）'),
    ('vampires', '**§322 已做**：`remove_all:strike`（新原子）+ `card:bite` ×5 + `max_hp_pct:30` + `relic_lose:blood_vial` 那一条'),
]:
    pass
t = sub(t, '| ~~`old_beggar`~~ | 2 |', '| ~~`old_beggar`~~ | 2 |', 'noop') if False else t
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(t)
print('event-gaps: act2 row ok')

PLAN = io.open(PLAN, encoding='utf-8').read()
assert '## §322' not in PLAN, 'port-plan already has §322'
entry = """
## §322 Act 2 四条 + 一个真 bug（`card:` / `curse:` 的 `Amount`）

### 先修 bug：`Amount` 被静默丢掉

内容里 `winding_halls` 写 `card:madness` Amount **2**、§321 的 `[I am Rich]` 写
`curse:normality` Amount **2** —— 而内核**只给一张**：`parse` 把 `amount` 丢了，`apply` 也只
`push_card` 一次。屏幕写 2、牌组里 1，所有闸门都绿。

修法：`GainCurse(u8)` / `GainCard(u8)` 带上张数，`card_count(amount)` 把 `0` 读作 1、
`1..=5` 原样、其余**解析失败**（不截断）。`council_of_ghosts` 的 5 张与 `vampires` 的 5 张
正好靠它。

### 新原子：`remove_all:<id>`

`vampires` 的 "Remove all Strikes"。载荷是**基础 id**，`+` 行算同一张（去尾 `+` 比较），
倒着删（`remove_at` 会前移，正着遍历会跳过相邻那张）。一种都没有 ⇒ **成功**（不是错误）。

### 四条事件

| 事件 | 内容 |
|---|---|
| `council_of_ghosts` | `[Accept]` 5（A15 3）张 Apparition + 50% 上限；`[Refuse]` → `[Leave]` |
| `pleading_vagrant` | `[Give 85 Gold]` → 随机遗物；`[Rob]` → 随机遗物 + `Shame`；`[Leave]` |
| `old_beggar` | 池子 `MinGold: 75`；`[Offer 75 Gold]` → 付 75 + **删一张牌**；`[Leave]` |
| `vampires` | `[Offer: Blood Vial]`（有血瓶时）→ 失血瓶 + 全删打击 + 5 Bite；`[Accept]` → 同上 + 30% 上限；`[Refuse]` |

### 判据

`rd-run` 三条：`curse:`/`card:` 的**张数**（1 与 3 两侧，且 6 / -1 解析失败）、
`remove_all` 全删（含 `+` 行、含**相邻两张**、以及"一种都没有 ⇒ 成功"）。
`rd-wasm` 四条端到端（真的在 `?` 房上 `begin_event` + `rd_run_choose`）：
`pleading_vagrant` `[Rob]`（`relic_random` 是 **wasm 解析**的，所以必须在那一层验）、
`old_beggar`（付 75 + 进改牌问句）、`vampires`（全删打击 + 5 Bite + 30% 上限）、
`council_of_ghosts`（5 Apparition + 50% 上限）。

负控三条各红在预期位置：`card:` 张数被丢掉 / `remove_all` 只扫一张 / `card_count` 恒为 1。
第二条第一版**没红** —— 我那次"只删一张"的改法其实仍会删到全部（`break` 放错了），
改成"只扫第 0 格"才真的红。这条经历与 §4.16 是同一个形状：负控也要**先证明它改坏了**。

⚠️ `masked_bandits` 仍缺：要三名册外敌人（Pointy / Romeo / Bear）的完整行（动作、意图、
开场数值），不是一条内容能补的；`cursed_tome` 因 `necronomicon` **明确不做**而不做；
`augmenter` 要"两张随机变形"（`transform_random` 并不存在，§321 前的那份清单写错了）。

数字：事件 **30** 个（三幕池 10+13+10 = 33 条）、镜像 183,716 / core 146,784 B、
`rd-core 811 / rd-run 209 / rd-wasm 166`、units 1186（下限 1179 → 1186）。
**Act 2 事件 6/13 → 10/13**。
"""
PLAN = PLAN.rstrip('\n') + '\n' + entry
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(PLAN)
print('port-plan ok')
