"""§225 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §225 消耗审计 + 两张"整手牌"牌（`Second Wind` / `Fiend Fire`），以及一条被参考契约挡回的修法

用户这一节的两个要求：加复制牌/整手牌消耗，并**确认所有消耗相关逻辑是不是统一**。审计先做，结论是
**统一**（下面 225.1），而两张牌落地时撞出一条**语义差**（225.3）。

### 225.1 审计：进消耗堆的三条路径，都跑 `LifecyclePrograms[Exhausted]`

内核里把牌送进 `ExhaustPile` 只有三条路，全部经过同一个落点：

| 路径 | 谁在搬 | `Exhausted` 节目 |
|---|---|---|
| 打出即消耗（`PlayedCardDestinationZone = ExhaustPile`） | 终态回调发 `MoveCardToZone` 请求 → `move_card_for` | ✅ 同一条 |
| 虚无（`TurnEndHandDestinationZone = ExhaustPile`） | 回合末弃手牌 `discard_hand` → `host.card_exhausted` | ✅ |
| 内容驱动（`node.moveCardToZone` 指到消耗堆） | `move_card_for` | ✅ |

`every_way_into_the_exhaust_pile_runs_the_exhausted_program` 把后两条钉成机器判据（用 `sentinel`
的 `Exhausted` 节目 = +2 能量当探针 —— "牌到了那个区"不如"节目跑过"能说明问题）。
`state.move_card` 本身**不发**通知（§220 的教训：那会让状态操作依赖效果队列的深度），所以三条路各自
在自己的"知道内容"的层里发 —— 现在它们是齐的。

### 225.2 新增的两张牌

| 牌 | wiki | 实现 |
|---|---|---|
| `Second Wind` | Exhaust 所有**非攻击**牌，每张 +5 (7) 格挡 | `forEachCardInZone(Hand)` + `conditional(not(card.hasTag.attack))` + `moveCardToZone(iterated → ExhaustPile)` + `gainBlock` |
| `Fiend Fire` | Exhaust 整手牌，每张 7 (10) 伤害，自身 Exhaust | `forEachCardInZone(Hand)` + `moveCardToZone` + `dealDamage` |

第二张不需要新能力；第一张需要"**这张迭代中的牌有什么 tag**"。`event.bool: card.hasTag.*` 此前只读
`ctx.event_flags`（只有触发器会填），所以 §225 A 让它**在迭代上下文里也成立**：
`start_iteration` 绑卡时把该定义 tag 位写进 `event_flags`，并**存进帧**（续延重建上下文时要拿回来）。
位表本身从 `host::card_tag_flags` 挪到 `Content::card_tag_bits` —— 一份定义，宿主与 exec 共用。

### 225.3 撞到的语义差：打出的牌在节目期间**还在手牌里**

`Second Wind` 第一次跑出来给 **10** 格挡而不是 5：循环把 `Second Wind` **自己**也算进了"整手牌"。
原因是参考实现里打出的牌要到 `onTerminal` 才落区（`play::tests` 与 `CARD_DIFF` 的
`archive_the_evidence` **都钉着这条**）。

我先试了"让快照跳过正在结算的那张牌"（`ExecContext::resolving_card` + 帧字段 + `forEachCardInZone`
跳一格），逻辑自洽、`Second Wind` 立刻变 5 —— 但**既有测试当场红**：

```text
play::tests::a_play_advances_both_counters_and_the_two_faces_differ_by_exactly_one
  assertion failed: 节目里的 forEachCardInZone → moveCardToZone 把它自己搬去了 ExhaustPile
```

也就是说：**"打出的牌还算手牌"是参考契约的一部分**，改它等于改哈希契约。于是按纪律退回：
**跟参考走、把差异写成声明**（`sts-wiki-gap.md` §G.2 + 判据注释 + 矩阵的 `DeclaredDeviation`）：

* `Second Wind` 给 10（自算一张），`Fiend Fire` 打 21（自算一张）；
* 判据断言**我们的数字**，并在失败信息里点名"这是声明的偏差"，不假装等于 wiki。

### 225.4 复制牌（`Dual Wield`）为什么没做

它要"选中一张攻击/Power 牌，**复制**它"。内核的 `node.createCardInstance` 只认**固定的定义 id**，
而"复制选中的那张"需要 `ResultKey`（§"没有 outcome slot"那条**明确不支持**），或者一个新的
"复制当前选中的卡"节点。这是**新载体**，不是内容能绕的：所以这一节没做，留成下一节的第一件事
（与 §219 的做法一致：先证明现有载体表达不了，再决定加什么）。

### 225.5 数字

* **21/21 闸门绿**，单测 **915**（712 core + 110 run + 93 wasm，+3 条）；四个对拍不变。
* 镜像 **85,460 B**（core 71,840）；卡 **77 行**（+4：两张牌各带升级行）。
* 矩阵 **391 行**、具名测试 **917**；`second_wind` / `fiend_fire` 的 `DeclaredDeviation` 有内容。
'''

port = io.open(ROOT + 'docs/port-plan.md', encoding='utf-8').read()
assert '## §225' not in port
io.open(ROOT + 'docs/port-plan.md', 'a', encoding='utf-8', newline='\n').write(SECTION)
print('port-plan §225 appended')

readme = io.open(ROOT + 'README.md', encoding='utf-8').read()
for old, new in [
    ('（§1–§224，每一轮都留数字、记下被推翻的结论）', '（§1–§225，每一轮都留数字、记下被推翻的结论）'),
    ('编译成 84,588 B 的 `rdcf` 镜像（core 镜像 71,188 B）', '编译成 85,460 B 的 `rdcf` 镜像（core 镜像 71,840 B）'),
]:
    assert readme.count(old) == 1, old[:40]
    readme = readme.replace(old, new)
io.open(ROOT + 'README.md', 'w', encoding='utf-8', newline='').write(readme)
print('README updated')
