"""§283 文档：port-plan + 缺口表（偏差更正）+ README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §283 记"最近两次招式" + `Snecko Eye`：两件都**不需要内核改动**

§282 留了两条尾巴：`Bite` 不连三次（要记最近**两次**招式）与 `Snecko Eye` 遗物。
这一节两件都做完，而**内核一行没改** —— 两件都是内容 + 已有的载体。

### 283.1 "Bite 不会连用三次"：`prev_move` 是内容的一个计数器

内核的 `intent.selfHasCounter` 只读**一个**计数器，而"连三次"是"最近**两次**都是 Bite"。
解法不用改内核：每个动作多写一格 ——

```
prev_move = combatantCounter(last_move)     // 先把上一次抄进来
last_move = <本招的索引>                     // 再写自己
```

`node.setCombatantCounter` 的 `Amount` 本来就是**表达式**，所以"抄一格"不需要新节点。
然后一条规则压在选择之上：

```
prev_move == 2 AND last_move == 2  ⇒  强制 Tail Whip   （Bite 的索引是 2，优先级 95）
```

判据（`snecko_never_bites_three_times_in_a_row`）**两侧**：
* 反面：只有上一次是 Bite ⇒ **仍然可能**出 Bite（否则"永远不出 Bite"也会全绿，
  而那会让 Snecko 变成只会 Tail Whip 的怪）；
* 正面：最近两次都是 Bite ⇒ 扫 10 个轮次，一次 Bite 都不许出现。

### 283.2 `Snecko Eye`：一条状态带两条规则

wiki："At the start of your turn, draw 2 additional cards. Start each combat Confused."

做法与 §267 的"零基建"同一路：遗物只做**开战挂一条状态**，两条规则都在那条状态的
`TurnStarted` 触发器里：

```
standard.snecko_eye （TurnStarted）
    applyStatus(standard.confusion, 1)  @ sel.source
    drawCards 2                         @ sel.source
```

`rd-run` 里只多一行 `"snecko_eye" => StartCombatStatus("standard.snecko_eye", 1)`。
判据两侧：带 Eye ⇒ 手牌 7（5 + 2）且状态里有 `standard.confusion`；不带 ⇒ 5 张、没有。

### 283.3 ★ 三个"静默不落地"的坑（都在这一节踩到）

1. **`sel.eventTarget` 在 `TurnStarted` 里是空的**。第一版把 `applyStatus` 的目标写成
   `sel.eventTarget`（从伤害那条抄的），于是"给自己挂状态"解析出**空集**、什么都不做 ——
   而同一段里的 `drawCards`（用 `sel.source`）成功了，所以症状是"抽了 7 张但没有 Confused"。
   触发器里指自己一律用 **`sel.source`**（`standard.rage` / `spore_cloud` 都是这么写的）。
2. **`UsesStacks: false` 的状态收不下 `applyStatus(stacks: 1)`**。§282 声明 `standard.confusion`
   时写了 `UsesStacks: false`（想表达"不叠加"），而 wiki 的 "Does not stack" 讲的是**上限 1**。
   与 §231 的 `standard.no_draw`（同为开关，也是 `UsesStacks: true`）对齐之后才落地。
3. **意图是闭集**：我写了 `Intent.Kind: "AttackDebuff"`，而内核只有
   `Attack/Defend/Buff/Debuff/Special` —— `select_action` 报 `UnknownIntentKind`，
   在**意图选择**（不是攻击）时炸。按主效果归 `Attack`。

★ 还有一个**方法论**上的坑：我的内容脚本用了 `if not any(...)` 守卫来做到幂等，
于是第二次运行时整块被跳过，**我改的内容根本没写进去**。表现是"改了、编译了、判据还是红"，
而构建产物里的旧结构（还带 `conditional`）一直没变。修正后我把那一段改成直接重写整块。

### 283.4 已知偏差（`docs/sts-wiki-gap.md` F.4 已更新）

* **`Confused` 每回合都挂一次**（`Confusion` 不叠加，重复挂无害）。wiki 的
  `Orange Pellets` 清掉之后**不会再回来**，而我们下一回合会再挂上。
  原本想用"首回合才挂"（计数器判第一次 `TurnStarted`），但状态触发器的程序里
  `combatantCounter(sel.source)` 读到的是 0（触发帧的 source 不是状态拥有者），
  条件恒真 —— 那比"每回合都挂"更糟（看起来像"只在首回合"，实际不受控）。所以选择
  显式的偏差，而不是一个假装在判的条件。
* `Snecko Eye` 的"每回合多抽 2"用 `TurnStarted` 触发器里的 `drawCards`，**不是**
  `TurnStartDraw` 修饰器。两者可观察行为一致（都是回合开始多 2 张），但修饰器那条路能让
  "抽牌上限"参与计算 —— 今天的 `max_hand_size` 是 `i32::MAX`，所以没有差别。

### 283.5 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `snecko_never_bites_three_times_in_a_row` | 两侧（单次 Bite 仍可能出 Bite；两次 Bite ⇒ 只能 Tail Whip，扫 10 轮） |
| `snecko_eye_draws_two_more_and_confuses_at_the_start` | 两侧（7 张 + Confused / 5 张 + 无） |
| 内容门 | 状态计数 128、遗物实现清单含 `snecko_eye`、触发器材清单、动作意图闭集、A 档 |

**负控**（`native/p283_negative.py`）：① 删掉"连两次 Bite"那条规则；② 删掉遗物的映射 ——
两条全 RED ✓。

### 283.6 账

镜像 **153,964 B**（core 120,008 → 略变）；状态 **128**、遗物 **116**（+`snecko_eye`）；
`rd-core` 797 / `rd-run` 152 / `rd-wasm` **130**；`STS_CONTENT PASS`；
七道页面门 + `ACT1_SLICE` 全过；21/21。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    old = '''| Bite 连招 | "will not use Bite three times in a row" | 加权 `Choice` 60/40，**可能连三次** | **偏差** —— 要记"最近两次招式"，而 `selfHasCounter(last_move)` 只记上一条 |
| `Snecko Eye` 遗物 | 开局自挂 Confused + 每回合多抽 2 | **没做**（机制已就绪，属遗物那一节） | 缺 |'''
    new = '''| Bite 连招 | "will not use Bite three times in a row" | **§283 已做**：内容多记一格 `prev_move`（`prev_move = last_move`），规则 `prev==Bite && last==Bite ⇒ Tail Whip` | 一致 |
| `Snecko Eye` 遗物 | 开局自挂 Confused + 每回合多抽 2 | **§283 已做**（`standard.snecko_eye` 的 `TurnStarted` 触发器） | 一致 |
| Confused 的"何时挂" | 开局挂一次；`Orange Pellets` 清掉后不再回来 | **每回合都挂一次**（不叠加，所以只有"清掉后会回来"这一处偏差） | **偏差**：首回合判定写在触发器里读不到 source 计数器（恒 0），与其假装在判，不如显式偏差 |
| `Snecko Eye` 的多抽 | `TurnStartDraw` 修饰器 | `TurnStarted` 触发器里的 `drawCards 2` | 可观察等价（`max_hand_size` 是 `i32::MAX`，上限不参与） |'''
    assert g.count(old) == 1
    g = g.replace(old, new)
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§282）', '（主计划 §1–§283）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§283 doc + gap rows + README')


main()
