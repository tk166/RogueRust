"""§254（2/2）：`node.offerCards` 的实体 —— 固定候选表 + "选中被打出"。

`Wish` 是**唯一**"先造一张、再立刻打出它"的牌（wiki 原话）。它与 `Discovery` 的
`offerRandomCards` 只在"候选从哪来"上不同（固定表 vs 随机池），所以两件事分开写节点：
合并会让"候选是内容写死的"没有地方可表达。

字段：`{Definitions: [卡定义 id], Min?, Max?, Then?}`。
`Then` 缺席 = `ToHandFree`（与 `Discovery` 同义）；`Wish` 写 `PlayChosen`。
"""
import io

EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'

CHILDLESS = (
    '''        | NodeKind::PlayCard
        | NodeKind::CreateCardCopy''',
    '''        | NodeKind::PlayCard
        | NodeKind::OfferCards
        | NodeKind::CreateCardCopy''')

DISPATCH = (
    '''        NodeKind::PlayCard => play_card_node(node, ctx, frame, slot, stats),''',
    '''        NodeKind::PlayCard => play_card_node(node, ctx, frame, slot, stats),
        NodeKind::OfferCards => offer_cards_node(node, ctx, frame, slot, stats),''')

CODE = r'''
/// §254：`node.offerCards` 的实体 —— `{Definitions, Min?, Max?, Then?}`。
///
/// 三个候选是**内容写死的**（`Definitions` 是 `F_STRLIST`），按给定顺序进问句。
/// `Then` 决定选完做什么：`ToHandFree`（进手牌、这次免费，与 `Discovery` 同义）或
/// `PlayChosen`（**立刻打出它**，`Wish`）。
///
/// 与 `offerRandomCards` 共用"问句怎么建"这件事的形状（`PendingChoice` + `ChoiceSource::Offered`），
/// 但**不共用抽签**：这里一个随机都不掷 —— 抽签会让"Wish 的三个选项是固定的"变成运气。
fn offer_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let mut ids = [0u16; MAX_OFFERED_CARDS];
    let count = node.str_list_field("Definitions", &mut ids)?;
    if count == 0 || count > MAX_OFFERED_CARDS {
        return Err(ExecError::Modifier);
    }
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };
    let Some(chooser) = ctx.source else {
        return Err(ExecError::MissingCombatant);
    };
    let min = u8::try_from(node.int_field("Min")?.unwrap_or(1)).map_err(|_| ExecError::Modifier)?;
    let max = u8::try_from(node.int_field("Max")?.unwrap_or(1)).map_err(|_| ExecError::Modifier)?;
    if min > max {
        return Err(ExecError::Modifier);
    }
    // `Then` 缺席 ⇒ `ToHandFree`（与 `Discovery` 同一条默认）。
    let then = match node.str_field("Then")? {
        None | Some("ToHandFree") => crate::state::ChoiceThen::ToHandFree,
        Some("PlayChosen") => crate::state::ChoiceThen::PlayChosen,
        Some(_) => return Err(ExecError::Ir(IrError::UnknownKind)),
    };

    let mut offered = crate::state::Bounded::new();
    for index in 0..count {
        let Some(text) = ids.get(index).copied().and_then(|id| content.string(id)) else {
            return Err(ExecError::Ir(IrError::Missing("Definitions")));
        };
        // 定义必须在 `CARD` 表里 —— 一个指向不存在的牌的候选会让"选中"那一步炸，
        // 而那时玩家已经点了（不可回退）。所以**建问句之前**就验。
        if card_row(content, text).is_none() {
            return Err(ExecError::Ir(IrError::Missing("CARD row")));
        }
        let definition = CardDefinitionId::new(text)?;
        offered
            .push(definition, crate::state::Container::ChoiceOptions)
            .map_err(ExecError::Capacity)?;
    }

    let question = crate::state::PendingChoice {
        chooser,
        source: crate::state::ChoiceSource::Offered,
        min,
        max,
        then,
        offered,
        candidates: crate::state::Bounded::new(),
    };
    ctx.state
        .begin_choice(question)
        .map_err(|_| ExecError::Modifier)?;
    resume_later(ctx.state, frame, slot)
}

'''


def main():
    src = io.open(EXEC, encoding='utf-8').read()
    assert 'fn offer_cards_node' not in src, 'already patched'
    for old, new in [CHILDLESS, DISPATCH]:
        assert src.count(old) == 1, (old[:50], src.count(old))
        src = src.replace(old, new)
    anchor = '/// §250：`node.offerRandomCards` 的实体'
    assert src.count(anchor) == 1
    src = src.replace(anchor, CODE.lstrip('\n') + anchor)
    io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)
    print('exec.rs: offerCards implemented')


main()
