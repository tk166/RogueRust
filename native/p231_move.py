"""§231 (part 1c): 把 `standard.no_draw` 的规则从**节点**挪到**请求处理器**。

节点的位置是错的：抽牌药水（`rd_env_use_potion` 里那条 `EffectRequest::DrawCards`）不经过
`node.drawCards`，于是"本回合不能再抽"会被它绕过 —— 而 StS 里那张药水同样抽不到。
一处规则，一处实现：写在 `resolve_request` 的 `DrawCards` 分支里。
"""
import io

EXEC = 'kernel/rd-core/src/exec.rs'
src = io.open(EXEC, encoding='utf-8').read()

# ① 请求处理器：拦下所有抽牌请求
old = '''        EffectRequest::DrawCards { owner, count } => draw_for(ctx, &owner, count),'''
new = '''        // §231: `standard.no_draw` (Battle Trance) is honoured **here**, not in the node: a draw is a
        // draw whether it came from `node.drawCards` or from a potion's `EffectRequest::DrawCards`.
        // "Additional cards" excludes the turn-start draw, which never goes through this request.
        EffectRequest::DrawCards { owner, count } => {
            let blocked = ctx.state.combatant(&owner).is_some_and(|combatant| {
                combatant
                    .statuses()
                    .iter()
                    .filter(|instance| instance.definition_id.as_str() == "standard.no_draw")
                    .fold(0i32, |sum, instance| sum.saturating_add(instance.stacks))
                    > 0
            });
            draw_for(ctx, &owner, if blocked { 0 } else { count })
        }'''
assert src.count(old) == 1, ('handler', src.count(old))
src = src.replace(old, new)

# ② 节点：把刚才那一半删掉（并保留"为什么不在这一层"的一行说明）
old = '''    // §231: `standard.no_draw` (Battle Trance) -- while it is present, an **effect-driven** draw
    // draws nothing. The turn-start draw goes through `turn::start_current_turn`, not through this
    // node, so "additional" stays exactly what the card says.
    let blocked = draw_is_blocked(ctx, selector)?;
'''
new = '''    // §231: `standard.no_draw` is enforced in `resolve_request`, **not here** -- a draw is a draw
    // whether it came from this node or from a potion's `EffectRequest::DrawCards`.
'''
assert src.count(old) == 1, ('node-comment', src.count(old))
src = src.replace(old, new)

old = '''                count: if blocked { 0 } else { count },'''
new = '''                count,'''
assert src.count(old) == 1, ('node-count', src.count(old))
src = src.replace(old, new)

# ③ 不再有人用的辅助函数删掉
start = src.index('/// §231：这批抽牌的目标身上有 `standard.no_draw` 吗（`Battle Trance`）。')
end = src.index('/// §231：`node.dealDamageAndHealByLoss` 的实体')
src = src[:start] + src[end:]

io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)
print('ok moved')
