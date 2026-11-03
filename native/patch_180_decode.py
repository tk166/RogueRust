"""§180 part 2: decode `STAT.DeathPrevention` and use it at the death point.

`status_bind::death_prevention(content, status_id) -> Option<DeathPreventionData>` reads the term the
status row already carries:

    {"SurvivingHealth": <int>?, "Percent": <int>?, "Repeating": <bool>?}

`Percent` is our extension (the reference's record only has a flat `SurvivingHealth`, so a
"30% of Max HP" charm cannot be expressed there -- and StS's Fairy in a Bottle is exactly that).
"""
import io

BIND = "kernel/rd-core/src/status_bind.rs"
EXEC = "kernel/rd-core/src/exec.rs"

BIND_ANCHOR = """pub fn decode_required<'a>("""

BIND_NEW = r'''/// A status' **death-prevention** data (`STAT.DeathPrevention`, §180).
///
/// Mirrors the reference's `StatusDeathPreventionData(SurvivingHealth, Effects, Repeating)`, plus
/// `Percent`: the reference cannot express StS's "heal to 30% of your Max HP", and a flat number
/// would either be wrong for every other max HP or need one row per hero.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct DeathPreventionData {
    /// Survive at (at least) this many HP.
    pub surviving_health: i32,
    /// ...and at least this percentage of the bearer's max HP. `0` = not used.
    pub percent: i32,
    /// Whether the status **stays** after saving its bearer. `false` = the one-shot charm.
    pub repeating: bool,
}

/// Read `DeathPrevention` off a status row.
///
/// `Ok(None)` = the row exists and the field is null (most statuses -- 25 of 25 before §180).
/// `Err` = the row or the data is malformed, which a caller must **not** treat as "no prevention":
/// that is the silent-shape failure `§161.3` is about.
pub fn death_prevention(
    content: &Content<'_>,
    status_id: &str,
) -> Result<Option<DeathPreventionData>, BindError> {
    let row = status_row(content, status_id).ok_or(BindError::Missing("STAT row"))?;
    let cell = row.death_prevention();
    if cell == ABSENT16 || cell == NULL16 {
        return Ok(None);
    }
    let node = NodeRef::new(content, cell);
    let surviving_health = node.int_field("SurvivingHealth")?.unwrap_or(0);
    let percent = node.int_field("Percent")?.unwrap_or(0);
    let repeating = node.bool_field("Repeating")?.unwrap_or(false);
    Ok(Some(DeathPreventionData {
        surviving_health,
        percent,
        repeating,
    }))
}

pub fn decode_required<'a>('''

EXEC_FIX_OLD = r'''        let Ok(Some(data)) = crate::status_bind::death_prevention(content, text) else {
            continue;
        };
        let percent = max_health.saturating_mul(data.percent) / 100;
        let surviving = data.surviving_health.max(percent).max(1);
        return Ok(Some((definition.as_str_static(), surviving)));'''
EXEC_FIX_NEW = r'''        let Ok(Some(data)) = crate::status_bind::death_prevention(content, text) else {
            continue;
        };
        let percent = max_health.saturating_mul(data.percent) / 100;
        let surviving = data.surviving_health.max(percent).max(1);
        // The **id**, not a `&str`: the borrow above belongs to the combatant's status list, and
        // the caller needs the name after it has already consumed a stack.
        return Ok(Some((*definition, surviving)));'''

SIG_OLD = '''fn death_prevention_for(
    ctx: &ExecContext<'_>,
    target: &CombatantId,
) -> Result<Option<(&'static str, i32)>, ExecError> {'''
SIG_NEW = '''fn death_prevention_for(
    ctx: &ExecContext<'_>,
    target: &CombatantId,
) -> Result<Option<(crate::state::StatusDefinitionId, i32)>, ExecError> {'''

CALL_OLD = '''            let keep = death_prevention_repeats(ctx, target)?;
            if !keep {
                let _ = consume_one_status_stack(ctx.state, target, definition)?;
            }'''
CALL_NEW = '''            let keep = death_prevention_repeats(ctx, target)?;
            if !keep {
                // The name is needed **twice**: once to read the data (above) and once to consume
                // the stack (here). `StatusDefinitionId` is `Copy` and fixed-size, so keeping it
                // avoids a second, subtly different lookup.
                let text = {
                    let mut buffer = [0u8; 64];
                    let name = definition.as_str();
                    buffer[..name.len()].copy_from_slice(name.as_bytes());
                    buffer
                };
                let length = definition.as_str().len();
                if let Ok(name) = core::str::from_utf8(&text[..length]) {
                    let _ = consume_one_status_stack(ctx.state, target, name)?;
                }
            }'''


def main():
    text = io.open(BIND, encoding="utf-8").read()
    assert text.count(BIND_ANCHOR) == 1, text.count(BIND_ANCHOR)
    io.open(BIND, "w", encoding="utf-8", newline="").write(text.replace(BIND_ANCHOR, BIND_NEW))

    exec_text = io.open(EXEC, encoding="utf-8").read()
    for old, new in [(SIG_OLD, SIG_NEW), (EXEC_FIX_OLD, EXEC_FIX_NEW), (CALL_OLD, CALL_NEW)]:
        assert exec_text.count(old) == 1, (exec_text.count(old), old[:60])
        exec_text = exec_text.replace(old, new)
    io.open(EXEC, "w", encoding="utf-8", newline="").write(exec_text)
    print("§180 decoder + call site wired")


if __name__ == "__main__":
    main()
