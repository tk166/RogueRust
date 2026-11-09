"""§313（一·修）：编译错误的四处收尾。

1. `ConditionKind::ALL` 12 → 13；
2. `Combatant` 没有 `is_alive()`，用 `lifecycle_state == Alive`（与 `targets::is_alive` 同一判据，
   它是私有函数，不能跨模块用）；
3. `definition_id.as_str()` 是 `&str`、池里的是 `&[u8]` ⇒ 比 `as_bytes()`；
4. `node_cardinality` 的穷尽 match 要加一支（`DefinitionFilter` 与 `StatusFilter` 同基数）。
"""
import io

TARGETS = 'D:/Vibe/sts-tui/kernel/rd-core/src/targets.rs'
INTENT = 'D:/Vibe/sts-tui/kernel/rd-core/src/intent.rs'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    patch(INTENT, 'pub const ALL: [ConditionKind; 12] = [', 'pub const ALL: [ConditionKind; 13] = [')
    patch(INTENT, '''                if combatant.team_id != team || !combatant.is_alive() {''',
'''                if combatant.team_id != team
                    || combatant.lifecycle_state != crate::state::CombatantLifecycleState::Alive
                {''')

    patch(TARGETS, '''                is_alive(c) && c.definition_id.as_str() == definition''',
'''                is_alive(c) && c.definition_id.as_str().as_bytes() == definition''')

    patch(TARGETS, '''        // `:303` WithStatus（含 `IncludeFallen: true` 的那一半，同一个类、同一个默认值）/
        // `:437` WithoutStatus —— 都吃默认值 ZeroOrMore。
        SelectorNode::StatusFilter { .. } => Cardinality::ZeroOrMore,''',
'''        // `:303` WithStatus（含 `IncludeFallen: true` 的那一半，同一个类、同一个默认值）/
        // `:437` WithoutStatus —— 都吃默认值 ZeroOrMore。
        SelectorNode::StatusFilter { .. } => Cardinality::ZeroOrMore,
        // §313：按定义筛是"筛"不是"选" —— 基数只会变小，所以与 `StatusFilter` 同一个默认值。
        SelectorNode::DefinitionFilter { .. } => Cardinality::ZeroOrMore,''')
    print('fixups applied')


main()
