"""§231 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §231 `True Grit` / `Battle Trance` / `Reaper`：一个修正、一个新节点、两条既存载体的复用

照例先检索，三类结论：

| 牌 | 检索结论 | 这一节做了什么 |
|---|---|---|
| `Battle Trance` | **已存在**（抽 3/4），但第二半挂的状态**错** | 换成 `standard.no_draw`（新状态 + 内核规则） |
| `True Grit` | 缺 | 纯内容（格挡 + `selectCards`/`chooseCards`）+ 节点学会 `Then: "Exhaust"` |
| `Reaper` | 缺，且没有"按掉血回血" | 一个节点 `node.dealDamageAndHealByLoss` |

### 231.1 `Battle Trance`：一条"两个轴都错"的既有实现

它原来在抽完牌之后挂 `standard.draw_reduction`。那条状态的语义是"**下回合**起手少抽 1 张"
（`Pipeline: TurnStartDraw` + `TurnEnded` 衰减），而 wiki 说的是
"You cannot draw additional cards **this turn**" —— **时机错**（下回合 vs 本回合）、
**幅度错**（少 1 张 vs 一张都不能抽）。

修法：新状态 `standard.no_draw`，规则写在 **`resolve_request` 的 `DrawCards` 分支**里。

⚠️ 规则的位置是被判据逼出来的。第一版写在 `exec::draw_cards_node`（内容是这么走的），
`battle_trance_blocks_further_draws_only_this_turn` 立刻红在"再抽一张还是抽到了" ——
因为**抽牌药水**根本不经过那个节点（它直接发 `EffectRequest::DrawCards`）。**一次抽牌就是一次抽牌**，
所以规则只该有一处，且在请求那一层。回合起手抽牌不走这条请求，因此"additional"的语义自然成立。

状态本身用一条内容 `TurnEnded` 触发器自摘（`modifyStatusStacks -99`），于是它只活这一个回合；
下一回合起手抽牌恢复正常 —— 判据两侧都问。

### 231.2 `True Grit`：wiki 的括号是「基础;升级」

`Gain (7;9) Block. Exhaust 1 card( at random;)` ⇒ **基础版随机、`+` 版由玩家选**。

* 基础版：`node.selectCards{Random, Count: 1, ToZone: ExhaustPile}`（§195.4 就有的"内核挑"）；
* `+` 版：`node.chooseCards{Then: "Exhaust"}` —— 内核的 `ChoiceThen::Exhaust` 一直存在（Elixir
  那条药水就在用），只是 `chooseCards` 没有把 `"Exhaust"` 这个串映射过去。这一节补上那三行。

判据两版各测一次，并且钉"**正好一张**"（零张和整手牌都是别的 bug）。

### 231.3 `Reaper`：为什么"按掉血回血"必须是一个节点

wiki：`Deal (4;5) damage to ALL enemies. Heal HP equal to unblocked damage. Exhaust.`

参考用 `ResultKey` 把"这一击掉了多少血"传给下一个节点，而本内核**明确不支持 `ResultKey`**。
但 `resolve_damage` 一直返回 `(blocked, health_lost)` —— 所以节点能自己算：
逐目标 `resolve_damage`、把 `health_lost` 加起来、再入队一条 `Heal`。

代价是这一击**立刻生效**（不是入队后结算）。这一点写进了节点文档：格挡/易伤/力量的读取时点都在
`resolve_damage` 内部，与入队版一致；不同的只是它与同一节目里后续节点的相对顺序 ——
而 `Reaper` 需要的恰恰是"先掉血、再按掉的血回血"。

判据给 `enemy_b` 预置 2 点格挡：4 点伤害只掉 2 血，回血只回"真掉的那些"（4 + 2，不是 4 + 4）。
**"unblocked" 这个词就是这条牌的全部难点**，只测无格挡的敌人等于没测。

### 231.4 一条被内容增长顶红的偶发断言（顺手修）

`an_attack_potion_offers_three_definitions_and_creates_only_the_chosen_card` 里原来断言
"手牌里显示的价格 ≠ 印刷价"。这只有在**印刷价非 0** 时才说明"每副本价格在起作用"；池子里现在有
0 费攻击（`body_slam+`），抽到它时 delta 本来就是 `-0`（§161.5：0 费不是错误）⇒ 偶发红。
断言加了 `printed != 0` 的前提，并在注释里写清"那是断言把打折当成了必然打折"，不是回归。

### 231.5 数字

* 单测 **935**（730 core + 110 run + 95 wasm，+3）；四个对拍不变（`FIGHT_DIFF 182/182`、
  `CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）。
* 内容：卡 **111 行**（+4：`True Grit` 2、`Reaper` 2）、状态 **46**（+1 `standard.no_draw`）、
  镜像 **91,752 B**（core 75,760）。
* 矩阵 **427 行**（+5）、扫描到的具名测试 **937**、wiki 对照 **47** 张。
'''

path = ROOT + 'docs/port-plan.md'
text = io.open(path, encoding='utf-8').read()
assert '## §231' not in text, 'already there'
io.open(path, 'w', encoding='utf-8', newline='\n').write(text.rstrip('\n') + '\n' + SECTION)
print('doc_231: appended %d bytes' % len(SECTION))
