"""§180 exec side: read `DeathPrevention` at the death point.

Where: after Block / Buffer / Plated Armor have run and health has landed on 0, but **before** the
combatant turns `Downed` -- the reference intercepts exactly there
(`SandboxInterceptors.cs:48-56` returns `Prevent(max(1, SurvivingHealth))` from a `PreDownInterceptor`
that the downed-marking handler consults).
"""
import io

EXEC = "kernel/rd-core/src/exec.rs"

ANCHOR = """    // S8 的 `DamageDealt` 事件 → `MarkCombatantDownedOnZeroHealthHandler`"""

NEW = r'''    // ── S6d：**`DeathPrevention`**（§180）—— 参考的 `IPreDownInterceptor` 这一半。
    //
    // 位置是**语义**：这一下已经穿过格挡、Buffer、Plated Armor，血量确实落到 0，但**还没**转
    // `Downed`。参考的拦截点就在这里。
    //
    // 代价是这一下要**重新读一遍**持有者的状态：上面已经读过一次（伤害修饰），但中间那几个
    // 处理器会改状态表，所以"读到的那一份"不能复用。
    if health_lost > 0 && health_after == 0 {
        if let Some((definition, surviving, repeats)) = death_prevention_for(ctx, target)? {
            health_after = surviving;
            health_lost = health_after.saturating_sub(health_before).max(0);
            // `Repeating` 的才留下；其余是"一次性护符"（wiki 的 Fairy in a Bottle: "works once"）。
            // ⚠️ `false` 时**必须真的摘掉**：留着它，下一次致命伤还会被同一个状态救 ——
            // 那就是 `Repeating` 的语义，而不是这瓶药的。
            if !repeats {
                let mut buffer = [0u8; 64];
                let text = definition.as_str();
                buffer[..text.len()].copy_from_slice(text.as_bytes());
                if let Ok(name) = core::str::from_utf8(&buffer[..text.len()]) {
                    let _ = consume_one_status_stack(ctx.state, target, name)?;
                }
            }
        }
    }

    // S8 的 `DamageDealt` 事件 → `MarkCombatantDownedOnZeroHealthHandler`'''

HELPERS_ANCHOR = """fn carries_status(state: &CombatState, id: &CombatantId, definition: &str) -> bool {"""

HELPERS = r'''/// 读一个战斗员身上**能救命**的那条 `DeathPrevention` 状态（§180）。
///
/// 返回 `(状态 id, 这一下之后剩多少血, 是否重复)`。`None` = 他身上没有这类状态，或者内容里
/// 那条数据读不出来 —— 两种都走"照常倒下"。
///
/// ⚠️ 这不是"静默降级"：这条分支只在**血量已经到 0** 时被调用，它的输出是"活下来还是死"；
/// 而"内容里的 `DeathPrevention` 写坏了"该由 `the_status_catalogue_is_honest` 在构建期喊，
/// 不该在一场战斗的最后一下里抛异常（那时候状态已经改了一半）。
///
/// 血量公式：`max(SurvivingHealth, 最大生命 * Percent / 100, 1)`。`Percent` 是本移植的扩展 ——
/// 参考的 `StatusDeathPreventionData` 只有平值，表达不了 wiki 的 "30% of Max HP"。
fn death_prevention_for(
    ctx: &ExecContext<'_>,
    target: &CombatantId,
) -> Result<Option<(crate::state::StatusDefinitionId, i32, bool)>, ExecError> {
    let Some(content) = ctx.content else {
        return Ok(None);
    };
    let Some(combatant) = ctx.state.combatant(target) else {
        return Ok(None);
    };
    let max_health = combatant.health_max;
    // Copy the definitions out first: the loop below reads the *content*, and holding a borrow of
    // the combatant's status list across that would tie two unrelated lifetimes together.
    let mut candidates = [crate::state::StatusDefinitionId::EMPTY; 16];
    let mut count = 0usize;
    for status in combatant.statuses() {
        if count == candidates.len() {
            break;
        }
        if status.stacks <= 0 {
            continue;
        }
        candidates[count] = status.definition_id;
        count += 1;
    }
    for definition in &candidates[..count] {
        let mut buffer = [0u8; 64];
        let text = definition.as_str();
        if text.len() >= buffer.len() {
            continue;
        }
        buffer[..text.len()].copy_from_slice(text.as_bytes());
        let Ok(name) = core::str::from_utf8(&buffer[..text.len()]) else {
            continue;
        };
        let Ok(Some(data)) = crate::status_bind::death_prevention(content, name) else {
            continue;
        };
        let percent = max_health.saturating_mul(data.percent) / 100;
        let surviving = data.surviving_health.max(percent).max(1);
        return Ok(Some((*definition, surviving, data.repeating)));
    }
    Ok(None)
}

fn carries_status(state: &CombatState, id: &CombatantId, definition: &str) -> bool {'''


def main():
    text = io.open(EXEC, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    text = text.replace(ANCHOR, NEW)
    assert text.count(HELPERS_ANCHOR) == 1, text.count(HELPERS_ANCHOR)
    text = text.replace(HELPERS_ANCHOR, HELPERS)
    io.open(EXEC, "w", encoding="utf-8", newline="").write(text)
    print("§180 exec side inserted")


if __name__ == "__main__":
    main()
