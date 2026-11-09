"""§319：`event-gaps.md` 里 `the_library` / `sensory_stone` 两格，把"缺什么"写具体。

§319 顺着 `falling` 摸清了这两条的真实形状（wiki 原文）：

- `The Library` = `[Sleep] 回 33%（A15 20%）` + `[Read] 从 **20 张**里选 1 张`；
- `Sensory Stone` = 三个 `[Recall]`：**1 张无色牌 / 2 张 + 5 HP / 3 张 + 10 HP**。

所以它们缺的**不是同一个东西的一半**，而是同一件新原子：一个"事件窗口内的候选列表"
（`Pending::EventOffer` + 容量 20 + 页面列表）。`Sensory Stone` 还要在**抽候选时**带
`colorless` 过滤 —— 而内容里已经有 99 张带 `colorless` tag 的卡（不是缺池子）。
"""

import io

PATH = 'docs/event-gaps.md'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()
t = sub(t,
        '| `the_library` | 2 | "从 20 张里选一张" 需要 **N 选 1 的候选问句** | 中（`Offered` 问句只有 3 张的上限语义，需要"20 张任选"） |',
        '| `the_library` | 2 | `[Sleep]` 回 33%（A15 20%）**已有** `heal_pct`；`[Read]` 要"从 **20 张**里选 1 张" —— 需要**事件窗口的候选列表**（`Pending::EventOffer`，容量 20 + 页面列表；`PendingChoice::Offered` 是战斗内 3 张，形状不同） | 中 |',
        'library row')
t = sub(t,
        '| `sensory_stone` | 3 | "从一堆**无色**牌里选一张" | 中（同 `the_library`） |',
        '| `sensory_stone` | 3 | 三个 `[Recall]`：**1 张无色牌 / 2 张 + 5 HP / 3 张 + 10 HP** —— 同一件 `EventOffer`，外加**抽候选时按 `colorless` tag 过滤**（内容里已有 99 张该 tag 的卡，不是缺池子；缺的是"按 tag 抽候选"这一步） | 中 |',
        'stone row')
t = sub(t,
        '`sensory_stone` 要"无色牌 N 选 1"',
        '`sensory_stone` 要"候选列表 + `colorless` 过滤"（与 `the_library` 同一件原子）',
        'act3 summary')
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('event-gaps updated')
