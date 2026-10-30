"""§153: lift the encounter pick out of `fight_begin` into `pick_encounter`, so it can be tested.

The inline version had three problems: it could only be exercised by *starting a fight* (and a test
that fights to the end kills the hero, which stops the walk after one fight -- that is exactly what
the first version of the test hit: `expected several fights, got ["enc_jaw_worm"]`), it mixed three
concerns (weights, no-repeat, bookkeeping), and every `return fail(...)` needed a `Session`.

The function takes the run state + the pool's ids and returns the chosen index; the seed draw that
follows stays in `fight_begin` because it is about the *fight*, not the pick.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-wasm\src\run.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

START = "    // §153: **the weights the content declares**, not a uniform draw."
END = "    session.state.set_last_encounter(encounter_id(encounters[pick]));\n"

start = source.find(START)
end = source.find(END)
if start < 0 or end < 0:
    raise SystemExit("inline block not found")
inline = source[start : end + len(END)]

replacement = """    let pick = match pick_encounter(&mut session.state, content, &pool_name, &encounters) {
        Ok(index) => index,
        Err(message) => return fail(session, &message),
    };
"""

source = source[:start] + replacement + source[end + len(END) :]

HELPER = '''/// Choose which encounter a fight uses (`port-plan.md` §153).
///
/// Three rules, in order:
/// 1. **the content's `Weight`**, not a uniform draw (`Weight: 15/14/14/14/14/14/15` used to be
///    written, validated by the content gate, and then ignored);
/// 2. a pool with no weights at all falls back to uniform (that is what "no `Weight` field" means);
/// 3. **never the same encounter twice in a row** -- one re-roll, not a loop, because a loop over a
///    two-entry pool would turn the pool into a cycle.
fn pick_encounter(
    state: &mut rd_run::state::RunState,
    content: &'static Content<'static>,
    pool_name: &str,
    encounters: &[&'static str],
) -> Result<usize, String> {
    let weights = content.encounter_weights(pool_name);
    let total: u32 = weights
        .as_ref()
        .map_or(0, |table| table.iter().take(encounters.len()).map(|w| u32::from(*w)).sum());
    let mut pick = if total == 0 {
        match state.rng_mut().roll(RunStream::Combat, encounters.len() as u32) {
            Ok(value) => value as usize,
            Err(e) => return Err(describe(&e)),
        }
    } else {
        let roll = match state.rng_mut().roll(RunStream::Combat, total) {
            Ok(value) => value,
            Err(e) => return Err(describe(&e)),
        };
        let mut remaining = roll;
        let mut chosen = encounters.len() - 1;
        for (index, weight) in weights.iter().flatten().take(encounters.len()).enumerate() {
            let weight = u32::from(*weight);
            if weight == 0 {
                continue;
            }
            if remaining < weight {
                chosen = index;
                break;
            }
            remaining -= weight;
        }
        chosen
    };
    if encounters.len() > 1 && encounter_id(encounters[pick]) == state.last_encounter() {
        let again = match state.rng_mut().roll(RunStream::Combat, encounters.len() as u32) {
            Ok(value) => value as usize,
            Err(e) => return Err(describe(&e)),
        };
        if encounter_id(encounters[again]) != state.last_encounter() {
            pick = again;
        }
    }
    state.set_last_encounter(encounter_id(encounters[pick]));
    Ok(pick)
}

'''

anchor = "fn encounter_id(text: &'static str)"
if "fn pick_encounter(" in source:
    print("pick_encounter already present")
else:
    at = source.find(anchor)
    if at < 0:
        raise SystemExit("encounter_id anchor missing")
    source = source[:at] + HELPER + source[at:]
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("pick_encounter inserted; inline block replaced")
