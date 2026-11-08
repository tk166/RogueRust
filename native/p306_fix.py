"""§306 修 `discard_hand`：整手保留**不赦免 Ethereal**。

## 症状

`runic_pyramid` 让 `host.hand_is_retained` 为真，而 `discard_hand` 在真时**整段短路**
（`return Ok(0)`）—— 于是 Ethereal 牌（落点 = 消耗堆）也留在了手里。

判据（`runic_pyramid_keeps_the_whole_hand_and_ethereal_still_exhausts`）实测：
`with 0 vs without 1` —— 有遗物时**一张都没消耗**。

## 依据（两处独立来源）

* wiki.gg `Keywords`：*"Ethereal: If an Ethereal card is in your hand at the end of your turn,
  it is **Exhausted**."*
* wiki.gg `Runic_Pyramid`：*"Still fires: **Ethereal cards still Exhaust** and cards with
  end-of-turn effects still fire."*

## 修法：先算落点，再决定"留不留"

旧顺序是"先问 `card_stays_in_hand_at_turn_end`，再算落点"。新顺序把落点提到前面，并让
**落点 = 消耗堆**那一档从两条"留下"的规则旁边**穿过去**：

```
let destination = host.turn_end_hand_destination(...);
if destination == Hand { continue }
if destination != ExhaustPile {
    if hand_retained { continue }                    // 整手保留（Runic Pyramid）
    if card_stays_in_hand_at_turn_end { continue }   // 这张自己有 Retain
}
```

⚠️ 旧代码里"Retain 关键字 + Ethereal"会被留下（因为 retain 检查在前）。本内容没有这样的牌
（Retain 是观者的关键字），所以这一格**今天没有可观察差异** —— 但它现在是按 wiki 说的
行为写的，而不是按"谁的检查写在前面"。
"""
import io

TURN = 'D:/Vibe/sts-tui/kernel/rd-core/src/turn.rs'

OLD_DOC = '''/// 被 `host.hand_is_retained(...)` 抑制（`Cards/CardTurnLifecycleEventHandlers.cs:46-55`）——
/// 那是**整手**保留，先短路，一张都不碰。返回**实际搬走**的张数。'''
NEW_DOC = '''/// `host.hand_is_retained(...)`（`Cards/CardTurnLifecycleEventHandlers.cs:46-55`）是**整手不弃**，
/// 但它**不赦免 Ethereal**：wiki 的 `Keywords` 写 "If an Ethereal card is in your hand at the end
/// of your turn, it is Exhausted"，`Runic_Pyramid` 页也写 "Still fires: Ethereal cards still
/// Exhaust"。所以整手保留只抑制"弃"那一档，落点 = 消耗堆的那一档照旧搬。
///
/// ⚠️ 旧实现是**整段短路**（`return Ok(0)`），于是 Ethereal 也留在手里 —— 那个偏差没有任何东西
/// 会红，因为覆盖矩阵里这件遗物只被"挂上状态"那条测试认领过。返回**实际搬走**的张数。'''

OLD_BODY = '''    // 被 `RetainHandTag` 抑制（`Cards/CardTurnLifecycleEventHandlers.cs:46-55`）—— 本内核走
    // `host.hand_is_retained`，因为"哪些标记保留手牌"是内容决定的。抑制时返回 0（"一张都没弃"）。
    if host.hand_is_retained(state, actor) {
        return Ok(0);
    }
'''
NEW_BODY = '''    // 整手保留（`RetainHandTag`，本内核走 `host.hand_is_retained` —— "哪些标记保留手牌"是内容
    // 决定的）。它只抑制"弃"，**不**赦免 Ethereal（见文档注释里的两句 wiki 原文）。
    let hand_retained = host.hand_is_retained(state, actor);
'''

OLD_LOOP = '''        if host.card_stays_in_hand_at_turn_end(state, actor, slot) {
            continue;
        }
        let destination = host.turn_end_hand_destination(state, actor, slot);
        if destination == CardZone::Hand {
            continue;
        }'''
NEW_LOOP = '''        // 落点先算：它是**这张牌自己的**答案（Ethereal ⇒ 消耗堆，Retain ⇒ 手牌），
        // 而"整手保留"与"这张有 Retain"都只该在**非** Ethereal 的牌上生效。
        let destination = host.turn_end_hand_destination(state, actor, slot);
        if destination == CardZone::Hand {
            continue;
        }
        if destination != CardZone::ExhaustPile
            && (hand_retained || host.card_stays_in_hand_at_turn_end(state, actor, slot))
        {
            continue;
        }'''


def main():
    s = io.open(TURN, encoding='utf-8').read()
    for old, new in ((OLD_DOC, NEW_DOC), (OLD_BODY, NEW_BODY), (OLD_LOOP, NEW_LOOP)):
        assert s.count(old) == 1, (s.count(old), old[:70])
        s = s.replace(old, new)
    io.open(TURN, 'w', encoding='utf-8', newline='\n').write(s)
    print('discard_hand fixed')


main()
