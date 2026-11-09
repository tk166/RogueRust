"""§313（七）：表达式 `combatantCount` —— "这个选择器解出几个（活着的）战斗员"。

`Protect` 的"独自时给自己 15 块"需要在**动作程序里**判断"友军只剩我一个"，而
`intent.enemyAliveCount` 是**意图规则**的条件（`intent::condition_matches` 里求值），
在程序里求值会撞 `Expr(UnsupportedKind)` —— 实测过一次。

所以补一个表达式 kind，形状照邻居：`{ "Selector": …, "AliveOnly": true }`。
`AliveOnly` 缺省 **true**（"数得出来的人"是活着的；写 false 要显式说）。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/expr.rs'

KINDS_OLD = '''    "combatantZoneCount",'''
KINDS_NEW = '''    "combatantZoneCount",
    // §313：选择器解出几个战斗员（`Protect` 的"独自时自保"）。**允许多个目标** ——
    // 与 `currentHealth` 那些单目标读相反，数的就是个数。
    "combatantCount",'''

EVAL_OLD = '''        // §247: how many cards are in a zone right now (Mind Blast).'''
EVAL_NEW = '''        // §313: 选择器解出几个战斗员（`AliveOnly` 缺省 true）。
        //
        // 为什么是**表达式**而不是意图条件：`Protect` 的"独自 vs 有 Mystic"写在**动作程序**里，
        // 而 `intent.enemyAliveCount` 只在意图规则的条件求值器里存在 —— 程序里用它会被
        // `expr.rs` 判成 `UnsupportedKind`（这一轮实测撞过一次）。
        "combatantCount" => {
            let alive_only = node.bool_field("AliveOnly")?.unwrap_or(true);
            let selector = child(node, "Selector")?;
            let mut buf = [CombatantId::EMPTY; MAX_COMBATANTS];
            let compiled = CompiledSelector::compile(selector)?;
            let selection = ctx.selection();
            let count = compiled
                .resolve(&selection, &mut buf)
                .map_err(|_| ExprError::Sel(SelError::TableFull))?;
            if !alive_only {
                return Ok(i32::try_from(count).unwrap_or(i32::MAX));
            }
            let mut alive = 0;
            for id in buf.iter().take(count) {
                if ctx
                    .state
                    .combatant(id)
                    .is_some_and(|c| c.lifecycle_state == crate::state::CombatantLifecycleState::Alive)
                {
                    alive += 1;
                }
            }
            Ok(alive)
        }

        // §247: how many cards are in a zone right now (Mind Blast).'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(KINDS_OLD) == 1
    text = text.replace(KINDS_OLD, KINDS_NEW)
    assert text.count(EVAL_OLD) == 1
    text = text.replace(EVAL_OLD, EVAL_NEW)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text)
    print('combatantCount added')


main()
