"""§325 文档 —— README / wiki-gap / event-gaps / port-plan。

数字来自 `native/gap_check.py` 的 pastable 区块：events 38（13+15+10）/ encounters 64 /
镜像 188,528 · core 151,092 B。
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
t = sub(t, '**61 怪 / 63 遭遇 /', '**61 怪 / 64 遭遇 /', 'README encounters')
t = sub(t, '**32 个事件**（三幕池 10+15+10 = 35 条，跨幕复用 3 条）',
        '**35 个事件**（三幕池 13+15+10 = 38 条，跨幕复用 3 条）', 'README events')
t = sub(t, '编译成 186,856 B 的 `rdcf` 镜像（core 镜像 149,416 B）',
        '编译成 188,528 B 的 `rdcf` 镜像（core 镜像 151,092 B）', 'README image')
io.open(README, 'w', encoding='utf-8', newline='\n').write(t)
print('README ok')

t = io.open(WIKI, encoding='utf-8').read()
t = sub(t, 'monsters 61 / encounters 62', 'monsters 61 / encounters 64', 'wiki-gap encounters')
t = sub(t, 'events 35 (10+15+10)', 'events 38 (13+15+10)', 'wiki-gap events')
t = sub(t, '`35` 是三个幕的事件池之和（`10+15+10`）', '`38` 是三个幕的事件池之和（`13+15+10`）',
        'wiki-gap pool sum')
io.open(WIKI, 'w', encoding='utf-8', newline='\n').write(t)
print('wiki-gap ok')

t = io.open(GAPS, encoding='utf-8').read()
# Act 1 的统计行：8/11 → 11/11，并说明 `designer_in_spire`/`secret_portal` 之类不在这一版清单里。
t = sub(t, '| 1（Exordium，11 条） |', '| 1（Exordium，11 条） |', 'noop') if False else t
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(t)
print('event-gaps: (row counts updated separately)')

text = io.open(PLAN, encoding='utf-8').read()
assert '## §325' not in text, 'port-plan already has §325'
entry = """
## §325 Act 1 三条：`big_fish` / `living_wall` / `mushrooms`

| 事件 | 内容 |
|---|---|
| `big_fish` | `[Banana]` `heal_pct:33` / `[Donut]` `max_hp:5` / `[Box]` `relic_random` + `curse:regret`，三个都去 `[Leave]` |
| `living_wall` | `[Forget]` / `[Change]` / `[Grow]` —— 三个既有的 `DeckChange`（Remove / Transform / Upgrade） |
| `mushrooms` | 池子 `MinFloor: 7`；`[Stomp]` 打 **3 只 Fungus Beast**（新遭遇 `enc_three_fungi_beasts`）→ `After` 段给 `relic:odd_mushroom`；`[Eat]` `heal_pct:25` + `curse:parasite` |

`big_fish` 与 `living_wall` 是**纯内容**。`mushrooms` 需要三样：

1. **三只真菌的遭遇**（事件专属，登记进 `INV_EVENT_ONLY`），
2. **事件池名的 hop 拼写**（`"Mushrooms" => "EncounterTables.Mushrooms"`，`rd-core` 两处字面量），
3. `odd_mushroom` —— **早就实现了**（§264 的 `OverrideScope: Self` 易伤幅值改写：
   "When Vulnerable, take 25% more attack damage rather than 50%"），一句内核都没改。

### 两个连带修好的共用助手

加内容之后 **两条既有判据红了**，两条都是"助手只认识旧世界的形状"：

1. `settle_here` / `settle_event` 只认 `Pending::Event`（5）与选牌（7/8）。§320 的候选面板（9）
   与§324 的"欠几次改牌"通道都不认识 ⇒ 走到一半，下一步 `rd_run_step` 报的是"这一格还没结算"
   （那句话看不出真因）。同时补上**事件变成战斗**那一条（`mushrooms` 的 `[Stomp]`、
   `dead_adventurer` 的伏击）—— 不打完它，节点永远不结算。
2. **`an_unknown_room_opens_an_event_and_resolves_it` 把内容普查抄成了断言**：
   "恰好两个选项、效果码 ≤ 10"。加一条正常事件（合法地给出码 16）它就假红。改成对**任何**
   事件都成立的契约：槽数 ≥ 2、每槽有标签、效果码 ∈ `-1 ∪ 1..=16`、越界为 `-1`；
   简单数字效果（1..=5）仍逐个验，其余码交给各自事件的判据。

### 已知偏差（如实记）

`parasite` 的**程序是空的**："被变形/移除时 -3 上限"**没有**实现。理论上它属于
`remove_at`（牌离开牌组的唯一入口），但把卡 id 写进 `rd-run` 会违反 §133 的分层
（运行层不读内容），所以这条先记成偏差 —— 现在它是一张纯 inert 的不可打出诅咒。

数字：事件 **35**（三幕池 13+15+10 = 38）、遭遇 **64**、镜像 188,528 · core 151,092 B、
`rd-core 811 / rd-run 212 / rd-wasm 174`、units 1198（下限 1193 → 1198）。
**Act 1 事件 8/11 → 11/11**；三幕合计 **28/31**（余下三条：`cursed_tome` 明确不做、
`secret_portal` 与 `designer_in_spire` 不在本版清单口径内）。
"""
text = text.rstrip('\n') + '\n' + entry
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(text)
print('port-plan ok')
