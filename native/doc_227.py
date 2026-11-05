"""§227 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §227 三种"选完再改它"的形态：`Armaments` / `Warcry` / `Nightmare`

§226 的载体（`node.chooseCards` + `PendingChoice.candidates`）只回答了一件事："玩家选哪几张"。
这一节把**选完之后做什么**长成三种，并把 `Copy` 的载荷收进变体里。

### 227.1 `ChoiceThen` 从 4 个变体长到 6 个，`Copy` 长出载荷

| 变体 | 一句话 | 牌 |
|---|---|---|
| `Copy { copies, into }` | 原件不动，往 `into` 造 `copies` 份 | Dual Wield（`into = Hand`）、Nightmare（`into = SetAsidePile`） |
| `Upgrade` | 原地把定义 id 换成 `<id>+`，牌不动 | Armaments |
| `ToDrawPileTop` | 搬去抽牌堆**顶**（`ZonePlacement::Top` = 下一张就抽它） | Warcry |

§226 里 `copies` 是 `PendingChoice` 的字段，于是 `begin_choice` 得守着"`then` 是 Copy 时 `copies`
非零、否则为零"这条**外部**不变量。这一节把它挪进变体：能构造出来的非法状态越少越好，剩下的
只有 `Copy { copies: 0 }` 一种，仍然响亮拒绝（`CopiesNotApplicable`）—— 因为"复制 0 份"是一次
**成功**的空操作，那是最难发现的一种错。

### 227.2 Nightmare 的"下一回合"：内核一个字都没加

wiki：`Choose a card. Next turn, add 3 copies of that card into your hand. Exhaust.`

要跨回合记住"复制的是哪张牌"，最直接的想法是给内核加个"待造列表"。但**那几份副本本身就是记忆**：
答案落地时把 3 份副本造进 `SetAsidePile`，再挂一条 `standard.nightmare_pending` 状态，它的
`TurnStarted` 触发器把那一区搬进手牌并自摘（`modifyStatusStacks -99`，与 `standard.phantom_veil`
同一个写法）。整条规则都在内容里，内核只需要"复制到某个牌区"这一个能力。

判定这个状态"合法"的是**两道已有闸门**，一条都没新写：`the_status_catalogue_is_honest` 要求
"内核有规则**或**显式声明为 inert"，`sts-content` 的触发器表要求"`TurnStarted` 触发器的清单里
有它"。⇒ 加状态时想偷偷让它"什么都不做"是加不进去的。

### 227.3 `Armaments+` 需要 `upgradeCards` 的 `CardDefinitionId` 变成**可选**

"upgrade **all** cards in your hand"——内容在写程序时不知道玩家手上有什么定义，所以
`node.upgradeCards` 的 `CardDefinitionId` 缺席 = **整片牌区**（与 `RequireTag` 缺席 = 不过滤同一条
规则）。同时"这张牌能不能升级"的判据只留**一处**（`upgradable_definition`），因为同一张牌要走两条
路：批量（`upgradeCards`）与玩家选中的那一张（`chooseCards { Then: Upgrade }` 的候选收窄）。
升级后 id 的**拼法**也只剩一处（`state::upgraded_id`）—— 两处各写一遍 `push(b'+')` 就是
"同一个词表被两处认识"，迟早一处改。

内核只守**机械**那半（`+` 只能加一次、id 不能超长 ⇒ `NotUpgradable`），"有没有 `+` 行"由节点收窄
候选来保证：`chooseCards` 的 Upgrade 分支把候选过滤成"内容里真有 `+` 行"的牌，所以像 `dazed` 这种
永远升不了的牌**不会**出现在选项里（否则就是一个点了什么都不发生的按钮）。

### 227.4 三个"测试自己骗自己"的现场（都改掉了）

1. **Warcry 的"堆顶"判据不够强**：只往抽牌堆放一张"垫底"牌，而 Warcry 要**抽**一张 ⇒ 堆被抽空，
   "放堆顶"与"塞堆底"长得一样。改成放两张（抽走一张、留一张当垫底）才能分辨。
2. **Nightmare 的回合走法是硬的**：写死"结束 → 开始"两步，而战斗里有三个战斗员
   （英雄 + 两个敌人）⇒ 两步之后行动者是第二个敌人，触发器根本没跑。改成"循环直到行动者又是英雄"。
3. **手牌张数是下界不是等式**：回合末弃掉的手牌会被"抽牌堆空了就洗弃牌堆"重新抽回来 ——
   那是回合机的正常行为。所以判据用 `SetAsidePile 空了` 当触发器跑过的硬证据，手牌张数只断言 `>= 3`。

### 227.5 数字

* 单测 **923**（719 core + 110 run + 94 wasm，+5）；四个对拍不变（`FIGHT_DIFF 182/182`、
  `CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）。
* 内容：卡 **85 行**（+6：三张牌各带 `+` 行）、状态 **45**（+1 `standard.nightmare_pending`）、
  镜像 **87,360 B**（core 72,996）。
* 矩阵 **400 行**（+7：三张牌 ×2 + 状态）、扫描到的具名测试 **925**、wiki 对照 **47** 张
  （三张新牌都是 `wiki:dump`）。
* 三张牌的 wiki 数字照 `native/wiki_cards/` 的 dump：`Nightmare+` 是**降费到 2**（不是 Innate），
  `Armaments+` 是"整手牌"、`Warcry` 0 费抽 1(2) 且自我 Exhaust。
'''

path = ROOT + 'docs/port-plan.md'
text = io.open(path, encoding='utf-8').read()
assert '## §227' not in text, 'already there'
io.open(path, 'w', encoding='utf-8', newline='\n').write(text.rstrip('\n') + '\n' + SECTION)
print('doc_227: appended %d bytes' % len(SECTION))
