"""§231 (part 1): 两件内核能力。

* `standard.no_draw` —— "本回合不能再抽牌"。`Battle Trance` 的原文是 "You cannot draw additional
  cards **this turn**"，而内容里原来给它挂的是 `standard.draw_reduction`（那条只压**下回合起手抽牌**，
  是另一根轴）⇒ 那条实现是错的，这一节修。规则落在 `draw_cards_node`：回合起手抽牌不算"additional"，
  所以只拦**效果驱动**的抽牌，正好是这张牌说的那件事。
* `node.dealDamageAndHealByLoss` —— 先打伤害，再按**实际掉的血**给来源回血（`Reaper`）。
  `resolve_damage` 一直返回 `(blocked, health_lost)`，只是从来没有人把第二个数用于"回血"。
"""
import io

CATALOG = 'kernel/rd-core/src/status_catalog.rs'
EXEC = 'kernel/rd-core/src/exec.rs'
IR = 'kernel/rd-core/src/ir.rs'


def rewrite(path, edits):
    src = io.open(path, encoding='utf-8').read()
    for old, new in edits:
        assert src.count(old) == 1, (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)



src = io.open(EXEC, encoding='utf-8').read()
anchor = '''/// §230：`node.dealDamageWithTagBonus` 的实体'''
assert src.count(anchor) == 1
impl = open('D:/Vibe/sts-tui/native/p231_impl.txt', encoding='utf-8').read() + anchor
src = src.replace(anchor, impl)
io.open(EXEC, 'w', encoding='utf-8', newline='
').write(src)
# ── 3) ir 词表 + 预检 + 分发 ────────────────────────────────────────────────
rewrite(IR, [
    ('''    /// `node.dealDamageWithTagBonus` —— **基础伤害 + 每张带某个 tag 的牌一份加成**（§230）。''',
     '''    /// `node.dealDamageAndHealByLoss` —— 打伤害，然后按**实际掉的血**给来源回血（§231，`Reaper`）。
    ///
    /// 参考靠 `ResultKey` 把"这一击掉了多少血"传给下一个节点；本内核不支持 `ResultKey`，而
    /// `resolve_damage` 本来就返回 `(blocked, health_lost)` —— 所以这个节点自己当场算。
    DealDamageAndHealByLoss,
    /// `node.dealDamageWithTagBonus` —— **基础伤害 + 每张带某个 tag 的牌一份加成**（§230）。'''),
    ('''            NodeKind::DealDamageWithTagBonus => "node.dealDamageWithTagBonus",''',
     '''            NodeKind::DealDamageAndHealByLoss => "node.dealDamageAndHealByLoss",
            NodeKind::DealDamageWithTagBonus => "node.dealDamageWithTagBonus",'''),
    ('''        const ALL: [NodeKind; 27] = [''', '''        const ALL: [NodeKind; 28] = ['''),
    ('''            // §230：按"带某个 tag 的牌数"加伤的伤害（Perfected Strike）。
            NodeKind::DealDamageWithTagBonus,''',
     '''            // §230：按"带某个 tag 的牌数"加伤的伤害（Perfected Strike）。
            NodeKind::DealDamageWithTagBonus,
            // §231：打伤害并按实际掉血回血（Reaper）。
            NodeKind::DealDamageAndHealByLoss,'''),
])

rewrite(EXEC, [
    ('''        // §230：`dealDamageWithTagBonus`（数牌 + 打伤害）。同上。
        | NodeKind::DealDamageWithTagBonus''',
     '''        // §230：`dealDamageWithTagBonus`（数牌 + 打伤害）。同上。
        | NodeKind::DealDamageWithTagBonus
        // §231：`dealDamageAndHealByLoss`（打伤害 + 按掉血回血）。同上。
        | NodeKind::DealDamageAndHealByLoss'''),
    ('''        NodeKind::DealDamageWithTagBonus => {''',
     '''        NodeKind::DealDamageAndHealByLoss => {
            deal_damage_and_heal_by_loss_node(node, ctx, frame, slot, stats)
        }
        NodeKind::DealDamageWithTagBonus => {'''),
])
print('ok kernel')
