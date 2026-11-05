"""§230 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §230 `Flex` / `Limit Break` / `Perfected Strike`，以及 `Inflame+` 的一条**牌面谎言**

照例先检索已有实现，结论分三类：

| 牌 | 检索结论 | 这一节做了什么 |
|---|---|---|
| `Inflame` | **已存在**，而且程序是对的（`inflame` 2 层、`inflame+` **3 层**） | 只改它 `+` 行的 `DescriptionKey` —— 那句写着 "Gain 2 Strength." |
| `Flex` | 缺 | 纯内容：`standard.lose_strength` 这条状态本来就在 |
| `Limit Break` | 缺 | 纯内容：翻倍 = 把"当前层数"当增量 |
| `Perfected Strike` | 缺，且没有"按 tag 数牌"的能力 | 一个节点 `node.dealDamageWithTagBonus` |

### 230.1 一条机器查不出、人一眼能看见的错

`inflame+` 的**程序**给 3 层力量（与 wiki 的 `Gain (2;3) Strength` 一致），而它的
`DescriptionKey` 写的是 "Gain 2 Strength."。所有闸门都是绿的：`INV_CARDS` 比的是**事实**（3 ✓）、
`INV_CARD_WIKI` 比的也是**数字**（3 ✓），而牌面上给玩家看的那句话没有任何判据。

⇒ 这是"闸门看不见的那一类"里最便宜的一种（一句文案），也是最该顺手改的一种：玩家读到的数字
必须等于内核执行的数字。**没有为它加闸门**（那需要把散文解析回数字，等于在闸门里重写一遍规则，
§218 明确拒绝过）；记在这里，让它至少不是"没人知道"。

### 230.2 `Flex`：临时力量根本不需要新东西

wiki：`Gain (2;4) Strength. At the end of this turn, lose (2;4) Strength.`

`standard.lose_strength` 早就在（回合末扣掉等于层数的力量并自摘，`TurnEnded` 触发器）。所以
`Flex` = `sequence[applyStatus(strength, N), applyStatus(lose_strength, N)]`，**内核一行没加**。

判据必须走完一个回合：只断言"加了 2 层"的话，一个把力量**永久**加上的实现也一样绿。

### 230.3 `Limit Break`：翻倍 = 增量取当前层数

`modifyStatusStacks` 的 `Delta` 一直是**表达式**，而 `combatantStatusStacks` 读的是"此刻"的层数
⇒ `Delta = combatantStatusStacks(self, strength)` 就是把 12 变成 24。零内核改动。

⚠️ wiki 的写法是 `Double your Strength.(<br>Exhaust.;)` —— 括号里是「**基础;升级**」，
所以**基础版自消耗、`+` 版不消耗**（升级去掉 Exhaust）。判据两侧都测，写反了会立刻红。

### 230.4 `Perfected Strike`：为什么数牌要落在**节点**上

wiki：`Deal 6 damage. Deals (2;3) additional damage for ALL your cards containing "Strike".`
正文更精确：**"in your deck when this card is played"** ⇒ 手牌 + 抽牌堆 + 弃牌堆（消耗掉的牌不算）。

查 tag 要读**内容**（`Content::card_has_tag`），而 `ExprContext` 这一层一直只拿 `&CombatState`
（§225 把卡牌 tag 压成 `event_flags` 位，那是"一次事件的事实"，数不了整副牌）；而"整片牌区里有几张
带某个 tag"正是节点层已经在做的事（`forEachCardInZone` 的 `TagFilter`）。所以按惯例加**一个具体节点**
`node.dealDamageWithTagBonus { TargetSelector, Amount, Bonus, Tag }`，不开谓词语言。

两处值得记下来：

* **"谁的牌"与"打谁"是两个槽**。第一版拿 `TargetSelector` 解出来的**敌人**去数手牌，于是永远 0 张、
  牌只打基础伤害 —— 而"只打基础伤害"看起来完全正常（绿闸门、合理数字）。现在数的是 `ctx.source`
  的牌堆，`TargetSelector` 只决定打谁。
* **它自己也数**。参考里打出的牌要到 `onTerminal` 才落区（§225），所以这张牌在结算时仍在手牌、
  仍在"你的牌组"里 —— 与 wiki 的 "increases not only the damage of other copies, but also of
  itself" 一致。内容上也把它标上 `strike` tag（它的名字里就有 "Strike"），否则它会漏掉自己那 2 点。

### 230.5 数字

* 单测 **932**（727 core + 110 run + 95 wasm，+3）；四个对拍不变（`FIGHT_DIFF 182/182`、
  `CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）。
* 内容：卡 **107 行**（+6：三张各带 `+` 行；`Inflame` 只是改文案）、镜像 **90,808 B**（core 75,156）。
* 矩阵 **422 行**（+6）、扫描到的具名测试 **934**、wiki 对照 **47** 张。
'''

path = ROOT + 'docs/port-plan.md'
text = io.open(path, encoding='utf-8').read()
assert '## §230' not in text, 'already there'
io.open(path, 'w', encoding='utf-8', newline='\n').write(text.rstrip('\n') + '\n' + SECTION)
print('doc_230: appended %d bytes' % len(SECTION))
