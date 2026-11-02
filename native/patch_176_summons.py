"""§176: the driver assumed the enemy roster is fixed at build time. Splits and summons break that.

Reproduced (kernel test, no browser): a Slime Boss fight driven to its phase split --

    round 11: verdict -3 · err [活跃战斗员 `acid_slime_m#000000` 不在 plan.enemies 里]
    enemies: ["slime_boss=2", "acid_slime_m#000000=10", "spike_slime_s#000001=10"]

`step_end_turn` looks the acting enemy up in `plan.enemies` (a fixed slice of `ENCT` records leaked at
build time) to get its `EACT` actions. A combatant created by `node.createCombatant` (the boss's split,
Reptomancer's daggers, Gremlin Leader's gremlins) is **not** in that slice, so the whole end-turn step
fails -- which in the page looks like "the fight will not advance".

The bug was invisible until §175 made `StartingStatuses` live: `standard.split` / `phase_split` are
starting statuses, so before that the boss never split at all.

Two changes:

1. `Session::exec` accepts `Step<'_>` instead of `Step<'static>` (the kernel's `run_fight` already
   does). That is what lets the driver pass the **local copy** of the acting combatant's id instead of
   a `&'static str` from the plan -- no leaking.
2. A summoned combatant's actions are looked up by its **definition id** across the encounter table
   (`ENCT[*].Enemies[j].Id`), which is where the content keeps an enemy's action list. The rotation is
   the same `Actions[(round - 1) % len]` the kernel uses when no `IntentRule` matches; content-authored
   `IntentRule`s are still applied for encounter members, and summons have none today (slimes, daggers,
   gremlins).
"""
import io

PATH = "kernel/rd-wasm/src/lib.rs"

OLD_EXEC = """    fn exec(&mut self, steps: &[Step<'static>]) -> Result<(), String> {"""
NEW_EXEC = """    // §176: `Step<'_>`, not `Step<'static>` -- the acting enemy may be a **summoned** combatant whose
    // id lives in the state, so the caller has to be able to pass a borrowed id. `run_fight` in the
    // kernel has taken `Step<'_>` all along; only this wrapper was stricter.
    fn exec(&mut self, steps: &[Step<'_>]) -> Result<(), String> {"""

OLD_LOOKUP = """            let raw_id: &'static str = self
                .plan
                .enemies
                .iter()
                .map(|enemy| enemy.id)
                .find(|id| *id == active.as_str())
                .ok_or_else(|| format!("活跃战斗员 `{}` 不在 plan.enemies 里", active.as_str()))?;
            let action = self.action_for(&active)?;"""

NEW_LOOKUP = """            // `active` is a **copy** (`CombatantId` is `Copy`), so borrowing its text here does not
            // borrow the state that `exec` mutates below.
            let raw_id: &str = active.as_str();
            let action = self.action_for(&active)?;"""

OLD_ACTION_FOR = """    /// The `EACT` id this combatant will use **now** (nil = no authored action).
    fn action_for(&self, actor: &CombatantId) -> Result<Option<&'static str>, String> {
        let at = locate_enemy(self.content, self.encounter, actor)
            .map_err(|error| format!("locate_enemy: {}", detail(&error)))?
            .ok_or_else(|| format!("`{}` 不在这条遭遇的敌人名单里", actor.as_str()))?;
        let choice = select_action(&self.state, self.content, at, actor, self.state.current_round)
            .map_err(|error| format!("select_action: {}", detail(&error)))?;
        Ok(choice.map(|choice| choice.action_id))
    }"""

NEW_ACTION_FOR = """    /// The `EACT` id this combatant will use **now** (nil = no authored action).
    ///
    /// §176: a combatant created by `node.createCombatant` (split / summon) is not in this encounter's
    /// enemy list, so the encounter-indexed selector cannot answer for it. Its actions come from the
    /// content's enemy records by **definition id** (`ENCT[*].Enemies[j].Id`), and the rotation is the
    /// same `Actions[(round - 1) % len]` the kernel falls back to when no `IntentRule` matches.
    fn action_for(&self, actor: &CombatantId) -> Result<Option<&'static str>, String> {
        if let Some(at) = locate_enemy(self.content, self.encounter, actor)
            .map_err(|error| format!("locate_enemy: {}", detail(&error)))?
        {
            let choice =
                select_action(&self.state, self.content, at, actor, self.state.current_round)
                    .map_err(|error| format!("select_action: {}", detail(&error)))?;
            return Ok(choice.map(|choice| choice.action_id));
        }
        let actions = self.summoned_actions(actor)?;
        if actions.is_empty() {
            return Ok(None);
        }
        let round = self.state.current_round.max(1) as usize;
        Ok(actions.get((round - 1) % actions.len()).copied())
    }

    /// The action list an encounter record gives for this combatant's **definition id** (§176).
    ///
    /// Scanning every encounter is cheap (27 rows, each a handful of records) and it is the only place
    /// the content keeps "which actions does this monster have": the image has no monster table.
    fn summoned_actions(&self, actor: &CombatantId) -> Result<Vec<&'static str>, String> {
        let Some(combatant) = self.state.combatant(actor) else {
            return Ok(Vec::new());
        };
        let definition = combatant.definition_id.as_str();
        // `ENCT` is a fixed table: walk it with `Encounter` rows until one is absent.
        let encounters = self
            .content
            .section(rd_core::content::S_ENCT)
            .map_or(0, |section| section.count);
        for index in 0..encounters {
            let Ok(enemies) = self.content.encounter_enemies(index as u32) else {
                continue;
            };
            for spec in enemies.iter() {
                let Ok(spec) = spec else { continue };
                if spec.id().ok() != Some(definition) {
                    continue;
                }
                let Ok(list) = spec.actions() else { continue };
                let mut out = Vec::with_capacity(list.len());
                for slot in 0..list.len() {
                    if let Some(action) = list.string(slot) {
                        out.push(action);
                    }
                }
                if !out.is_empty() {
                    return Ok(out);
                }
            }
        }
        Ok(Vec::new())
    }"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in [(OLD_EXEC, NEW_EXEC), (OLD_LOOKUP, NEW_LOOKUP), (OLD_ACTION_FOR, NEW_ACTION_FOR)]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("summoned/split combatants can act")


if __name__ == "__main__":
    main()
