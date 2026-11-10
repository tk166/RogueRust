"""§324 文档 —— README / wiki-gap / event-gaps / port-plan。

数字来自 `native/gap_check.py` 的 pastable 区块：cards 295（155+140）/ relics 153 /
events 35（10+15+10）/ 镜像 186,856 · core 149,416 B。
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
t = sub(t, '293 条卡行（154 张基础 + 139 条升级行）', '295 条卡行（155 张基础 + 140 条升级行）',
        'README cards')
t = sub(t, '/ 152 遗物 /', '/ 153 遗物 /', 'README relics')
t = sub(t, '**31 个事件**（三幕池 10+14+10 = 34 条，跨幕复用 3 条）',
        '**32 个事件**（三幕池 10+15+10 = 35 条，跨幕复用 3 条）', 'README events')
t = sub(t, '编译成 186,244 B 的 `rdcf` 镜像（core 镜像 148,836 B）',
        '编译成 186,856 B 的 `rdcf` 镜像（core 镜像 149,416 B）', 'README image')
io.open(README, 'w', encoding='utf-8', newline='\n').write(t)
print('README ok')

t = io.open(WIKI, encoding='utf-8').read()
t = sub(t, 'cards 293 (base 154 + plus 139)', 'cards 295 (base 155 + plus 140)', 'wiki-gap cards')
t = sub(t, '/ relics 152 /', '/ relics 153 /', 'wiki-gap relics')
t = sub(t, 'events 34 (10+14+10)', 'events 35 (10+15+10)', 'wiki-gap events')
t = sub(t, '`34` 是三个幕的事件池之和（`10+14+10`）', '`35` 是三个幕的事件池之和（`10+15+10`）',
        'wiki-gap pool sum')
io.open(WIKI, 'w', encoding='utf-8', newline='\n').write(t)
print('wiki-gap ok')

t = io.open(GAPS, encoding='utf-8').read()
t = sub(t, '其余 **2**：`augmenter`（要"两张**随机**变形"—— `transform_random` 并不存在）、`cursed_tome`（`necronomicon` **明确不做**，所以这条也不做）',
        '其余 **1**：`cursed_tome`（`necronomicon` **明确不做**，所以这条也不做）',
        'gaps remaining')
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(t)
print('event-gaps ok')

text = io.open(PLAN, encoding='utf-8').read()
assert '## §324' not in text, 'port-plan already has §324'
entry = """
## §324 `augmenter` —— Act 2 的 12/13（最后一条是明确不做）

wiki 的三个选项：

| 选项 | 效果 | 用什么实现 |
|---|---|---|
| `[Test J.A.X.]` | 牌组加一张 **J.A.X.**（0 费无色特殊技能：失 3 血、+2 力量；`+` 行 +3） | 新卡两行 + `card:jax` |
| `[Become Test Subject]` | **选** 2 张，各改造一次 | 新原子 `transform_choose:<n>` |
| `[Ingest Mutagens]` | **Mutagenic Strength**（开战 +3 力量；第一回合末失 3） | **早就有了**（见下） |

⚠️ 旧笔记说这条是"两张**随机**变形"，**错**：wiki 的更新记录写的是
*"now allows choosing 2 cards to Transform instead of selecting 3 at random"*。

### `transform_choose:<n>`

它是"N 次**待办**的改牌"，所以复用**拾取欠账**通道（`pickup_change` + `pickup_picks`）——
那条通道本来就是"与 `pending` 无关的欠账"，页面也已经按它画选择器
（`describePickupCard`）。**没有新 `Pending`、没有新屏、没有新状态字段。**
两条拒绝都是"不静默吞额度"：牌组空 ⇒ `DeckEmpty`；**已经欠着**别人的改牌
（`empty_cage` / `astrolabe`）⇒ `WrongPhase`（而不是覆盖它）。

### 一个我自己造出来的重复（值得记）

我按 wiki 给 `mutagenic_strength` 加了一条新 `RelicEffect::StartCombatStatuses`（复数），
结果既有判据当场红：**这件遗物早就实现了** —— 内容里有 `standard.mutagenic_strength`
这个状态（`TurnEnded` 触发器 + `mutagenic_strength_turns` 计数），`relic_effect()` 也早就
把它映射过去了。于是我把新变体**整条撤掉**（不留死代码），判据改成钉住**既有**实现。
教训：加"新遗物"之前先 `grep` 一遍 id —— 内容里可能已经躺着它。

### 判据

`rd-run` 三条：欠账通道两侧（`transform_choose:2` ⇒ 2 次、取两次清空、事件本身已收尾）、
两条拒绝（空牌组 / 已有欠账，且都"一个字节不改"）、`mutagenic_strength` 走它自己的载体状态
（并且没有这件遗物时没有它）。`rd-wasm` 三条端到端：三个选项各一遍 ——
J.A.X. 真的进牌组、`[Become Test Subject]` 欠 2 次且 `rd_run_pickup_card` 两次后尺寸不变、
`[Ingest Mutagens]` 挂上 `standard.mutagenic_strength`。

负控两条各红在预期位置：欠账只记一次 / 覆盖别人的欠账。

⚠️ **`run_slot()` 是进程级单例 ⇒ 这三条 wasm 判据必须单线程跑**（验收本来就是
`--test-threads=1`）。并行时实测一条报 `WrongPhase`、一条报 `-1 无文本`，单线程三条全绿 ——
"失败随顺序变化"就是共享单例的指纹，已写进测试注释。

数字：卡 **295**（155 + 140，镜像 186,856 B）、遗物 **153**、事件 **32**（三幕池
10+15+10 = 35）、`rd-core 811 / rd-run 212 / rd-wasm 170`、units 1193（下限 1187 → 1193）。
**Act 2 事件 11/13 → 12/13**（第 13 条 `cursed_tome` 因 `necronomicon` 明确不做而不做）。
"""
text = text.rstrip('\n') + '\n' + entry
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(text)
print('port-plan ok')
