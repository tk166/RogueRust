"""§300：补上两个函数本体（`choice_then_from_name` 与 `set_card_cost_override_node`）。

`chooseCards` 里那段 `match then_name` 已经被前一步替换成调用；这里把**同一张表**写成函数，
并把新节点的实体写上（照 `set_combatant_counter_node` 的形状：求值 → 选 owner → 入队请求）。
"""
import io

EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'

FUNCTION = '''/// §300：`Then` 的名字 → [`crate::state::ChoiceThen`] 的**唯一**一张表。
///
/// 两个节点共用它：`chooseCards`（问"已有的哪几张"）与 `offerRandomCards`（问"这几张新的里
/// 要哪个"）。§300 之前后者把 `then` **写死**成 `ToHandFree`，于是"三选一，塞进抽牌堆"
/// （`nilrys_codex`）在内容里表达不出来 —— 而词表其实早就有了。
///
/// ⚠️ `Copy` 变体要从节点上读 `Copies` / `ToZone`，所以这个函数拿的是 `node` 而不是纯字符串。
fn choice_then_from_name(
    then_name: &str,
    node: NodeRef<'_>,
) -> Result<crate::state::ChoiceThen, ExecError> {
    let then = match then_name {
        "Copy" => {
            let copies = node.int_field("Copies")?.ok_or(IrError::Missing("Copies"))?;
            if !(1..=MAX_COPIES_PER_CHOICE as i32).contains(&copies) {
                return Err(ExecError::Ir(IrError::Missing("Copies")));
            }
            // `ToZone` 缺席 ⇒ 手牌（Dual Wield 的语义）。
            let into = match node.str_field("ToZone")? {
                Some(name) => zone_from_wire_name(name).ok_or(ExecError::Ir(IrError::UnknownKind))?,
                None => CardZone::Hand,
            };
            crate::state::ChoiceThen::Copy {
                copies: u8::try_from(copies)
                    .map_err(|_| ExecError::Ir(IrError::Missing("Copies")))?,
                into,
            }
        }
        // §227：Armaments —— 选一张原地升级。
        "Upgrade" => crate::state::ChoiceThen::Upgrade,
        // §227：Warcry —— 选一张放到抽牌堆顶。
        "ToDrawPileTop" => crate::state::ChoiceThen::ToDrawPileTop,
        // §250：`Forethought` —— 抽牌堆底，且这一份免费。
        "ToDrawPileBottomFree" => crate::state::ChoiceThen::ToDrawPileBottomFree,
        // §250：`Discovery` —— 进手牌且免费（`offerRandomCards` 的默认收尾）。
        "ToHandFree" => crate::state::ChoiceThen::ToHandFree,
        // §231：True Grit+ —— 选一张消耗掉。
        "Exhaust" => crate::state::ChoiceThen::Exhaust,
        // §238：Exhume —— 选中的那张拿进手牌。
        "ToHand" => crate::state::ChoiceThen::ToHand,
        _ => return Err(ExecError::Ir(IrError::UnknownKind)),
    };
    Ok(then)
}

'''

NODE_FN = '''/// §300：`node.setCardCostOverride` —— `{OwnerSelector, FromZone?, CardDefinitionId?,
/// Count?, Random?, Amount}`：把牌的价格改写成**绝对值**（`mummified_hand`）。
///
/// 形状与 [`upgrade_cards_node`] 同族（同一个 owner 选择器 + 同一个"从哪个牌区取"），差别只有
/// 两处：写的是 `standard.card_cost_override` 那一格，而不是定义 id；以及支持 `Random`。
///
/// `Amount` 缺席 ⇒ 0（"变 0 费"是这件遗物的全部内容，而"改成别的数"没有用户）。
fn set_card_cost_override_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    let only_zone = match node.str_field("FromZone")? {
        Some(name) => zone_from_wire_name(name).ok_or(ExecError::Ir(IrError::UnknownKind))?,
        // 缺席 ⇒ 手牌。`mummified_hand` 说的是 "a random card in your **hand**"。
        None => CardZone::Hand,
    };
    let limit = match node.int_field("Count")? {
        Some(count) if count >= 0 => count as usize,
        Some(_) => return Err(ExecError::Ir(IrError::Missing("Count"))),
        None => 1,
    };
    let random = node.bool_field("Random")?.unwrap_or(false);
    let amount = match node.node_field("Amount")? {
        Some(term) => {
            let expr_ctx = ctx.expr_context();
            expr::eval_int(term, &expr_ctx)?
        }
        None => 0,
    };

    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let owner_count = resolve_targets(owner_selector, ctx, &mut owners)?;
    let Some(owner) = owners.first().copied().filter(|_| owner_count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };

    // 先快照候选（槽位），再改 —— 与 `upgrade_cards_node` 同一条"先读后写"。
    let mut slots = [0u16; crate::state::MAX_CARDS_PER_ZONE];
    let count = match ctx.state.card_zones(&owner) {
        Some(data) => {
            let listed = data.slots(only_zone);
            let count = listed.len().min(slots.len());
            slots[..count].copy_from_slice(&listed[..count]);
            count
        }
        None => 0,
    };
    if count == 0 {
        return resume_later(ctx.state, frame, slot);
    }
    // 随机取：用内核的随机账（与随机造牌/洗牌同一本账），抽一次挑一个起点。
    let start = if random {
        let picked = crate::rng::shuffled_pick_index(count, ctx.state.random_seed, ctx.state.random_step);
        ctx.state.random_step = ctx.state.random_step.saturating_add(1);
        picked
    } else {
        0
    };
    let key = crate::state::CounterId::new(crate::state::CARD_COST_OVERRIDE_COUNTER)?;
    let mut changed = 0usize;
    for step in 0..count {
        if changed >= limit {
            break;
        }
        let index = (start + step) % count;
        let card_slot = crate::state::CardSlot::from_index(slots[index]);
        if let Some(card) = ctx.state.card_mut(card_slot) {
            card.set_mark_counter(key, amount).map_err(ExecError::Capacity)?;
            changed += 1;
        }
    }
    resume_later(ctx.state, frame, slot)
}

'''


def main():
    s = io.open(EXEC, encoding='utf-8').read()

    # 1) `choice_then_from_name` 挂在 `choose_cards_node` 前面
    if 'fn choice_then_from_name(' not in s:
        index = s.index('fn choose_cards_node(')
        doc_start = s.rfind('\n\n', 0, s.rfind('\n///', 0, index)) + 1
        s = s[:doc_start] + FUNCTION + s[doc_start:]

    # 2) `set_card_cost_override_node` 挂在 `upgrade_cards_node` 前面
    if 'fn set_card_cost_override_node(' not in s:
        index = s.index('fn upgrade_cards_node(')
        doc_start = s.rfind('\n\n', 0, s.rfind('\n///', 0, index)) + 1
        s = s[:doc_start] + NODE_FN + s[doc_start:]

    io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(s)
    print('functions inserted')


main()
