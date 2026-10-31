"""rd-wasm: the §161.3 choice ABI (pending / kind / min / max / pick / selected / confirm / clear).

Also: zone id 3 means "the pending choice's source pile", `compute_actions` is empty while a choice
is pending, and `rd_env_step` refuses while one is.

Every anchor is asserted unique, so re-running this is a loud failure rather than a second copy.
"""
import io

PATH = "kernel/rd-wasm/src/lib.rs"


def sub(text, old, new, count=1):
    assert text.count(old) == count, (text.count(old), old[:60])
    return text.replace(old, new)


def main():
    text = io.open(PATH, encoding="utf-8").read()

    # ---- 1. Session field -------------------------------------------------------------------
    text = sub(
        text,
        """    /// Reward for the last step, in 1/1000 (`env-abi.md` §7 + §10's "wasted energy" ruling).
    reward: i32,""",
        """    /// Reward for the last step, in 1/1000 (`env-abi.md` §7 + §10's "wasted energy" ruling).
    reward: i32,
    /// §161.3: which legal options the player has ticked in the pending card choice.
    ///
    /// **UI scratch, not game state.** The *action* is [`rd_env_choice_confirm`], which hands the
    /// whole selection to the kernel at once; the kernel's [`rd_core::state::resolve_choice`] either
    /// takes it entirely or refuses with nothing changed. Keeping the tick list here rather than in
    /// `CombatState` is what lets the kernel's answer stay atomic -- and it is why a half-finished
    /// selection is not something a save file has to describe.
    choice_picks: Vec<usize>,""",
    )

    text = sub(
        text,
        """        error: String::new(),
        reward: 0,
        before: vec![0; OBS_LEN],""",
        """        error: String::new(),
        reward: 0,
        choice_picks: Vec::new(),
        before: vec![0; OBS_LEN],""",
    )

    # ---- 2. compute_actions: empty while a choice is pending --------------------------------
    text = sub(
        text,
        """    fn compute_actions(&self) -> Vec<Action> {
        let mut actions = Vec::new();
        if self.is_done() {
            return actions;
        }""",
        """    fn compute_actions(&self) -> Vec<Action> {
        let mut actions = Vec::new();
        if self.is_done() {
            return actions;
        }
        // §161.3: a pending card choice is a **modal** state. Play/end-turn are not legal until it
        // is answered, so listing them would be a table of actions that all get refused -- and a
        // random driver would spin on `-1` forever while the fight looked alive. An empty table is
        // the honest answer ("nothing you can do until you choose"), and `rd_env_choice_pending`
        // is what tells a driver *why*.
        if self.state.pending_choice().is_some() {
            return actions;
        }""",
    )

    # ---- 3. pile_zone learns id 3 -----------------------------------------------------------
    text = sub(
        text,
        """fn pile_zone(zone: i32) -> Option<CardZone> {
    match zone {
        0 => Some(CardZone::DrawPile),
        1 => Some(CardZone::DiscardPile),
        2 => Some(CardZone::ExhaustPile),
        _ => None,
    }
}""",
        """/// Zone ids, as `ui_render.js` spells them: 0 = draw, 1 = discard, 2 = exhaust, **3 = the
/// pending card choice's source pile** (§161.3).
///
/// Id 3 is dynamic on purpose: the picker renders the same card faces the pile viewer does, and a
/// fourth static pile would have to be kept in sync with "which pile is the question about". The
/// one thing a caller must know is that id 3 answers **nothing** when no choice is pending, which
/// is why it returns `None` instead of an empty pile.
fn pile_zone(session: &Session, zone: i32) -> Option<CardZone> {
    match zone {
        0 => Some(CardZone::DrawPile),
        1 => Some(CardZone::DiscardPile),
        2 => Some(CardZone::ExhaustPile),
        3 => session.state.pending_choice().map(|choice| choice.source.zone()),
        _ => None,
    }
}""",
    )

    # every call site of pile_zone gains the session
    text = sub(
        text,
        """    let Some(zone) = pile_zone(zone) else {
        return -1;
    };
    let Some(hero) = session.hero_id() else {
        return -1;
    };""",
        """    let Some(zone) = pile_zone(session, zone) else {
        return -1;
    };
    let Some(hero) = session.hero_id() else {
        return -1;
    };""",
    )
    text = sub(
        text,
        """    let session = ensure_session().ok()?;
    let zone = pile_zone(zone)?;
    let hero = session.hero_id()?;""",
        """    let session = ensure_session().ok()?;
    let zone = pile_zone(session, zone)?;
    let hero = session.hero_id()?;""",
    )

    # ---- 4. rd_env_step refuses while a choice is pending -----------------------------------
    text = sub(
        text,
        """    let Some(action) = session.actions.get(index.max(0) as usize).copied() else {
        return -1;
    };

    session.reobserve();""",
        """    let Some(action) = session.actions.get(index.max(0) as usize).copied() else {
        return -1;
    };
    // §161.3: `compute_actions` is empty while a choice is pending, so this is unreachable through
    // the table -- which is exactly why it is written: a driver holding a **stale** action index
    // would otherwise play a card through the open question.
    if session.state.pending_choice().is_some() {
        session.error = "还有一次待决的选牌没回答".to_string();
        return -1;
    }

    session.reobserve();""",
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("rd-wasm: session field, actions, pile zone, step guard")


if __name__ == "__main__":
    main()
