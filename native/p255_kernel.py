"""§255：`Conjure Blade` 的两半 —— 审计口径扩到紫色 + 造牌时能带一个每副本计数器。

## 一、审计口径

`native/audit_card_gap.py` 的 `IN_SCOPE` 一直是 `Red + Colorless + Curse + Status`，
所以**观者（Purple）的牌从来没被统计过** —— `Conjure Blade` 就是这样"不存在"的。
§254 把范围扩到含观者（`Wish` 落地），口径必须跟着扩，否则"缺多少"这件事继续不可见：
扩进去之后它会诚实地报"紫色还有 N 张没做"，而不是装作没有这批牌。

## 二、造牌时带计数器

`Conjure Blade` 的全部内容就是"造一张 `Expunger`，并且它的 **X** 等于我这次花的能量"
（升级版 `X+1`）。而 `Expunger` 的 X 存在**它自己**的每副本计数器上（§251 就是这么读的），
所以"造出来"与"带上那个数"必须是**同一次**动作 —— 分成两步就会出现"造出来了但 X 是 0"
的中间态（而那正好是 wiki 说的"能造出打 0 次的 Expunger"，两者不可区分）。

所以给 `node.createCardInstance` 加两个可选字段 `MarkCounterId` / `MarkValue`
（缺席 = 以前的行为，逐字不变）。请求侧对应 `mark: Option<(CounterId, i32)>`。
"""
import io

AUDIT = 'D:/Vibe/sts-tui/native/audit_card_gap.py'
STATE = 'D:/Vibe/sts-tui/kernel/rd-core/src/state.rs'
EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'

AUDIT_PATCH = (
    "IN_SCOPE = ('Red', 'Colorless', 'Curse', 'Status')",
    "# §255：观者也纳入范围（§254 决定：`Wish` 落地之后紫卡就算）。\n"
    "# 代价是诚实的：紫色还有一批没做，脚本会把它们列成 missing —— 那比\"装作没有这批牌\"好。\n"
    "IN_SCOPE = ('Red', 'Colorless', 'Curse', 'Status', 'Purple')")

STATE_PATCH = (
    '''    CreateCardInstance {
        /// 归属战斗员。
        owner: CombatantId,
        /// 卡定义。
        definition: CardDefinitionId,
        /// 张数。
        count: i32,
        /// 落到哪个区。
        to_zone: CardZone,
    },''',
    '''    CreateCardInstance {
        /// 归属战斗员。
        owner: CombatantId,
        /// 卡定义。
        definition: CardDefinitionId,
        /// 张数。
        count: i32,
        /// 落到哪个区。
        to_zone: CardZone,
        /// §255：造出来时给它写一个**每副本计数器**（`Conjure Blade` 的 "X 等于我花的能量"）。
        ///
        /// 为什么必须在**造**的那一步写：`Expunger` 的 X 存在它自己的 mark counter 上，
        /// 而"造出来但 X 是 0"与 wiki 说的"能造出打 0 次的 Expunger"**完全不可区分** ——
        /// 分成两步就会出现一个无法观测、也无法证伪的中间态。
        mark: Option<(CounterId, i32)>,''')

EXEC_NODE_PATCH = (
    '''    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let resolved = resolve_targets(selector, ctx, &mut targets)?;''',
    '''    // §255：可选的"造出来时写一个每副本计数器"（`Conjure Blade`）。
    let mark = match node.str_field("MarkCounterId")? {
        None => None,
        Some(key) => {
            let key = crate::state::CounterId::new(key)?;
            let value = match node.node_field("MarkValue")? {
                None => 0,
                Some(term) => {
                    let expr_ctx = ctx.expr_context();
                    expr::eval_int(term, &expr_ctx)?
                }
            };
            Some((key, value))
        }
    };
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let resolved = resolve_targets(selector, ctx, &mut targets)?;''')

EXEC_REQUEST_PATCH = (
    '''            EffectRequest::CreateCardInstance {
                owner,
                definition,
                count,
                to_zone,
            } => create_card_for(ctx, &owner, definition, count, to_zone),''',
    '''            EffectRequest::CreateCardInstance {
                owner,
                definition,
                count,
                to_zone,
                mark,
            } => create_card_for(ctx, &owner, definition, count, to_zone, mark),''')

EXEC_FN_PATCH = (
    '''fn create_card_for(
    ctx: &mut ExecContext<'_>,
    owner: &CombatantId,
    definition: CardDefinitionId,
    count: i32,
    zone: CardZone,
) -> Result<(), ExecError> {
    if count < 0 {
        return Err(ExecError::Modifier);
    }
    for _ in 0..count {
        // §161.5: 铸号搬到了 `state::CombatState::create_card_instance`（`Offered` 也要用它）。
        // 这里是**第二个调用方**，不是第二份实现 —— 两条铸号路径会给出两个"下一个是几"。
        ctx.state.create_card_instance(owner, definition, zone)?;
    }
    Ok(())
}''',
    '''fn create_card_for(
    ctx: &mut ExecContext<'_>,
    owner: &CombatantId,
    definition: CardDefinitionId,
    count: i32,
    zone: CardZone,
    mark: Option<(crate::state::CounterId, i32)>,
) -> Result<(), ExecError> {
    if count < 0 {
        return Err(ExecError::Modifier);
    }
    for _ in 0..count {
        // §161.5: 铸号搬到了 `state::CombatState::create_card_instance`（`Offered` 也要用它）。
        // 这里是**第二个调用方**，不是第二份实现 —— 两条铸号路径会给出两个"下一个是几"。
        let slot = ctx.state.create_card_instance(owner, definition, zone)?;
        // §255：造出来那一步就写计数器（`Conjure Blade` 的 X）。
        if let Some((key, value)) = mark {
            let card = ctx
                .state
                .card_mut(slot)
                .ok_or(ExecError::MissingCombatant)?;
            card.set_mark_counter(key, value).map_err(ExecError::Capacity)?;
        }
    }
    Ok(())
}''')

# `create_card_instance_node` 里那条请求的构造
EXEC_EMIT_PATCH = (
    '''        EffectRequest::CreateCardInstance {
            owner,
            definition,
            count,
            to_zone: zone,
        },''',
    '''        EffectRequest::CreateCardInstance {
            owner,
            definition,
            count,
            to_zone: zone,
            mark,
        },''')


def patch(path, pairs, label):
    src = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        if src.count(old) == 0 and new in src:
            # 幂等：这一处已经打过了（脚本重跑不该要求"再打一次"）。
            continue
        assert src.count(old) == 1, (label, old[:60], src.count(old))
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('patched', label)


def main():
    if 'Purple' not in io.open(AUDIT, encoding='utf-8').read():
        patch(AUDIT, [AUDIT_PATCH], 'audit_card_gap.py (scope += Purple)')
    patch(STATE, [STATE_PATCH], 'state.rs (mark on create)')
    patch(EXEC, [EXEC_NODE_PATCH, EXEC_REQUEST_PATCH, EXEC_FN_PATCH, EXEC_EMIT_PATCH],
          'exec.rs (create-with-mark)')


main()
