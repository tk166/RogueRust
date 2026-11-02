"""§175b: enemy `StartingStatuses` are now **applied** -- they never were.

The gap this closes: `content.rs` has decoded `ENCT[*].Enemies[j].StartingStatuses` since the
beginning (it even counts them: "20 records carry StartingStatuses"), and **nothing applied them**.
So Sentries had no Artifact, Gremlin Leader no Enrage, Giant Head no Metallicize, and the Lagavulin
added in §173 had no Metallicize 8 -- all of them inert content.

Found by a test that could not fail for the right reason: Nemesis's "intangible every other turn" is
carried by a status, the isolation test in `rd-core` proved the trigger works, and the fight still
showed *no status at all* on the enemy (`nemesis statuses at start: []`).

The application point is `build_session_at`, right after the fight is built and **before**
`start_first_turn` -- "starting statuses" have to exist when turn 1 begins, or a TurnStarted trigger
(the whole point of Nemesis's carrier) is one turn late.

The spec's fields come from the encounter record (`Stacks` / `DurationTurns` / `Charges` / `Status`),
and they are applied through the **same** `EffectRequest::ApplyStatus` + `exec::drain` path a card or
an enemy action uses -- no second implementation of "add a status".
"""
import io

PATH = "kernel/rd-wasm/src/lib.rs"

ANCHOR = """    start_first_turn(&mut session.state, &standard, &mut session.host)
        .map_err(|e| format!("start_first_turn: {}", detail(&e)))?;
    session.reobserve();"""

NEW = """    // §175b: apply the encounter's `StartingStatuses` **before** the first turn starts.
    apply_starting_statuses(&mut session, content, encounter)?;
    start_first_turn(&mut session.state, &standard, &mut session.host)
        .map_err(|e| format!("start_first_turn: {}", detail(&e)))?;
    session.reobserve();"""

HELPER_ANCHOR = """/// [`build_session_with`], plus the Ascension health bonus for the enemies (§159)."""

HELPER = '''/// Put every enemy's `StartingStatuses` onto it (§175b).
///
/// `ENCT[*].Enemies[j].StartingStatuses` is a list of `{Status, Stacks, DurationTurns, Charges}`
/// specs. Nothing applied them before this: Sentries had no Artifact, Gremlin Leader no Enrage,
/// Giant Head no Metallicize, Lagavulin no Metallicize 8. The content layer had been *counting* them
/// since §1 -- a number that was checked while the behaviour was missing.
///
/// Applied through `EffectRequest::ApplyStatus` + `exec::drain`, i.e. the same path a card or an
/// enemy action takes, so there is no second implementation of "add a status".
fn apply_starting_statuses(
    session: &mut Session,
    content: &'static Content<'static>,
    encounter: u32,
) -> Result<(), String> {
    let enemies = content
        .encounter_enemies(encounter)
        .map_err(|e| format!("encounter_enemies: {}", detail(&e)))?;
    for spec in enemies.iter() {
        let spec = spec.map_err(|e| format!("ENCT enemy record: {}", detail(&e)))?;
        let id = spec.id().map_err(|e| format!("ENCT enemy id: {}", detail(&e)))?;
        let Ok(target) = rd_core::state::CombatantId::new(id) else {
            return Err(format!("`{id}` is not a usable combatant id"));
        };
        let statuses = spec
            .starting_statuses()
            .map_err(|e| format!("StartingStatuses: {}", detail(&e)))?;
        for index in 0..statuses.len() {
            let term = statuses
                .term(index)
                .ok_or_else(|| format!("StartingStatuses[{index}] has no term"))?;
            let node = rd_core::ir::NodeRef::new(content, term);
            // `StatusDefinitionId` is the key the **content** uses (`enc_three_sentries` and friends);
            // `content.rs`'s doc comment said `Status`, which was wrong -- that comment is fixed in the
            // same change. Both spellings are accepted so neither can bite again.
            let status_id = node
                .str_field("StatusDefinitionId")
                .ok()
                .flatten()
                .or_else(|| node.str_field("Status").ok().flatten());
            let Some(status_id) = status_id else {
                return Err(format!(
                    "StartingStatuses[{index}] has neither `StatusDefinitionId` nor `Status`"
                ));
            };
            let Ok(definition) = rd_core::state::StatusDefinitionId::new(status_id) else {
                return Err(format!("`{status_id}` is not a usable status id"));
            };
            let stacks = node.int_field("Stacks").ok().flatten().unwrap_or(1);
            let duration = node.int_field("DurationTurns").ok().flatten().unwrap_or(0);
            let charges = node.int_field("Charges").ok().flatten().unwrap_or(0);
            session
                .state
                .enqueue_effect_with_owner(
                    rd_core::state::EffectRequest::ApplyStatus {
                        target: Some(target),
                        definition,
                        stacks,
                        duration,
                        charges,
                        source: Some(target),
                        source_card: None,
                    },
                    None,
                )
                .map_err(|e| format!("enqueue starting status: {}", detail(&e)))?;
            rd_core::exec::drain(&mut session.state, Some(content), None)
                .map_err(|e| format!("drain starting status: {}", detail(&e)))?;
        }
    }
    Ok(())
}

''' + HELPER_ANCHOR


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in [(ANCHOR, NEW), (HELPER_ANCHOR, HELPER)]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("starting statuses are applied before turn 1")


if __name__ == "__main__":
    main()
