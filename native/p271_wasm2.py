"""§271 wasm 修正：`heal_on_potion_use` 用对了两个 slot（`run_slot` = 运行层，`slot` = 战斗）。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def main():
    src = io.open(P, encoding='utf-8').read()

    start = src.index('fn heal_on_potion_use() {')
    end = src.index('/// §271：某件遗物带的那个数字', start)
    new = '''fn heal_on_potion_use() {
    // 两个 slot 各管一件事：**运行层**认识遗物，**战斗层**认识血量。混用会得到一个
    // "编译不过"（第一次就这么写的：`&session.state` 是 `&Box<CombatState>`）。
    let Some(amount) = run_slot()
        .as_ref()
        .and_then(|run| relic_amount(&run.state, "toy_ornithopter"))
    else {
        return;
    };
    let Some(session) = crate::slot().as_mut() else {
        return;
    };
    let Some(hero) = session.hero_id() else {
        return;
    };
    if let Some(combatant) = session.state.combatant_mut(&hero) {
        let healed = (combatant.health_current + amount).min(combatant.health_max);
        combatant.health_current = healed;
    }
    session.reobserve_after_external_change();
}

'''
    src = src[:start] + new + src[end:]

    # `relic_amount` 去掉没用的 fallback 参数
    src = patch(src, '''fn relic_amount(state: &rd_run::state::RunState, relic: &str, _fallback: i32) -> Option<i32> {''',
                '''fn relic_amount(state: &rd_run::state::RunState, relic: &str) -> Option<i32> {''',
                'relic_amount signature')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('heal_on_potion_use fixed')


main()
