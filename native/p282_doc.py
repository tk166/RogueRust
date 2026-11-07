"""§282 文档：port-plan + 缺口表（Snecko 的连招规则偏差）+ README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
EVENTS = 'D:/Vibe/sts-tui/docs/event-gaps.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §282 `Confusion` + Snecko：随机价格第一次有**内容**消费者

§281 把 `randomInt` / 统一随机入口做进了内核，但**没有内容用它**（StS 没有随机伤害值）。
这一节补上它真正的消费者：`Snecko` 的 **Perplexing Glare** 挂 *Confused*，而 *Confused*
就是"**每次抽牌**把这张牌的价格重掷成 0..3" —— 用户说的"每回合重掷"就在这条规则里。

### 282.1 wiki 事实（两处独立来源）

`Slay the Spire` 的 `Snecko`（Act 2 **普通**敌人，**独自**出现）：

| 项 | 值 |
|---|---|
| HP | **114-120**（A7+ 120-125） |
| Perplexing Glare | **第 1 回合必用**，对玩家挂 *Confused* |
| Bite | 15（A2+ 18）伤害，**60%** |
| Tail Whip | 8（A2+ 10）伤害 + 2 层易伤；**A17+ 再加 2 层虚弱**，**40%** |
| 连招 | "Bite 不会连用三次"（**偏差**，见 282.6） |

*Confused*：`Whenever you draw a card, randomize its cost.` —— **四档等概率**（0/1/2/3 各 25%），
不叠加，整场有效。三条豁免与两条边界（wiki `Snecko Eye` 的 Notes）：
* **只有从抽牌堆抽进手牌**才重掷（`Seek` 那种"放入手牌"不算）；
* **X 费牌不受影响**；
* 重掷会**覆盖**此前一切费用改动（`Blood for Blood` 之类）；
* **0 费的普通牌会被变贵**（表：0 费 → 75% 变贵），而**不可打出的牌**不动。

### 282.2 ★ 缺口真正在哪：抽牌有**两条**路

第一版把钩子装在 `exec::draw_for` 里 —— 那只是 `node.drawCards` / 药水请求的路径。
**回合开始的 5 张**走的是另一条：`turn.rs::draw_for_turn_start` →
`CombatState::draw_cards_with_reshuffle`。于是"有 Confusion 时回合开始的牌不重掷"，
而屏幕上一切正常（价格就是印刷价）—— 这正是这个项目反复栽的那个形状（§277 的"一处决策、
五个消费者"，§280 的"三个 walker 一个洞"）。

修法：把重掷做成 **`pub fn exec::confuse_drawn_card`**，由**两个**调用点各调一次：

| 路径 | 调用点 |
|---|---|
| 节点/药水的抽牌 | `exec::draw_for`（抽到之后、`Drawn` 节目之前） |
| 回合开始的 5 张 | `turn::draw_for_turn_start`（同位置） |

★ 判据也因此必须**走回合机**：负控第 ④ 条（把 `turn.rs` 那处调用删掉）一开始**没红** ——
因为判据当时自己抽 5 张再自己调重掷，把守卫装到了切口的**下游**。改成
`end_current_turn_and_start_next` 推到英雄回合、让回合机自己抽牌之后，删掉那处调用立刻红。

### 282.3 内容与内核的分工

* **内容**：`standard.confusion`（**没有**修饰器、没有触发器 —— 它是个**开关**，规则全在内核，
  与 §231 的 `standard.no_draw` 同一类）+ `snecko` 怪 + 三个动作 + `enc_snecko` + Act 2 的
  `Weak2` 池。
* **内核**：`exec::confuse_drawn_card` —— 读状态 id、按 **tag** 判两条豁免
  （`x_cost` / `unplayable`）、`draw_in_range(0,3)`、写绝对覆盖计数器。
* **显示**：§281 之后 `hand_costs` 会先读绝对覆盖，于是屏幕上就是掷出来的价
  （"显示 = 实收"）。

⚠️ 两条豁免只能按 **tag** 判，不能按"印刷价 <= 0"：0 费的**普通**牌会被 Confusion 变贵，
那条捷径会让它们免疫 —— 一条静默的行为偏差。

⚠️ `standard.confusion` 还必须进 `status_catalog::has_behaviour` 的清单。漏了会红 ——
`the_status_catalogue_is_honest` 就是为"内容声明了一条内核没规则的状态"写的，这次它当场抓到。

### 282.4 `TurnHost` 拿内容的那一格

回合机是泛型 `H: TurnHost`，而 trait 上没有 content（豁免要按 tag 判）。加了**默认方法**
`fn confusion_content(&self) -> Option<&Content>`（返回 `None` ⇒ 不重掷），由 `Host` 覆写成
真内容。`NullHost`（标准包路径）保持 `None`。"没覆写"这件事**有判据**（282.5 的第 2 条）。

### 282.5 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `confusion_randomizes_the_cost_of_every_drawn_card` | **有/无两侧**（无 ⇒ 印刷价；有 ⇒ 0..=3 且真的变过）、**不可打出的牌不重掷**、同种子同价格、换种子不同。**走回合机**（推到英雄回合），所以 `turn.rs` 那处钩子删掉会红 |
| `the_status_catalogue_is_honest` | `standard.confusion` 有规则（`has_behaviour`） |
| 内容门 `[2]`/`[2b]`/`[7d]` | Snecko 的血量（A7 120）、三个动作的 A 档（Bite 18@A2、Tail Whip 10@A2 + Weak@A17、Glare 无 A 档）、遭遇清单、Act 2 池 |
| `act_two_fights_act_two_enemies` | act 2 的怪白名单加 `snecko` |

**负控**（`native/p282_negative.py`，改内核源码 → 跑判据 → 还原）：
① 钩子写成常数 1；② 去掉 `unplayable` 豁免；③ 去掉状态判据；④ **删掉 `turn.rs` 的那处调用**
—— 四条全 RED ✓（第 ④ 条是这一节最重要的一条：它证明"两条路径都接了"）。

### 282.6 已知偏差（写进 `docs/sts-wiki-gap.md`）

* **"Bite 不会连用三次"**没做：它要记**最近两次**招式，而 `selfHasCounter(last_move)` 只记住
  上一条。今天按加权 `Choice`（60/40）实现，所以理论上可能连出三次 Bite。
* **`Snecko Eye`**（Boss 遗物：开局自挂 Confused + 每回合多抽 2 张）没做 —— 它现在**能**做了
  （状态与抽牌数都有载体），但那是遗物那一节的一条，不在本节。
* **`Orange Pellets` 清 Confused 后"已经重掷过的牌保留新价"**：我们的实现天然如此
  （价格写在副本的计数器上，清状态不会回滚），与 wiki 一致，但没有专门判据。

### 282.7 账

镜像 **153,692 B**（core 119,748 B）；怪 **49 → 50**、遭遇 **43 → 44**、状态 **126 → 127**、
动作 **135 → 138**；`rd-core` 797 / `rd-run` 152 / `rd-wasm` **127**；
`STS_CONTENT PASS`；七道页面门 + `ACT1_SLICE` 全过；21/21。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '### G. ★ 基础值偏差'
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.4 Snecko（§282）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| Bite 连招 | "will not use Bite three times in a row" | 加权 `Choice` 60/40，**可能连三次** | **偏差** —— 要记"最近两次招式"，而 `selfHasCounter(last_move)` 只记上一条 |
| `Snecko Eye` 遗物 | 开局自挂 Confused + 每回合多抽 2 | **没做**（机制已就绪，属遗物那一节） | 缺 |
| Confused 的清状态语义 | `Orange Pellets` 清掉后，已重掷的牌保留新价 | 天然一致（价格在副本计数器上） | 一致，无专门判据 |

### G. ★ 基础值偏差''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§281）', '（主计划 §1–§282）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§282 doc + gap row + README')


main()
