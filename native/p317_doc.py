"""§317 记账：Transient（Act 3 普通池 10 / 10）；`Shifting` 记成机制缺口。"""
import io

ROOT = 'D:/Vibe/sts-tui/'
PLAN = ROOT + 'docs/port-plan.md'
ACCEPT = ROOT + 'tools/acceptance.ps1'

DOC = r"""
---

## §317 Transient：Act 3 的普通池 **10 / 10**；顺带挖出"负力量不可表达"

wiki（`Transient` 页 + 两个攻略页，三处数字一致）：HP **999**（不随升阶变）、`Fading 5`
（A17: 6）、`Shifting`（受伤时**临时**失去等量力量）、Attack 第 1 回合 30（A2: 40）**每回合 +10**。

### 317.1 两条做成了，一条没做成

| 规则 | 载体 | 结果 |
|---|---|---|
| `Fading`：5 回合后自己消失 | `TurnEnded` 触发器：剩 1 层就 `destroyCombatant(self)`，否则 `modifyStatusStacks(-1)` | ✅ |
| Attack 递增 | 表达式 `20 + 10 × roundNumber`（A2 档 30 + 10×turn） | ✅ |
| `Shifting`：受伤临时掉等量力量 | **负层数不可表达** | ❌ §D.6 |

`Fading` 那条的**顺序**是它唯一容易写错的地方：不能"减到 0 再死" —— 层数归零会**删掉状态实例**，
触发器跟着实例一起没了，于是永远等不到"死"那一步。所以判据写成"剩 1 层 ⇒ 这一回合结束就消失"。

### 317.2 一个判据层的连带修改

`transient.attack` 的伤害是 `20 + 10×round`，而检查器的 `amount()` 会把 `add` 渲染成**不透明**的
`('expr','add')` —— 于是基础档与 A2 档的事实**一模一样**，判据报"这一档什么都没做"（它是对的：
从事实看不见差别）。

改法沿用文件里已有的先例（§229/§233 的"动态尺寸"）：把 `roundNumber` 也归进
`_has_dynamic_size`，于是这一族表达式被**拆开**成 `('add', 20, ('multiply', ('expr','roundNumber'), 10))`
—— 两档的常量差看得见。**只影响用到 `roundNumber` 的动作**（今天两个：`maw.nom_nom` /
`transient.attack`），其余 120+ 条事实一个字都没动。

### 317.3 判据与负控

`the_transient_scales_its_attack_and_fades_away`（rd-wasm，真战斗）两段：
① 第 1 回合 30、第 2 回合 40；② 逐回合读 `Fading` 层数（5→4→3→2→1）并在第 5 次回合结束时
断言它**已经不在场上**。

**负控 2/2 红**（`native/p317_negative.py`）：`Fading` 的条件写成恒假（只剩自减）⇒ 第 5 回合
断言红；攻击写成固定 30 ⇒ 第 2 回合断言红。

### 317.4 账

内容：**58 怪 / 61 遭遇 / 148 状态 / 159 敌人动作 / 117 变体（101 动作）**；
镜像 **177,908 B**（core 140,968 B）；**三幕普通池：Act 1 17 条 / Act 2 13/13 / Act 3 10/10**。

`rd-core` 809 / `rd-run` 194 / `rd-wasm` **162**（+1）；聚合闸门 **22/22**（`rust-units 1165`）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§317 Transient' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)
    accept = io.open(ACCEPT, encoding='utf-8').read()
    assert accept.count('  [int]$UnitsFloor = 1164') == 1
    io.open(ACCEPT, 'w', encoding='utf-8', newline='\n').write(
        accept.replace('  [int]$UnitsFloor = 1164', '  [int]$UnitsFloor = 1165'))
    print('§317 recorded; UnitsFloor 1165')


main()
