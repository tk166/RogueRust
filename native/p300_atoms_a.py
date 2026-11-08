"""§300 三个原子 + 三件遗物。

| 原子 | 改动 | 解锁 |
|---|---|---|
| `offerRandomCards` 支持 `Then` | 把写死的 `ToHandFree` 换成查表（表已经存在，`chooseCards` 就在用） | `nilrys_codex` |
| `upgradeCards` 支持 `Random` | 取牌从"牌区顺序前 N 张"变成"随机 N 张"（`random_step` 同一本账） | `warped_tongs` |
| 新节点 `node.setCardCostOverride` | 给牌区里的牌写 `standard.card_cost_override`（可随机） | `mummified_hand` |

三个都是**我们自己的扩展**（参考的这几件事各有别的实现），所以每条都写清"为什么需要它"。
"""
import io

IR = 'D:/Vibe/sts-tui/kernel/rd-core/src/ir.rs'
EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'

NODE = '''    /// §300：**把一张牌的价格改写成绝对值**（`mummified_hand`：手牌一张变 0 费）。
    ///
    /// 写的是 `standard.card_cost_override` 那一格（§161.4：绝对价，在 delta 之前生效、
    /// 出牌付款后由内核清零）。参考实现里对应 `CardInstanceCostModifier`，但它挂在卡**自己**
    /// 的字段上、由 C# 代码直接改；本内核的等价物就是这个 mark counter，所以内容需要一个
    /// 能写它的节点 —— 在此之前只有 `createRandomCardInstance{CostZero}` 与内核的
    /// `playTopCardOfDrawPile` 会写它。
    SetCardCostOverride,
'''


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── 原子 C：新节点
    patch(IR, '''    UpgradeCards,''', '''    UpgradeCards,
''' + NODE.rstrip('\n'))
    patch(IR, '''            NodeKind::UpgradeCards => "node.upgradeCards",''',
                '''            NodeKind::UpgradeCards => "node.upgradeCards",
            NodeKind::SetCardCostOverride => "node.setCardCostOverride",''')
    patch(IR, '''        const ALL: [NodeKind; 41] = [''', '''        const ALL: [NodeKind; 42] = [''')
    patch(IR, '''            NodeKind::UpgradeCards,''', '''            NodeKind::UpgradeCards,
            NodeKind::SetCardCostOverride,''')

    # 预检表 + 派发表
    patch(EXEC, '''        | NodeKind::UpgradeCards''', '''        | NodeKind::UpgradeCards
        | NodeKind::SetCardCostOverride''')
    patch(EXEC, '''        NodeKind::UpgradeCards => upgrade_cards_node(node, ctx, frame, slot, stats),''',
                '''        NodeKind::UpgradeCards => upgrade_cards_node(node, ctx, frame, slot, stats),
        NodeKind::SetCardCostOverride => {
            set_card_cost_override_node(node, ctx, frame, slot, stats)
        }''')

    # ── 原子 A：`offerRandomCards` 的 `Then` 透传
    patch(EXEC, '''    // `Then` 缺席 ⇒ `ToHandFree`（与 `Discovery` 同一条默认）。
    let then = match node.str_field("Then")? {
        None | Some("ToHandFree") => crate::state::ChoiceThen::ToHandFree,
        Some("PlayChosen") => crate::state::ChoiceThen::PlayChosen,
        Some(_) => return Err(ExecError::Ir(IrError::UnknownKind)),
    };''', '''    // `Then` 缺席 ⇒ `ToHandFree`（与 `Discovery` 同一条默认）。
    //
    // §300：`nilrys_codex`（"三选一，把它塞进抽牌堆"）需要**别的收尾**，而这个节点的 `then`
    // 原来是写死的。词表本身早就有了（`chooseCards` 那条路在用 `ToDrawPileTop` /
    // `ToDrawPileBottomFree` / …），所以这里不再复制一份：直接把同一个名字查进同一张表。
    //
    // ⚠️ 已知偏差（写进 gap F.20）：抽牌堆只有 **Top / Bottom** 两个插入点，
    // 没有"随机洗入" —— `nilrys_codex` 用 `ToDrawPileTop`（下一张就抽它）。
    let then = match node.str_field("Then")? {
        None => crate::state::ChoiceThen::ToHandFree,
        Some(name) => choice_then_from_name(name, node)?,
    };''')
    print('atoms A + C')


main()
