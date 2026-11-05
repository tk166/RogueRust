"""§216 docs: port-plan section + README/§ counters."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §216 第六轮审阅的三条 P1：`Slow` 的时间语义、`Nom Nom` 的时间变量、`reset_in_place` 的漏字段

第六轮增量审阅（`docs/vibe/Review_74423a89_5e4dbef0.md`）指了三条 P1。三条**全部成立**，逐条回源码
复现过（复核写在那个文件末尾的第 7 节）。这一节按"**先让测试红**"的顺序做，每条都留了负控。

### 216.1 `Slow`：计数每回合归零，而且不由层数承担

wiki（`slay-the-spire.fandom.com/wiki/Slow`）：*"For every card you have played **this turn** …
**Slow resets at end of turn**; enemy does NOT carry over stacks."*

§198 把它做成了"每打一张牌 +1 层、永不衰减" ⇒ 第 2 回合再打 5 张就是 10 层（×200%）。而且
`giant_head` 的开场 `Stacks=1` 在"层数=倍率"的模型下意味着**未出牌就 +10%**。

**为什么不能"回合末清零"**（这是设计上的硬约束，不是偷懒）：

* `apply_status` 的 `stacks == 0` **不算一次施加**（`exec.rs:4068`）；
* `modifyStatusStacks` 减到 0 会**删掉实例**（`exec.rs:2821`，照参考 `StatusEffects.cs:830-838`）。

⇒ "Slow 在身上、计数为 0"在现有节点集里表达不出来；实例一删，`CardPlayed` 触发器就再也不响。
而内核**已经有**这个计数：`state.cards_played_this_turn`（`play.rs:855` 每出一张 +1，`turn.rs:897`
回合末清零）。所以加**第四种修饰器运算**：

```text
Operation::ScalePercentPerCardPlayedThisTurn   current * (100 + magnitude * cards_played_this_turn) / 100
```

* `Candidate` 多一个 `cards_played_this_turn`，由 `fold` 从新参数 `turn_cards` 灌进去；
* 伤害管线的两处调用点喂 `ctx.state.cards_played_this_turn`（`exec.rs:1192/1213`）；
* 格挡 / 回合开始抽牌 / 补能那三条管线喂 `NO_TURN_CARDS`（-1），`fold` 见到"要牌数却传了 -1"
  就 **`Err(ExecError::Modifier)`** —— 挂错管线是内容错误，必须响亮，不能安静地恒等；
* `status_bind::ModifierOp` 加对应拼写（镜像里运算就是字符串，写错一个词就是另一种语义）；
* 内容：`standard.slow` 的运算换成它、**删掉 `CardPlayed` 触发器**，`giant_head` 仍装 1 层
  —— 那 1 层现在只是"这个能力在身上"。

### 216.2 `Nom Nom`：`turnNumber` 是轮内序号，不是轮次

wiki：*"Deals 5×N damage. N = Current turn, divided by two (rounded up)."*

内核两个变量（`expr.rs:540`）：`turnNumber → state.current_turn`（**一轮内的行动者序号**，`turn.rs:970`
绕回时置 1）、`roundNumber → state.current_round`。单怪场景里 Maw 出手时 `current_turn` **恒为 2**
⇒ `ceil(2/2) = 1`，**永远 1 击**；双怪场景恒为 3 ⇒ 恒 2 击。

§212 那条测试直接写 `session.state.current_turn = turn`（`lib.rs:4885`）—— 它验证的值在真实玩法里
取不到。**这是这一轮最值得记的教训：不是公式抄错，是测试伪造了一个不会增长的量。**

修法两件：

1. 内容换 `roundNumber`；测试改成**真的推进轮次**（`Session::exec(EndOneTurn)` 走回合机，
   每轮断言 `current_round == round`），仍然钉 `[5, 5, 10, 10, 15, 15]`。
2. **内容门新增 `INV_TIME_VARIABLES`**：穷尽"每个程序读哪一个时间变量"，两个方向都查
   （表里声明的必须真出现、程序里出现的必须在表里）。为什么非加不可：`INV_ACTIONS` 把这条动作
   钉成 `("repeat", ("expr","divide"), "damage", 5, "event")` —— `turnNumber` 与 `roundNumber`
   在**事实**层面一模一样，钉事实永远看不见这个错。

### 216.3 `reset_in_place`：三个后加的标量

`reset_scalars` 只重置 12 个标量，`vacated_seat` / `gold_carried_away` / `ascension` 不在其中。
生产路径上 `rd-wasm` 每场 `Box::new(CombatState::new(..))`，所以玩家今天不受影响；但
`apply_fight_outcome` 是 `adjust_gold(-gold_carried_away)`（`run.rs:3491`）⇒ 真被复用时**每场重复扣**
同一笔被偷的金币。

而 `reset_in_place_matches_new_field_for_field` 比的是 `canonical_text`，这三个字段**都不在
`snapshot.rs` 里** ⇒ 脏着也"逐字段等价"。**名字里的 "field for field" 是假的**，而且会继续放过
下一个新字段。所以：

* 三个字段进 `reset_scalars`；
* 新增 `reset_in_place_also_clears_the_three_scalars_the_hash_text_cannot_see`：先污染、再 reset、
  再**逐字段**比（并成对比"污染确实生效"）；
* **连带发现**：`build_fight_from_content` 里的那段 reset 会把**调用方设过的难度**清成 0
  —— 两个 Looter 的 A2 测试当场红。修法是分工：`reset_in_place` 严格等于 `new()`，
  **建战斗**负责把等级接回来（`let ascension = state.ascension(); reset; set_ascension(ascension);`），
  并加 `building_a_fight_keeps_the_ascension_but_not_the_last_fights_gold` 钉住这条分工
  （难度保留、上一场的金币与空席位不保留）。

### 216.4 判据与负控（五条，每条都先红过）

| 判据 | 负控（改哪个字） | 红在哪 |
|---|---|---|
| `slow_counts_the_cards_played_this_turn_and_starts_over_each_turn` | 内容退回 `ScalePercentPerStack` | `no cards played: … left: 11 right: 10`（开场 +10%） |
| `scale_percent_per_card_played_reads_the_turn_count_not_the_stacks` | 实现读 `candidate.stacks` | `0 cards / 5 stacks: … left: 15 right: 10` |
| `nom_nom_hits_five_damage_ceil_round_over_two_times` | 内容退回 `turnNumber` | `left: [5,5,5,5,5,5] right: [5,5,10,10,15,15]`（**恒 1 击**）+ 内容门 `time variables ['turnNumber'], inventory says ['roundNumber']` |
| `reset_in_place_also_clears_the_three_scalars_…` | 删掉那三行 | `left: Some(3) right: None` |
| `building_a_fight_keeps_the_ascension_but_not_the_last_fights_gold` | 删掉"接回难度"两行 | `left: 0 right: 9` |

Slow 的那条测试是**真出牌、真结束回合**：0 张 → 10 点；真打 5 张 `defend` → 15 点；`start/end_current_turn`
之后计数归零 → 又回到 10 点。（第一版靶子只有 20 血，第二笔被"最多掉到 0"截断成 10 —— 和 §212 的
"英雄只有 400 血"是同一个坑，注释里写下来了。）

### 216.5 数字

* **21/21 闸门绿**，单测 **904**（704 core + 107 run + 93 wasm，比 §215 多 4 条）；四条对拍不变。
* 镜像 **80,484 B**（core 68,048）—— 比 §215 **小了 36 字节**：删掉的那个 `CardPlayed` 触发器
  比新运算名多占的字节还多。
* 覆盖矩阵 360 行不变，扫到具名测试 893 → **897**。
* `docs/sts-wiki-gap.md` §G 里那条过时的 `maw.*`"wiki 无此页（404）"已删（§212 起就不成立），
  并写明 Slow 剩下的**一处**偏差：我们只区分"直接伤害"，wiki 限定"攻击牌造成的伤害"
  —— 要精确到卡牌标签需要 `RestrictSourceCardTag` 进镜像格式（`status_bind` 目前对它**响亮拒绝**）。
'''

port = io.open(ROOT + 'docs/port-plan.md', encoding='utf-8').read()
assert '## §216' not in port
io.open(ROOT + 'docs/port-plan.md', 'a', encoding='utf-8', newline='\n').write(SECTION)
print('port-plan §216 appended')

readme = io.open(ROOT + 'README.md', encoding='utf-8').read()
pairs = [
    ('（§1–§215，每一轮都留数字、记下被推翻的结论）', '（§1–§216，每一轮都留数字、记下被推翻的结论）'),
    ('编译成 80,520 B 的 `rdcf` 镜像（core 镜像 68,088 B）', '编译成 80,484 B 的 `rdcf` 镜像（core 镜像 68,048 B）'),
]
for old, new in pairs:
    assert readme.count(old) == 1, old[:40]
    readme = readme.replace(old, new)
io.open(ROOT + 'README.md', 'w', encoding='utf-8', newline='').write(readme)
print('README updated')
