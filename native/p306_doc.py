"""§306 文档：E 类收尾 —— `runic_pyramid` 的端到端判据与一个真 bug。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'

DOC = r"""
---

## §306 E 类收尾：`runic_pyramid` —— 接线早就有了，判据没有；补判据时抓到一个真 bug

`runic_pyramid`（Boss 遗物，*"At the end of your turn, you no longer discard your hand"*）在
§268 就已经接线完整：内容状态 `standard.runic_pyramid` 带 `retain_hand` 标签、
`host.rs::hand_is_retained_detail` 读标签、`turn.rs` 按它决定回合末弃不弃手牌。

覆盖矩阵里它的"测试"一栏是 `the_zero_infrastructure_tail_wires_its_carriers` ——
那条只证明**遗物挂上了状态**。而"手牌真的留下来了"没有任何判据。这正是本项目最怕的形状。

### 306.1 补判据 → 立刻红：整手保留把 Ethereal 也赦免了

`discard_hand` 在 `hand_is_retained` 为真时**整段短路**（`return Ok(0)`），于是落点为消耗堆的
Ethereal 牌也留在了手里。判据实测 `with 0 vs without 1`：有遗物时**一张都没消耗**。

wiki 两处独立来源都写得很清楚：

* `Keywords`：*"Ethereal: If an Ethereal card is in your hand at the end of your turn, it is
  **Exhausted**."*
* `Runic_Pyramid`：*"Still fires: **Ethereal cards still Exhaust** and cards with end-of-turn
  effects still fire."*

修法：**先算落点，再决定留不留** —— 落点 = 消耗堆那一档从两条"留下"的规则旁边穿过去：

```rust
let destination = host.turn_end_hand_destination(state, actor, slot);
if destination == CardZone::Hand { continue }
if destination != CardZone::ExhaustPile
    && (hand_retained || host.card_stays_in_hand_at_turn_end(state, actor, slot))
{ continue }
```

⚠️ 顺手纠正一处顺序错：旧代码先问 `card_stays_in_hand_at_turn_end`（Retain 关键字）再算落点，
于是"Retain + Ethereal"会被留下。本内容没有这种牌（Retain 是观者的关键字），**今天没有可观察
差异**，但它现在是按 wiki 写的，而不是按"谁的检查写在前面"。

### 306.2 判据三层

| 断言 | 钉住 |
|---|---|
| 没有遗物 ⇒ 回合末手牌 0 | 基线。**没有它，一条"永远保留"的实现也全绿** —— 而那会让手牌越滚越多 |
| 有遗物 ⇒ 手牌 > 0 | 保留真的发生（而不只是"状态挂上了"） |
| 有/无遗物的 Ethereal 消耗数**相等**且 > 0 | Ethereal 不受这件遗物影响。⚠️ 第一版写成"更多"，修好之后 `1 = 1` 就红了 —— **断言本身说错了话** |

**负控 2 条全红**：回到整段短路（原 bug）、把 Ethereal 也当"留下"。

### 306.3 账

`rd-core` 809 / `rd-run` 185 / `rd-wasm` **151**（+1）；矩阵 878 行 / tests **1147**；
八道页面门 + `SOAK`；21/21。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§306 E 类收尾' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)
    print('doc written')


main()
