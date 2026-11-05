"""§229 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §229 `Rampage` / `Rip and Tear` / `Searing Blow`：每副本计数器、载体的复用、以及"任意次升级"

三张牌里**只有一张**需要新内核能力 —— 这一节的第一件事是把另外两张的载体找出来，别重造。

### 229.1 先查再写：`Rip and Tear` 内核一行没加

`Rip and Tear`（wiki：`Deal (7;9) damage to a random enemy twice.`）就是 §228 那个节点的
`Times: 2`。所以它这一节的改动**全在内容里**，判据也只有一条（两次命中、7/9），随机的"每击重掷"
由 §228 的 `sword_boomerang_rerolls_a_target_for_each_hit` 钉着，不抄第二份。

### 229.2 `Rampage`：一个"这张牌记住了一件事"的载体

wiki：`Deal 8 damage. Increase **this card's** damage by (5;8) this combat.`

"这张牌"是**每一份副本**，不是每个定义、也不是每个战斗员（牌组里两张 Rampage 各自涨各自的）。
本内核里每副本数据的唯一载体一直是 **mark counter**（每副本价格 `standard.card_cost_delta` 已经在用），
所以这一节只补两半：

| 新东西 | 一句话 |
|---|---|
| `ExprContext::resolving_card` + `card.counter { CounterId }` | 表达式第一次能读"正在结算的那份副本"的一个整数 |
| `cardInstance.resolving` | 卡实例表达式里的"正在结算的那张"，与 `cardInstance.iterated` 并列 |
| `node.addCardCounter { CardExpression, OwnerSelector, CounterId, Delta }` | 给那份副本的计数器加一个**相对**增量 |

§226 只用"是不是自己"压了一个 `event_flags` 位（`card.isResolving`）就够了；这次要读**整数**，
位图不够用，所以第一次把槽本身（`Option<CardSlot>`）交给表达式层。三种"没有"各有各的答案：
没有迭代卡 ⇒ `NoTarget`；没有正在结算的牌 ⇒ 两个新表达式都 `NoTarget`（在状态/遗物节目里读
"这张牌的计数器"是内容 bug，"0 加成"会把它藏起来）。

判据三段，缺一段这张牌就可能"看起来能用"：第一次 8、第二次 13（升级版 16）；
**反例**是另一张没打过的同名副本，伤害仍然是 8 —— 每副本而不是每定义。

### 229.3 `Searing Blow`：把两处"猜"换成"查表"

wiki：`Deal (12;16) damage. Can be Upgraded any number of times.`

本内容的升级是**另一行 CARD**（`strike` → `strike+`），所以"任意次"需要的只是**id 能连续加 `+`**。
卡住它的不是模型，是两处**猜**：

1. `state::upgraded_id` 见到以 `+` 结尾的 id 就返回 `None`（想防 `strike+` → `strike++`）；
2. `rd_run::upgrade_at`（事件/祝福的"升级一张牌"）同样用 `ends_with('+')` 判定"升过了"。
   它的调用方 `apply_deck_change` **手里就有 `pool`**，只是没往下传 —— 于是它查不了表，只能猜。

两处都改成**查表**：`+` 能叠几次由内容写了几行决定，`strike++` 不存在 ⇒ `strike+` 依然升不了。
于是 `searing_blow` 只要把行写够（本内容 8 行：12/16/…/40）就成立，**内核与运行层都不认识这张牌**。

⚠️ 这条改动顺手暴露了一个真实的边界：`state::resolve_upgrade` 现在**只守机械那一半**
（`+` 能加、id 不超长），"有没有那一行"由发问的节点收窄候选来保证（§227 的
`upgradable_definition`）。原来那条 `NotUpgradable`（见到 `+` 就拒）是**猜**，现在它只拒绝
"加一个 `+` 就装不下"。判据因此改成两头：内容侧由 Armaments 的 `dazed` 不进候选钉住，
内核侧只剩长度。这才是这条规则真正的分工。

### 229.4 容量常量跟着内容一起抬（并且改的是那个**错**的理由）

`MAX_POOL` 从 96 抬到 112。原来那条注释的推理是"池子不该比牌区大"，§229 到 101 行时它红了 ——
而那条推理**把池子当成了牌区**：这个池子是**目录**（基础行 + `+` 行 + 状态/诅咒牌），不装在同一张
牌区里。真实约束只有两条：`>= 内容行数`（`pool_fits` 会响亮拒绝，不许截断），以及离 `u8` 很远。

同时两处测试夹具补上了 `strike+`：`upgrade_at` 不再盲拼 `+`，一个没有 `strike+` 的池子里"升级"
本来就该是**空操作** —— 夹具里没有那一行，测的就不是"升级成功"。

### 229.5 数字

* 单测 **929**（724 core + 110 run + 95 wasm，+3）；四个对拍不变（`FIGHT_DIFF 182/182`、
  `CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）。
* 内容：卡 **101 行**（+8：`Rip and Tear` 2、`Rampage` 2、`Searing Blow` **8**）、
  镜像 **89,720 B**（core 74,544）。
* 矩阵 **416 行**（+12）、扫描到的具名测试 **931**、wiki 对照 **47** 张。
'''

path = ROOT + 'docs/port-plan.md'
text = io.open(path, encoding='utf-8').read()
assert '## §229' not in text, 'already there'
io.open(path, 'w', encoding='utf-8', newline='\n').write(text.rstrip('\n') + '\n' + SECTION)
print('doc_229: appended %d bytes' % len(SECTION))
