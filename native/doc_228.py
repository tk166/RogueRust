"""§228 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §228 随机目标（`Sword Boomerang`）与"按格挡打伤害"（`Body Slam`）

两张牌各差一样内核能力，而且都不是"再多一个词条"那种：

| 牌 | wiki | 缺的是什么 |
|---|---|---|
| `Sword Boomerang` | 1 费 Common Attack：`Deal 3 damage to a random enemy (3;4) times.` | **每一击各自重掷**一个目标 |
| `Body Slam` | 1 费（`+` 0 费）Common Attack：`Deal damage equal to your Block.` | 一个**读防御池**的表达式 |

### 228.1 随机目标为什么必须是一个**节点**，而不是一个选择器

直觉做法是加 `sel.randomEnemy`，但选择器解析拿的是 `&CombatState`（只读，见
`targets::SelectionContext`），而"抽一次签"要**推进 `random_step`** —— 那是与洗牌/掷骰同一本账
（`shuffle_candidates` 一直是这么记的）。只有拿 `&mut ExecContext` 的**节点**能同时读状态与推进
RNG，所以新节点是 `node.dealDamageToRandomTarget`：

```
{TargetSelector（候选池，内容写 sel.allEnemies）, Amount, Times, IgnoresBlock?}
```

三条语义各有一条判据（任何一条单独坏掉都还能看起来"在打伤害"）：

* **每一击各自抽签** —— 用 `rng::shuffled_pick_index`（与洗牌同一个生成器），每击一格
  `random_step`；判据断言 `random_step` **正好**推进"次数"格，否则就是"抽一次签、连打 N 下"；
* 候选池是**派发那一刻**解析的（`sel.allEnemies` = 活着的敌人），中途离场的目标不再是候选；
* 池子空 ⇒ **一击都没有**（不是错误）：一条对"所有活敌"的抽签，在没有活敌时本来就没有答案。

`Times` 上限 `MAX_RANDOM_HITS = 24`（`MAX_COMBATANTS` 的两倍）：再往上不是"更强的牌"，而是把
效果队列当无限用 —— 那条线该在内容层先说不像话，而不是到运行期变成 `Capacity`。

### 228.2 `combatantDefensivePool`：一个读池子的表达式

形状照 `combatantCurrentResource`（`Selector` + 池的 key），字段名是**我们定的**（理由同
`currentHealth`：镜像里没有这条 op，定义权在 `docs/spec/sts-act1-plan.md` §9-4）。
池子不存在 ⇒ `0`（"没有格挡"是常态，不是错误）。

`Body Slam` 因此就是一条普通的 `node.dealDamage`，`Amount` 是那个表达式 —— 伤害在**派发那一刻**
求值，而那一刻玩家的格挡就是牌面说的"你的格挡"。判据两端都测：格挡 13 ⇒ 掉 13，格挡 0 ⇒ 掉 0。

### 228.3 两张牌的 wiki 数字

* `Sword Boomerang` 升级改的是**次数**（`(3;4) times`，伤害固定 3）—— 所以两行只差 `Times`，
  `INV_CARDS` 里也只差最后一个字段。把"升级"当成"伤害 +1"会写成 4×3，那是另一张牌；
* `Body Slam` 升级只**降费**（`CostPlus = 0`），程序一个字都不变 —— 两行的 `Facts` 因此完全相同。

### 228.4 数字

* 单测 **926**（721 core + 110 run + 95 wasm，+2）；四个对拍不变（`FIGHT_DIFF 182/182`、
  `CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）。
* 内容：卡 **89 行**（+4：两张各带 `+` 行）、镜像 **88,024 B**（core 73,464）。
* 矩阵 **404 行**（+4）、扫描到的具名测试 **928**、wiki 对照 **47** 张（两张都是 `wiki:dump`）。
'''

path = ROOT + 'docs/port-plan.md'
text = io.open(path, encoding='utf-8').read()
assert '## §228' not in text, 'already there'
io.open(path, 'w', encoding='utf-8', newline='\n').write(text.rstrip('\n') + '\n' + SECTION)
print('doc_228: appended %d bytes' % len(SECTION))
