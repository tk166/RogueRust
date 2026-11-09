"""§313 记账：选择器 + 条件 + 表达式三块新零件，Centurion + Mystic，Act 2 到 12 / 13。"""
import io

ROOT = 'D:/Vibe/sts-tui/'
PLAN = ROOT + 'docs/port-plan.md'
ACCEPT = ROOT + 'tools/acceptance.ps1'

DOC = r"""
---

## §313 "指定某一只友军"：三块新零件，Act 2 补到 12 / 13

§311 之后 Act 2 只剩两条组合，`Centurion and Mystic` 那条卡在"没有『按定义挑一只友军』的选择器"。
做完发现**真正缺的是三块**，各自对应一条不能再简化的规则：

| 零件 | 规则 | 为什么不能复用旧的 |
|---|---|---|
| `sel.alliesWithDefinition` | `Protect`：**Mystic** 得 15 块（独自时自己得） | `sel.lowestHealthAlly` 在 Centurion 掉到 10 血时会返回 Centurion —— 那是另一个行为。**负控就是把它换上去，判据当场红** |
| `intent.allyMissingHealth` | `Mystic`：有**盟友**缺 ≥16 血时优先 `Heal` | `intent.healthPercent` 只看出手者自己；Mystic 是后排奶妈，"自己缺 16 血"几乎是另一条规则 |
| `combatantCount`（表达式） | `Protect` 的"独自时自保"要在**动作程序**里数活着的友军 | `intent.enemyAliveCount` 只活在**意图规则**的条件求值器里；写进程序 ⇒ `Expr(UnsupportedKind)`（实测撞过） |

### 313.1 形状：`DefinitionFilter` 是"筛"，不是"选"

`targets.rs` 加了 `SelectorNode::DefinitionFilter { inner, definition_id }`，与 `StatusFilter`
完全同构（先取子树、再筛一遍）。不新造叶子选择器是有意的：叶子那层回答"从哪儿开始选"，
"按定义筛"是在**已经选出来的集合**上做减法 —— 两者的基数和语义都不同
（`node_cardinality` 里它与 `StatusFilter` 同为 `ZeroOrMore`）。

### 313.2 三次"改完还是红"（都是我的错，形状值得记）

1. **`intent.not` 的内层写成 `and`**。`and` 是**表达式**的布尔与，条件求值器只认 `intent.*`
   ⇒ `UnknownConditionKind`。正确写法是 `intent.not` 里包 `intent.allOf`。
2. **只改了 `Monsters` 没改 `Encounters` 的敌人记录副本**。两处都是"这只怪的规则"，
   遭遇里那份才是运行期读的 ⇒ "改完还是红"。诊断花了好几轮，最后靠**二分**（把 Mystic 的
   规则逐条砍到恒真）才定位。教训：**同一个事实有两份拷贝时，二分要同时改两份**。
3. **`intent.enemyAliveCount` 写进动作程序** ⇒ `Expr(UnsupportedKind)`。于是补了
   `combatantCount` 表达式（`{Selector, AliveOnly}`，缺省只数活着的）。

### 313.3 内容

Centurion（76-80，A7 78-83）：`Slash` 12（A2 14）/ `Protect`（Mystic 15 块，A17 20；
独自时自己得）/ `Fury` 6×3（A2 7×3，Mystic 死后替代 Protect）；65/35，任一招不连三次。
Mystic（48-56，A7 50-58）：`Attack` 8 + 2 Frail（A2 9）/ `Buff` 全体 +2 力量（A2 3 / A17 4）/
`Heal` 全体 16（A17 20）；盟友缺 ≥16 血时优先 Heal、最多连两次；否则 60/40；
A17 起 Attack 不连两次。

池子 **12 / 13**（只剩 `2 Thieves`，要 `mugger` 的招式序列出处）。

### 313.4 判据与负控

| 判据 | 钉的东西 |
|---|---|
| `protect_gives_the_block_to_the_mystic_even_when_the_centurion_is_hurt` | **按定义**而非按血量（把 Centurion 打到 10 血，Mystic 仍拿 15 块） |
| `protect_falls_back_to_the_centurion_when_the_mystic_is_downed` | wiki 的另一半"独自时自己得" |
| `mystic_heals_when_a_ally_is_missing_sixteen_health_but_only_twice_in_a_row` | 三侧：满血不治 / 盟友缺 20 血就治 / 连治两次后不再治 |
| `every_pool_encounter_builds_and_runs_without_a_thrown_step`（已有） | 新遭遇进池子自动被扫到 —— 这一轮它抓到了上面第 1/3 两个坑 |

**负控 2/2 红**（`native/p313_negative.py`）：换成 `sel.lowestHealthAlly` ⇒ 判据 1 红；
把"独自"条件改成恒假 ⇒ 判据 2 红。

### 313.5 账

内容：**54 怪 / 55 遭遇 / 147 状态 / 150 敌人动作 / 109 变体（95 动作）**；
镜像 **173,808 B**（core 137,088 B）；Act 2 普通池 **12 / 13**。
`rd-core` 809 / `rd-run` 194 / `rd-wasm` **157**（+3）；聚合闸门 **22/22**（`rust-units 1160`）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§313 "指定某一只友军"' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)
    accept = io.open(ACCEPT, encoding='utf-8').read()
    assert accept.count('  [int]$UnitsFloor = 1157') == 1
    io.open(ACCEPT, 'w', encoding='utf-8', newline='\n').write(
        accept.replace('  [int]$UnitsFloor = 1157', '  [int]$UnitsFloor = 1160'))
    print('§313 recorded; UnitsFloor 1160')


main()
