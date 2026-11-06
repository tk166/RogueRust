"""§249 内核：把 `abs` / `negate` / `remainder` / `clamp` 从"表里有、没实现"变成实现。

## 为什么以前留空 —— 以及为什么现在能填

`expr.rs` 模块头原本写着：这四条"镜像里一条都没有，字段名（`Operand` / `Inner` /
`Value,Min,Max`）无法用真实数据核实，编一个字段名就是编一个语义"。

那条纪律是对的，但**结论下早了**：核实字段名的来源不只是镜像，还有**参考实现源码**
（`ref/RogueDeck-Core/.../EffectProgramExpressions.cs`，本地只读浅克隆）。四条的真名是：

| kind | 参考类（行号） | 字段 | 语义 |
|---|---|---|---|
| `abs` | `AbsExpression` `:219` | `Operand` | `Saturate(Math.Abs((long)operand))` |
| `negate` | `NegateExpression` `:532` | `Operand` | `Saturate(-(long)operand)` |
| `remainder` | `RemainderExpression` `:587` | `Dividend` `Divisor` `ZeroPolicy` | `dividend % divisor`，除零按策略 |
| `clamp` | `ClampExpression` `:622` | `Value` `Min` `Max` | `Math.Clamp(value, min, max)` |

⚠️ `remainder` 的战斗层拼法是 `{Dividend, Divisor, ZeroPolicy}`（与 `divide` 同族），
而 run 层那一族是 `{Left, Right}` —— 与 `divide` 的处理方式保持一致：**先看 `Dividend`
有没有值，再退回 `Left`**。`divide` 已经这么干了（`expr.rs:846-864`），这里照抄那个形状，
所以"两套拼法"不需要新机制。

`ZeroPolicy` 的语义与 `divide` 完全复用同一个 [`zero_policy`]：缺席 = `ReturnZero`，
`Fault` = 抛 `DivideByZero`，不认识的串 = `UnsupportedKind`（不猜）。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/expr.rs'

# 1) 模块头那张"不支持"清单里删掉这四条（它们实现了），并留下为什么改口的说明。
OLD_DOC = '''//! * `abs` / `negate` / `remainder` / `clamp` —— 参考实现里有（`EffectProgramExpressions.cs:219/532/587/622`），
//!   但**镜像里一条都没有**，字段名（`Operand` / `Inner` / `Value,Min,Max`）无法用真实数据核实，
//!   编一个字段名就是编一个语义 —— 所以留 `UnsupportedKind`。'''
NEW_DOC = '''//! * ~~`abs` / `negate` / `remainder` / `clamp`~~ —— **§249 起已实现**。原先留空是因为
//!   "镜像里一条都没有，字段名无法核实"，但核实字段名的来源不止镜像：参考实现源码就在
//!   `ref/RogueDeck-Core/.../EffectProgramExpressions.cs`，四条的真名与语义都读得到
//!   （`AbsExpression:219` / `NegateExpression:532` / `RemainderExpression:587` /
//!   `ClampExpression:622`）。这四条现在走饱和算术，与 `add`/`subtract` 同一族。'''

# 2) `eval_int` 的分派：在 `"divide"` 之后接上四条。
OLD_DISPATCH = '''        "divide" => divide(node, ctx),
'''
NEW_DISPATCH = '''        "divide" => divide(node, ctx),

        // §249：单操作数两条（`Operand`）。饱和，与参考的 `Saturate(...)` 逐字一致。
        "abs" => {
            let operand = eval_int(child(node, "Operand")?, ctx)?;
            // `Math.Abs((long)int.MinValue)` = 2_147_483_648 ⇒ 饱和回 `i32::MAX`（`:235`）。
            Ok(saturate(i64::from(operand).abs()))
        }
        "negate" => {
            let operand = eval_int(child(node, "Operand")?, ctx)?;
            Ok(saturate(-i64::from(operand)))
        }

        // §249：`remainder` 与 `divide` 同族 —— 战斗层 `{Dividend,Divisor,ZeroPolicy}`，
        // run 层 `{Left,Right}`；字段表是并集，所以判据是"这个键有没有值"。
        "remainder" => remainder(node, ctx),

        // §249：`Math.Clamp(value, min, max)`。参考**先算三个操作数**再钳（`:643-646`），
        // 求值序是 `Value` → `Min` → `Max`。
        "clamp" => {
            let value = eval_int(child(node, "Value")?, ctx)?;
            let min = eval_int(child(node, "Min")?, ctx)?;
            let max = eval_int(child(node, "Max")?, ctx)?;
            // `Math.Clamp` 在 `min > max` 时**抛**（`ArgumentException`）。冻结的 `ExprError`
            // 没有"参数非法"这个变体，落进 `UnsupportedKind` 是响亮的口袋（同 `zero_policy`
            // 处理坏枚举值的做法）。绝不悄悄交换两者：那是编一条参考没有的规则。
            if min > max {
                return Err(ExprError::UnsupportedKind);
            }
            Ok(value.clamp(min, max))
        }
'''

# 3) 两个辅助函数，放在 `run_divide` 之后（同一族，读起来连着）。
ANCHOR_HELPER = '''/// 读 `ZeroPolicy`。**缺席 = 默认 `ReturnZero`**'''
HELPERS = '''/// 战斗层 `remainder`（`RemainderExpression.Evaluate`，`EffectProgramExpressions.cs:606-616`）。
///
/// 参考先算**除数**、判零，再算被除数（与 `divide` 同一个顺序，`:570-581` vs `:606-616`）：
/// 除数为 0 且策略是 `Fault` 时**被除数根本没被求值** —— 那个顺序是可观察的（`card.*`
/// 求值可能带副作用/失败）。
fn remainder<'c>(node: NodeRef<'c>, ctx: &ExprContext<'_>) -> Result<i32, ExprError> {
    if let Some(dividend_node) = node.node_field("Dividend")? {
        let divisor = eval_int(child(node, "Divisor")?, ctx)?;
        let policy = zero_policy(node)?;
        if divisor == 0 {
            return match policy {
                ZeroPolicy::ReturnZero => Ok(0),
                ZeroPolicy::Fault => Err(ExprError::DivideByZero),
            };
        }
        let dividend = eval_int(dividend_node, ctx)?;
        // C# 的 `int % int` 在 `int.MinValue % -1` 上是 `0`（.NET 定义），
        // i64 里算同样得 0，所以饱和只防"病态"不改变语义。
        return Ok(saturate(i64::from(dividend) % i64::from(divisor)));
    }
    // run 层拼法：`{Left, Right}`，没有 `ZeroPolicy`（除零直接抛，同 `run_divide`）。
    if let Some(left_node) = node.node_field("Left")? {
        let divisor = eval_int(child(node, "Right")?, ctx)?;
        if divisor == 0 {
            return Err(ExprError::DivideByZero);
        }
        let dividend = eval_int(left_node, ctx)?;
        return Ok(dividend % divisor);
    }
    Err(ExprError::Ir(IrError::Missing("Dividend")))
}

'''


def patch():
    src = io.open(PATH, encoding='utf-8').read()
    for old, new, label in (
            (OLD_DOC, NEW_DOC, 'module doc'),
            (OLD_DISPATCH, NEW_DISPATCH, 'eval_int dispatch'),
            (ANCHOR_HELPER, HELPERS + ANCHOR_HELPER, 'helpers')):
        assert src.count(old) == 1, (label, src.count(old))
        src = src.replace(old, new)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src)
    print('patched expr.rs: 4 kinds')


patch()
