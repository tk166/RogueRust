"""§219 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §219 载体补全：`Exhaust` 是落区（而且两条牌一直拼错），`Dark Shackles` 一直是 fault 的

§218 结尾说剩下 8 条偏差里 4 条属"没有载体"。这一节去补载体，结果**一半的"缺载体"是假的** ——
载体一直在，只是**写错了**，而且没有任何测试打过那些牌。

### 219.1 `Exhaust` 不是 tag，是 `PlayedCardDestinationZone`

内核把"打出后去哪"放在卡定义的一格里，`play.rs:1931` 用 `zone_from_wire_name` 解析那串**枚举名**：
`DrawPile` / `Hand` / `DiscardPile` / **`ExhaustPile`** / `BanishedPile` / `QueuePile` / `SetAsidePile`。
别的串一律 `IrError::UnknownKind`。

`bandage_up` 与 `dark_shackles` 写的是 **`"Exhaust"`** ⇒ **这两张牌一打就抛**。为什么没人发现：

* C# oracle 那一层只 author scenario 包（`card_specs.json` 里是 `paper_cut` 那一批），sts 的牌不在其中；
* rd-wasm 的测试也从来没有把这两张牌打出去过；
* §218 的卡牌 wiki 对照把 wiki 的 `Exhaust` 关键字**当成 tag** 去比，于是它报的是"缺 exhaust tag"
  —— 而我当时把它读成"没有载体"，直接写进了偏差表。**两把尺都偏了一格，正好互相掩护。**

修法三件：

1. 两处 `"Exhaust"` → `"ExhaustPile"`；
2. 内容门新增 `check_card_zones`：两个落区字段的值必须是上表那七个名字之一
   （`ok("card zones", "N zone cells x 7 known names")`）；
3. 卡牌 wiki 的 `Exhaust` 改成比**落区**而不是 tag（`KEYWORD_TAGS` 里把 `Exhaust` 删掉）。

`Cover`：`slimed` 的"不可出"也是同一条偏差的产物 —— 载体有了，它就该按 wiki 做"1 费、可出、Exhaust"。

### 219.2 `Dark Shackles`：负层数是被拒绝的，所以它一直是 `Effect(Modifier)`

原来它给敌人施 `standard.strength` **-9 层**，而 `apply_status` 对负层数**响亮拒绝**
（`exec.rs:4063`，抄参考 `StatusEffects.cs:55-62`）⇒ 这张牌**打出即 fault**。
wiki 的语义是 *"Enemy loses 9 (15) Strength **this turn**"*，所以形状应当是"立刻降 + 回合末还"。

内核不需要改：`lose_strength` 已经是"回合末把层数**减**回力量"的载体（§158 给 Flex Potion 用的），
这一节加它的**镜像** `standard.regain_strength` —— 同一形状、`Delta` 用 `add` 而不是 `subtract`、
末了自己清掉自己。`dark_shackles` 于是变成：

```text
modifyStatusStacks(strength, -9)          ← 立刻降（钳在 0，参考行为 `:860-865`）
applyStatus(regain_strength, 9)           ← 回合末还回 9 层
```

⚠️ 钳在 0 是**参考的行为**（不能让力量变负），所以对"只有 5 层力量的敌人"实际只降 5 ——
写进 `card_wiki_inventory` 的说明里。判据里也因此先给敌人 10 层力量：不然"降 9"与"钳到 0"
在数值上分不开（第一版就是这么写错的，报出来是 `left: 0 right: 1`）。

### 219.3 判据与负控

`exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable`：三张牌各自打出后
①进消耗堆（按**定义名**比，不是实例 id）②效果真的发生了（`bandage_up` 治疗 4、`slimed` 花 1 点能量、
`dark_shackles` 力量 10→1、回合末回 10）。

两条负控：

| 负控 | 红在哪 |
|---|---|
| `bandage_up` 落区改回 `"Exhaust"` | 内容门：`wiki 有 Exhaust，内容的落区是 'Exhaust'`；内核：`must be playable … Effect(Ir(UnknownKind))` |
| `regain_strength` 的 `add` 改回 `subtract` | `"this turn": the 9 points come back  left: 0  right: 10` |

### 219.4 数字

* **21/21 闸门绿**，单测 **907**（706 core + 108 run + 93 wasm，比 §218 多 1 条）；四条对拍不变。
* 镜像 **80,956 B**（core 68,396）：+308 B（新状态 + `dark_shackles` 的两步程序 + `slimed` 落区）。
* 矩阵 **361 行**（状态 43 → 44）、扫到具名测试 **909**。
* 状态目录的诚实性闸门（`the_status_catalogue_is_honest`）把 `regain_strength` 逼进了
  `status_catalog::is_declared_inert` 的清单 —— 它要求"内容里的每个状态要么有内核规则、
  要么在名单上"，而 `regain_strength` 的规则在**内容触发器**里（与 `lose_strength` 同一条）。

### 219.5 还剩（真正缺载体的两条）

* `void` 的"抽到时失去 1 能量"需要 `LifecyclePrograms` 增加一个 `Drawn` 触发点
  （参考的 `CardLifecycleTrigger` 只有 `TurnEndInHand` 一个成员，这会是**我们自己的扩展**，
  与 §198 的 `ScalePercentPerStack` 同类）；
* `sentinel` 的"被消耗时 +2 能量"需要 `Exhausted` 触发点（同上）。
* `apparition` 的 Ethereal/升级轴仍按声明处理（升级改成"给 2 层无形"是本内容的简化）。
'''

port = io.open(ROOT + 'docs/port-plan.md', encoding='utf-8').read()
assert '## §219' not in port
io.open(ROOT + 'docs/port-plan.md', 'a', encoding='utf-8', newline='\n').write(SECTION)
print('port-plan §219 appended')

readme = io.open(ROOT + 'README.md', encoding='utf-8').read()
for old, new in [
    ('（§1–§218，每一轮都留数字、记下被推翻的结论）', '（§1–§219，每一轮都留数字、记下被推翻的结论）'),
    ('编译成 80,648 B 的 `rdcf` 镜像（core 镜像 68,216 B）', '编译成 80,956 B 的 `rdcf` 镜像（core 镜像 68,396 B）'),
]:
    assert readme.count(old) == 1, old[:40]
    readme = readme.replace(old, new)
io.open(ROOT + 'README.md', 'w', encoding='utf-8', newline='').write(readme)
print('README updated')
