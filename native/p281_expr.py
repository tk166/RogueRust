"""§281：`randomInt` 值节点。

设计的三条硬约束（每一条都来自"表达式求值器是只读的"）：

1. `ExprContext.state` 是 `&CombatState` —— **求值器不能抽随机数**。所以 `eval_int` 的
   `randomInt` 分支只报错（`RandomNeedsADraw`），抽取只能发生在**派发点**
   （`exec::eval_amount`，那里手上有 `&mut ExecContext`）。
2. 因此**嵌套**（`add{randomInt{1,3}, const 1}`）会被响亮拒绝，而不是静默变成 0 或常数 ——
   静默是这里最坏的失败形态（一张牌少打一半伤害而屏幕上一切正常）。
3. 显示路径（`program_damage`）**不**取数：它只回答字面量，非字面量答 `-1`（既有契约）。
   所以意图面板不会为了画一个数字而消耗随机流。
"""
import io

P_EXPR = 'D:/Vibe/sts-tui/kernel/rd-core/src/expr.rs'
P_EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    # ---------------------------------------------------------------- expr：词表 + 响亮拒绝
    s = io.open(P_EXPR, encoding='utf-8').read()
    s = patch(s, '''    // §146：X 费牌的 X（本内核自己的 kind —— 参考里没有 X 费，见 `port-plan.md` §146）。
    "x.cost",''','''    // §146：X 费牌的 X（本内核自己的 kind —— 参考里没有 X 费，见 `port-plan.md` §146）。
    "x.cost",
    // §281：一个**随机整数**（`{Min, Max}`，两端都含）。
    //
    // ⚠️ 它**不在** `eval_int` 里取数 —— 求值器是只读的（`&CombatState`），抽数要写
    // `random_step`。真正的取数在派发点（`exec::eval_amount`），见那里的注释。
    // 放进 `INT_KINDS` 是因为**值类别**是 int：这样 `eval_bool` 会说"问错了问题"
    // （`WrongValueKind`）而不是"还没实现"，两者是不同的诊断。
    "randomInt",''')

    # eval_int 的分支：明确拒绝
    s = patch(s, '''        // §146：X 费牌的 X。零字段 —— 值只来自这次出牌付掉的能量。
        "x.cost" => Ok(ctx.x_cost),''','''        // §146：X 费牌的 X。零字段 —— 值只来自这次出牌付掉的能量。
        "x.cost" => Ok(ctx.x_cost),
        // §281：随机整数**不能**在这里取（求值器是只读的）。派发点会先看到这个 kind 并
        // 自己抽一次（`exec::eval_amount`）；走到这里说明它被**嵌套**在别的表达式里，
        // 而那是我明确不做的一种形状 —— 响亮拒绝而不是猜一个数。
        "randomInt" => Err(ExprError::RandomNeedsADraw),''')

    # 错误变体
    s = patch(s, '''    /// 认不出值类别的 kind —— 当"不支持的表达式"，绝不猜一个值。''',
'''    /// §281：`randomInt` 出现在一个**只读求值**的位置（嵌套在别的表达式里、或者在显示路径上）。
    ///
    /// 与 `UnsupportedKind` 分开是有意义的诊断：那个是"内核还不懂这个 kind"，这个是
    /// "这个位置抽不了"，而修法完全不同（前者要写实现，后者要改内容或改调用点）。
    RandomNeedsADraw,
    /// 认不出值类别的 kind —— 当"不支持的表达式"，绝不猜一个值。''')
    io.open(P_EXPR, 'w', encoding='utf-8', newline='\n').write(s)

    # ---------------------------------------------------------------- exec：派发点取数
    e = io.open(P_EXEC, encoding='utf-8').read()
    e = patch(e, '''fn eval_amount(
    node: NodeRef<'_>,
    field: &'static str,
    ctx: &ExecContext<'_>,
) -> Result<i32, ExecError> {
    let expression = node.node_field(field)?.ok_or(IrError::Missing(field))?;
    let expr_ctx = ctx.expr_context();
    Ok(expr::eval_int(expression, &expr_ctx)?)
}''','''fn eval_amount(
    node: NodeRef<'_>,
    field: &'static str,
    ctx: &mut ExecContext<'_>,
) -> Result<i32, ExecError> {
    let expression = node.node_field(field)?.ok_or(IrError::Missing(field))?;
    // §281：`randomInt` 只能**在这里**取数 —— 这个函数手上有 `&mut ExecContext`（能推进
    // `random_step`），而 `expr::eval_int` 拿的是 `&CombatState`（只读）。
    //
    // 为什么在派发点抽而不是"先做一遍计划"：计划要跟**节目帧**一起存进续延才能跨挂起，
    // 而"每个数值节点在派发时抽一次"天然只需要一个 `&mut`。代价写在注释里：**嵌套**的
    // `randomInt` 不支持（会响亮拒绝），而真内容只把它放在 `Amount` 上。
    if expression.kind_str() == Ok("randomInt") {
        let (min, max) = random_bounds(expression, ctx)?;
        return Ok(ctx.state.draw_in_range(min, max));
    }
    let expr_ctx = ctx.expr_context();
    Ok(expr::eval_int(expression, &expr_ctx)?)
}

/// §281：`randomInt{Min, Max}` 的两端（都是 int 表达式，**但不许**自己再是 `randomInt`）。
///
/// 两端分开求值、都走 `expr::eval_int`，所以它们可以是 `combatantCounter` / `x.cost` 之类；
/// 而嵌套的 `randomInt` 会在 `eval_int` 里报 `RandomNeedsADraw`（宁可拒绝也不猜）。
fn random_bounds(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
) -> Result<(i32, i32), ExecError> {
    let lo = node.node_field("Min")?.ok_or(IrError::Missing("Min"))?;
    let hi = node.node_field("Max")?.ok_or(IrError::Missing("Max"))?;
    let expr_ctx = ctx.expr_context();
    let min = expr::eval_int(lo, &expr_ctx)?;
    let max = expr::eval_int(hi, &expr_ctx)?;
    Ok((min, max))
}''')
    io.open(P_EXEC, 'w', encoding='utf-8', newline='\n').write(e)
    print('expr::randomInt (loud) + exec draw at dispatch')


main()
