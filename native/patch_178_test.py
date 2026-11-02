"""§178 test: the split must happen **once**, and the roster must not fill up.

The failure shape (from `§177`'s diagnostics, `web-act1_slice`): the Slime Boss sits at `<= 10` HP,
the hero plays a multi-hit turn, and *every* damage instance re-entered `standard.phase_split` because
the guard it had was "remove my own status" -- a **queued request** that had not landed yet. Ten
summons later `MAX_COMBATANTS` (12) was full and the fight threw `Capacity(Full(Combatants))`.

Two tests:
1. `a_phase_split_happens_once_even_under_three_hits` -- the reproduction, asserted on the roster.
2. `destroying_a_combatant_takes_it_out_of_the_roster_and_the_turn_order` -- the primitive itself,
   including the refusal cases (must not mutate).
"""
import io

TESTS = "kernel/rd-core/src/host.rs"

ANCHOR = """    #[test]
    fn a_split_spawns_two_combatants_when_the_boss_dies() {"""

NEW = '''    /// §178: the exact shape of the `§177` freeze -- **three damage instances in one turn** while
    /// the boss is at `<= 10` HP. Before `node.destroyCombatant` each instance split again (the
    /// status removal is a queued request and never wins the race), so this test failed with
    /// `Capacity(Full(Combatants))` after ten summons.
    ///
    /// The judgment is the **roster**, not "it did not throw": a fix that silently swallows the
    /// overflow would also not throw.
    ///
    /// ⚠️ `assert!` rather than `assert_eq!` where the payload is a whole list of combatants -- a
    /// failing `assert_eq!` prints both rosters and nobody reads the second one.
    #[test]
    fn a_phase_split_happens_once_even_under_three_hits() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state
            .add_combatant(unit("hero", "player", 70, 70))
            .unwrap();
        // The boss at 8 HP: one point above the phase threshold, so the first hit takes it under.
        state
            .add_combatant(unit("slime_boss", "enemy", 8, 140))
            .unwrap();
        give(&mut state, "slime_boss", status("st_split", "standard.split", 1));
        give(
            &mut state,
            "slime_boss",
            status("st_phase", "standard.phase_split", 1),
        );
        assert_eq!(state.combatants().len(), 2, "hero + boss to start");

        // Three separate hits, each resolved on its own (that is what "play three attacks" is).
        for _ in 0..3 {
            {
                let mut ctx =
                    crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                        .with_content(&content);
                crate::exec::resolve_damage(&mut ctx, &cid("slime_boss"), 2, false)
                    .expect("a hit on the boss");
            }
            host.try_resolve_pending_queues(&mut state).expect("settle");
        }

        let ids: Vec<&str> = state.combatants().iter().map(|c| c.id.as_str()).collect();
        assert!(
            !ids.contains(&"slime_boss"),
            "the boss is GONE after the phase split, not merely dead: {ids:?}"
        );
        assert!(
            ids.len() <= 3,
            "one split means hero + two slimes, got {} combatants: {ids:?}",
            ids.len()
        );
        assert_eq!(
            state
                .combatants()
                .iter()
                .filter(|c| c.team_id.as_str() == "enemy")
                .count(),
            2,
            "exactly two enemies remain: {ids:?}"
        );
        assert!(
            state.combatants().len() < crate::state::MAX_COMBATANTS,
            "the container must never be the thing that stops the split"
        );
    }

    #[test]
    fn destroying_a_combatant_takes_it_out_of_the_roster_and_the_turn_order() {
        let mut state = arena(); // hero, enemy_a (20), enemy_b (10)
        let before = state.combatants().len();
        let order_before: Vec<&str> = state.turn_order().iter().map(|id| id.as_str()).collect();

        let removed = state
            .remove_combatant(&cid("enemy_a"))
            .expect("remove enemy_a");
        assert_eq!(removed.id.as_str(), "enemy_a");
        assert_eq!(state.combatants().len(), before - 1, "one fewer in the roster");
        let order_after: Vec<&str> = state.turn_order().iter().map(|id| id.as_str()).collect();
        assert_eq!(
            order_after,
            order_before
                .iter()
                .copied()
                .filter(|id| *id != "enemy_a")
                .collect::<Vec<_>>(),
            "the turn order keeps everyone else in the same relative order"
        );
        assert!(state.combatant(&cid("enemy_a")).is_none(), "no dangling id");
        assert!(
            state.card_zones(&cid("enemy_a")).is_none(),
            "its piles go with it, or every `cz=` line after it shifts"
        );

        // Refusals change nothing -- judged by the whole struct, RNG counter included.
        let snapshot = state;
        assert!(
            state.remove_combatant(&cid("enemy_a")).is_err(),
            "removing a combatant that is not in the fight must fail loudly"
        );
        assert!(
            state.remove_combatant(&cid("hero")).is_err(),
            "the active combatant cannot be removed mid-turn (the turn loop holds its id)"
        );
        assert!(
            state == snapshot,
            "a refusal must not move a single byte"
        );
    }

    #[test]
    fn a_split_spawns_two_combatants_when_the_boss_dies() {'''


def main():
    text = io.open(TESTS, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    io.open(TESTS, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("§178 tests added")


if __name__ == "__main__":
    main()
