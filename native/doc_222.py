"""§222 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §222 基础项：给 §221 的新内容补具名测试，并把两条 §218 偏差**查清为什么不能在这一节修**

这一节的起点是用户点名的三件事：§218 剩的两条声明偏差（`apparition` 的 Ethereal/升级轴、`buffer` 的
版本基线）与"只有 harness 覆盖"那 111 行里的重点项。结果两件事走了相反的方向 —— **测试补上了，
两条内容修正被闸门挡回来了，而且挡回来的理由值得单独写一节**。

### 222.1 补上的判据（这才是这一节真正落地的东西）

| 判据 | 覆盖 |
|---|---|
| `the_ten_cards_added_in_221_do_what_the_wiki_says` | §221 那 10 张牌，一张表：每行"打哪张、读哪一格、应当是多少" |
| `the_two_event_curses_behave_as_their_pages_say` | `doubt` / `writhe`（含下面 222.3 那条顺序偏差） |

十张牌之前的状态是：内容门钉数字、`CARD_DIFF` 跑程序文本，**没有任何东西断言"这张牌打出来真的做了
那件事"**。现在每张牌读**一个**可观察量（敌人血量 / 格挡 / 手牌数 / 抽牌堆 / 弃牌堆 / 敌人状态）——
读整份状态会让"读错格子"也看起来正确。写这一条时踩了三个小坑，都留在注释里：

* `arena()` 的**抽牌堆是空的** ⇒ "抽 1 张"读出来是 0（不是错误，是参考的"两堆都空就抽不满"）；
* 伤害**钳在 0** ⇒ `bludgeon` 打 20 血的目标读到 0，不是 -12；
* **Ethereal 管的是"回合末还在手里"**，与"打出去"无关 —— 第一版把 `ghostly_armor` 断言成"留在手里"。

### 222.2 `doubt` 抓到的顺序偏差（新发现，已声明）

`doubt`（wiki："At the end of your turn, gain 1 Weak"）的节目**确实执行**（判据先直接调
`try_hand_turn_end_lifecycle` 看到 Weak = 1），但走**完整回合末**时它立刻消失：
我们的 `standard.weak` 衰减是一条 `TurnEnded` **触发器**（第 ③ 步），而卡牌生命周期节目在第 ① 步
—— 同一次回合末里刚上的 Weak 当场被扣掉。参考把 Weak 的衰减放在 `decrease_timed_statuses`，与卡
程序的关系不同，所以原版里 Doubt 的 Weak 会留到下一回合。

写进 `docs/sts-wiki-gap.md` §G.2 偏差表，矩阵的 `DeclaredDeviation` 列能查到。
判据因此断言"被吃掉"—— **不假装它留着**，也不为了让它留着去动回合末的处理器顺序（那会同时移动
Burn 等所有生命周期节目的时点）。

### 222.3 为什么 `apparition` / `buffer` **没有**在这一节修（三件事，按代价排序）

**① 我先把 wasm 的知识补上：镜像在编译期嵌进 `.wasm`。**
`rd-wasm/src/lib.rs` 是 `include_bytes!("…content.sts.rdcf")` ⇒ **改内容必须重编 wasm**，否则浏览器
闸门跑的是旧镜像。这一节前四次隔离实验（回退 buffer / 回退 apparition / 回退遗物）全都无效，
就是因为只重编了内容、没重编 wasm —— 每次读到的是"旧镜像的失败"。

**② `bag_of_marbles` 是载体不匹配，不是抄错。**
wiki："At the start of each combat, apply 1 Vulnerable to **ALL enemies**"。我照着
`oddly_smooth_stone` 写成 `StartCombatStatus`，但 `combat_bonus` 的状态只加在**英雄**身上
（`apply_combat_bonus` 只认 `hero`）⇒ 英雄自己变易伤，Boss 战直接打不过。它需要一个
"开战给敌方挂状态"的载体，属于单独的活。

**③ 真正挡住 `apparition` / `buffer` 的是垂直切片，而且这是切片的问题。**
把两处按 wiki 修好（`apparition` 基础带 Ethereal、升级去掉 Ethereal、两层都 1 层无形；
`buffer` → Power / Rare / 2 费）之后，`ACT1_SLICE` 的 **24 个固定种子没有一个能打赢 Boss**
（`seed=null`，多数停在 `hpAfter 0`）。切片的注释里其实已经写着这件事：

> *"It is a **list**, not a lucky number: adding content changes the drop table, hence the route,
> hence which fights the driver wins."*

也就是说：**内容一动，切片的运气就变**。修这两条会让 Act 1 的掉落/路线整体挪位，而驱动脚本
（"attacks first, block never"）没有能力处理"Ethereal 的 Apparition"或"2 费的 Buffer"。

所以这一节的选择是：**回退内容修正、保留偏差声明、把边界写在代码旁边**
（`rd-run` 的 `relic_effect` 上方与 `sts_content_check` 的 `cards.upgrades` 各有一段）。
下一步如果要修，正确的顺序是：**先让切片驱动学会处理这两类牌**（它该像玩家一样：有 Ethereal 就
本回合打掉、能量紧就不打 2 费 Power），再改内容 —— 反过来做就是拿闸门去迁就内容。

### 222.4 数字

* **21/21 闸门绿**，单测 **913**（710 core + 110 run + 93 wasm，比 §221 多 3 条）；四条对拍不变。
* 内容**与 §221 相同**（卡 73 行 / 遗物 15 / 事件 11；镜像 84,592 B）—— 这一节的产出是判据与账，
  不是新内容。
* 矩阵 **387 行**、具名测试 **914**；`doubt` 的偏差行现在有内容（`DeclaredDeviation` 不再是 `—`）。
'''

port = io.open(ROOT + 'docs/port-plan.md', encoding='utf-8').read()
assert '## §222' not in port
io.open(ROOT + 'docs/port-plan.md', 'a', encoding='utf-8', newline='\n').write(SECTION)
print('port-plan §222 appended')

readme = io.open(ROOT + 'README.md', encoding='utf-8').read()
old = '（§1–§221，每一轮都留数字、记下被推翻的结论）'
new = '（§1–§222，每一轮都留数字、记下被推翻的结论）'
assert readme.count(old) == 1
io.open(ROOT + 'README.md', 'w', encoding='utf-8', newline='').write(readme.replace(old, new))
print('README updated')
