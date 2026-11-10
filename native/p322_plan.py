import io

PLAN = 'docs/port-plan.md'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


text = io.open(PLAN, encoding='utf-8').read()
assert '## §322' not in text, 'port-plan already has §322'
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
text = text.rstrip(chr(10)) + chr(10) + entry
io.open(PLAN, 'w', encoding='utf-8', newline=chr(10)).write(text)
print('port-plan ok')
