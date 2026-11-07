"""§271 wasm：`clear_tea_set`（开战兑现之后）+ `toy_ornithopter`（用药水回 5 血）。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


HEAL = '''/// §271：`toy_ornithopter` —— "Whenever you use a potion, heal 5 HP"。
///
/// ⚠️ 回的是**战斗里**的血，不是 `run.health`：一场战斗的 HP 在战斗状态里，结束时才折回运行层
/// （见 `fight_end`）。改运行层那一份会被折回覆盖 —— 玩家看不到回血，而且没有任何地方会报错。
/// 所以这里只在"战斗里且英雄还活着"时动手；不在战斗里就是**不做事**（药水只能在战斗中喝）。
fn heal_on_potion_use() {
    let Some(session) = crate::slot().as_mut() else {
        return;
    };
    let Some(amount) = relic_amount(&session.state, "toy_ornithopter", 5) else {
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

/// §271：某件遗物带的那个数字（`toy_ornithopter` 的 5）。
///
/// 遗物的参数只在 `rd-run` 的遗物表里，所以这里问它、而不是在 wasm 里再写一个 5。
fn relic_amount(state: &rd_run::state::RunState, relic: &str, _fallback: i32) -> Option<i32> {
    use rd_run::state::RelicEffect;
    if !state.relics().iter().any(|held| held.as_str() == relic) {
        return None;
    }
    match rd_run::state::RunState::relic_effect(relic) {
        Some(RelicEffect::PotionUseHeal(amount)) => Some(amount),
        _ => None,
    }
}

'''


def main():
    src = io.open(P, encoding='utf-8').read()

    # ① 两个助手（放在 consume_used_potion 之前）
    src = patch(src, 'fn consume_used_potion(slot: i32) -> i32 {',
                HEAL + 'fn consume_used_potion(slot: i32) -> i32 {', 'helpers')

    # ② `consume_used_potion` 成功之后回血
    src = patch(src, '''    match run.state.drop_potion(slot as usize) {
        Ok(()) => 0,''',
                '''    match run.state.drop_potion(slot as usize) {
        // §271：药水**真的**用掉了才回血（`drop_potion` 是这一步的唯一成功判据）。
        Ok(()) => {
            heal_on_potion_use();
            0
        }''', 'consume hook')

    # ③ 开战：应用完加成之后清掉 tea_set
    src = patch(src, '''    let bonus = session.state.combat_bonus_for(fight_kind);''',
                '''    let bonus = session.state.combat_bonus_for(fight_kind);
    // §271：`ancient_tea_set` —— 加成**已经算出来**，现在才允许清掉"欠一场"。
    // ⚠️ 顺序反了（先清再算）它就永远读不到，`ancient_tea_set` 变成一件什么都不做的遗物，
    // 而所有判据仍然绿 —— 没有任何东西"错"。
    session.state.clear_tea_set();''', 'clear tea set')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('run.rs: potion heal + tea set consume')


main()
