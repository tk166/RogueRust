"""§221 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §221 内容扩充：+10 张 Ironclad 牌、+2 件遗物、+2 个事件（以及一次容量上限的重新论证）

这一节只做**现有节点词汇能表达**的内容 —— 没有新机制，所以风险全在"内容抄错"上，而 §218 起的
卡牌 wiki 对照正好负责抓这一类。结果：`cards` **51 → 73 行**（基础 30 → 40）、遗物 **13 → 15**、
事件 **9 → 11**。

### 221.1 十张牌（数字全部来自 `native/wiki_cards/*.txt`）

| 牌 | wiki | 用到的既有节点 |
|---|---|---|
| Cleave | Deal 8 (11) to ALL | `dealDamage` + `sel.allEnemies` |
| Pommel Strike | 9 (10) + Draw 1 (2) | `dealDamage` + `node.drawCards` |
| Shrug It Off | Block 8 (11) + Draw 1 | `gainBlock` + `drawCards` |
| Thunderclap | 4 (7) ALL + 1 Vulnerable ALL | `dealDamage` + `applyStatus`（同一选择器） |
| Bludgeon | 32 (42) | `dealDamage` |
| Impervious | Block 30 (40), Exhaust | `gainBlock` + `PlayedCardDestinationZone`（§219 的载体） |
| Pummel | 2 damage 4 (5) times, Exhaust | `node.repeat` + 落区 |
| Wild Strike | 12 (17) + shuffle a Wound | `dealDamage` + `createCardInstance → DrawPile` |
| Ghostly Armor | Ethereal, Block 10 (13) | `gainBlock` + `TurnEndHandDestinationZone`（§144 的 Ethereal） |
| Battle Trance | Draw 3 (4), no more draw this turn | `drawCards` + `standard.draw_reduction` |

`program_facts` 因此要认识 `node.drawCards`（内容里第一次出现它）—— 不认识就 `AssertionError`，
这是"新节点必须登记"的闸门在起作用。

### 221.2 两件遗物（`13 → 15`）

`bag_of_marbles`（开战 1 层易伤）与 `oddly_smooth_stone`（开战 1 层敏捷）—— **都落在既有的
`RelicEffect::StartCombatStatus` 上**，没有新变体。所以改动只有两处：`Relics` 加两行、
`relic_effect` 加两个臂（`IMPLEMENTED_RELICS` 是内容门那张表，跟着改）。

### 221.3 两个事件（`9 → 11`）与两张诅咒

事件模型每间房**恰好两个选项**（`Effects0` / `Effects1` + A15 变体），所以只有两选项的 wiki 事件
能原样表达：

* `the_ssssserpent` — "Agree": +175 金币 + **Doubt**；"Disagree": 无事（A15: 两张 Doubt）。
* `the_mausoleum` — "Open Coffin": 一件遗物 + **Writhe**；"Leave": 无事。

带出来的两张真诅咒牌：`doubt`（**回合末 +1 Weak** —— 用 §220 刚做的 `LifecyclePrograms[TurnEndInHand]`，
没有新机制）与 `writhe`（`Innate` + `Unplayable`，纯关键字）。
`the_unknown_room_events_are_readable` 里那张"9 个事件"的表随之改成 11，并说明**池位比 id 多**
（`purification_shrine` / `golden_idol` / `ancient_forge` 跨幕复用）—— 这正是 §215 在矩阵里
顺手写下来的那件事。

### 221.4 撞到的容量：`MAX_POOL 64 → 96`

加完十张牌（+10 个 `+` 行）之后，奖励池 = **68 行**，而 `rd-run` 的 `MAX_POOL` 是 64 ⇒
`PoolTooLarge { pool: 68, max: 64 }`。**症状离原因很远**：一条"回放逐步对上"的测试在
`hop 1: begin a kind-4 node` 处返回 -2。

按 §161.1 的原则处理（容量常量放大后行为会变 ⇒ 它是语义）：

* 抬到 **96**，理由写进注释：96 就是**牌区单区上限**（`MAX_CARDS_PER_ZONE`），一个池子不该比
  "能装下这些牌的牌区"更大；`u8` 编码在 256 以下安全；
* 新增判据 `the_card_pool_fits_the_constant`：**从内容数行**与 `MAX_POOL` 比，而不是读常量比常量。
  下次内容再长过上限时，红的是一条说人话的测试，而不是"某条回放测试碰巧拒绝"。

### 221.5 数字

* **21/21 闸门绿**，单测 **910**（708 core + 109 run + 93 wasm，比 §220 多 1 条）；四条对拍不变。
* 镜像 **84,592 B**（core 71,200；+3,392 B：20 行卡 + 2 行诅咒 + 2 件事 + 2 件遗物）。
* 矩阵 **387 行**（+26：20 卡 + 2 诅咒 + 2 事件 + 2 遗物）、具名测试 **912**；
  卡牌 `SourceTie:wiki` 从 47 升到 **69**（新增的 20 行卡 + 2 行诅咒都有页面）。
* 内容侧还差：基础卡 **40 / 75**、遗物 15、事件 11（其中第一幕池 6 → 8 位）。
'''

port = io.open(ROOT + 'docs/port-plan.md', encoding='utf-8').read()
assert '## §221' not in port
io.open(ROOT + 'docs/port-plan.md', 'a', encoding='utf-8', newline='\n').write(SECTION)
print('port-plan §221 appended')

readme = io.open(ROOT + 'README.md', encoding='utf-8').read()
for old, new in [
    ('（§1–§220，每一轮都留数字、记下被推翻的结论）', '（§1–§221，每一轮都留数字、记下被推翻的结论）'),
    ('编译成 81,200 B 的 `rdcf` 镜像（core 镜像 68,640 B）', '编译成 84,592 B 的 `rdcf` 镜像（core 镜像 71,200 B）'),
]:
    assert readme.count(old) == 1, old[:40]
    readme = readme.replace(old, new)
io.open(ROOT + 'README.md', 'w', encoding='utf-8', newline='').write(readme)
print('README updated')
