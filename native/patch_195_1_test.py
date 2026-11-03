"""§195.1 tests: `eventAmount` reaches a content trigger, and Mode Shift is a real HP counter.

Two things only these tests can catch:

* **`eventAmount` is the HP actually lost** -- not the requested amount, not the blocked part.
  A fully blocked hit must shift *nothing*, and that is the case where "requested" and "lost" differ.
* **The threshold grows by 10 per trigger** (`30, 40, 50 ...`). A rule that forgets the
  `+ 10 * shifts` term still fires -- only the *second* shift is wrong, so a one-sided test
  (`damage >= 30` once) would pass on the broken rule.
"""
import io

P = "kernel/rd-core/src/host.rs"
src = io.open(P, encoding="utf-8").read()

anchor = """    #[test]
    fn regen_heals_at_the_end_of_the_turn() {"""

tests = '''    /// §195.1: The Guardian's Mode Shift is `damage >= 30 + 10 * shifts`, where the damage is the
    /// **HP actually lost** (`eventAmount`), and Defensive Mode resets the counter and grows the
    /// threshold.
    ///
    /// Four judgements, none of which a "the boss has a rule" test would make:
    /// 1. 29 damage is **not** enough (the threshold is not off by one);
    /// 2. a fully **blocked** hit adds nothing (the amount is HP lost, not the request);
    /// 3. 30 is enough, and Defensive Mode resets the damage counter to 0 and sets `shifts = 1`;
    /// 4. the **second** shift needs 40, not 30 -- this is the `+ 10 * shifts` term.
    #[test]
    fn mode_shift_counts_the_health_actually_lost_and_grows_by_ten() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);

        // A fight with the Guardian as `enemy_a`, carrying its own `standard.mode_shift`.
        let mut state = arena();
        // `arena()` gives `enemy_a` 20 HP -- a 29-damage probe would kill it before the trigger the
        // test is about could fire. The Guardian has 240.
        {
            let guardian = state.combatant_mut(&cid("enemy_a")).expect("the guardian");
            guardian.health_max = 240;
            guardian.health_current = 240;
        }
        give(&mut state, "enemy_a", status("st_ms", "standard.mode_shift", 1));

        let hit_for = |state: &mut CombatState, host: &mut Host<'_>, amount: i32, block: i32| {
            if block > 0 {
                state
                    .combatant_mut(&cid("enemy_a"))
                    .expect("the guardian")
                    .set_defensive_pool(
                        crate::state::DefensivePoolId::new("standard.block").unwrap(),
                        block,
                        None,
                    )
                    .expect("block");
            }
            {
                let mut ctx = crate::exec::ExecContext::new(
                    state,
                    Some(cid("hero")),
                    Some(cid("enemy_a")),
                    None,
                    64,
                )
                .with_content(&content);
                crate::exec::resolve_damage(&mut ctx, &cid("enemy_a"), amount, false)
                    .expect("the blow lands");
            }
            host.try_resolve_pending_queues(state).expect("the trigger settles");
        };

        hit_for(&mut state, &mut host, 29, 0);
        assert_eq!(counter_of(&state, "enemy_a", "mode_shift_damage"), 29, "29 < 30");
        assert_eq!(counter_of(&state, "enemy_a", "guard_shifts"), -1, "no shift yet");

        // Fully blocked: the request is 50 but **no HP is lost**, so nothing accumulates.
        hit_for(&mut state, &mut host, 50, 999);
        assert_eq!(
            counter_of(&state, "enemy_a", "mode_shift_damage"),
            29,
            "a fully blocked hit loses no HP -- `eventAmount` must not be the requested amount"
        );

        // 1 more HP crosses 30.
        hit_for(&mut state, &mut host, 1, 0);
        assert_eq!(counter_of(&state, "enemy_a", "mode_shift_damage"), 30);
        // The rule is only a *rule*: nothing resets the books until Defensive Mode **runs**, which is
        // the boss's turn. Run it the way the intent machine would.
        let row = u32::from(
            content
                .lookup_in("the_guardian.defensive_mode", crate::content::EK_EACTION)
                .expect("defensive mode is in the image")
                .index,
        );
        crate::intent::execute_action(&mut state, &content, &cid("enemy_a"), row, Some(cid("hero")))
            .expect("Defensive Mode");
        assert_eq!(counter_of(&state, "enemy_a", "mode_shift_damage"), 0, "counter resets");
        assert_eq!(counter_of(&state, "enemy_a", "guard_shifts"), 1, "one shift so far");
        assert_eq!(block_of(&state, "enemy_a"), 20, "wiki: gains 20 Block");

        // Second shift: the threshold is now 40.
        hit_for(&mut state, &mut host, 39, 0);
        assert_eq!(counter_of(&state, "enemy_a", "mode_shift_damage"), 39, "39 < 40");
        hit_for(&mut state, &mut host, 1, 0);
        assert_eq!(
            counter_of(&state, "enemy_a", "mode_shift_damage"),
            40,
            "the wiki's `increased by 10 each time` is part of the threshold, not decoration"
        );
    }

''' + anchor
assert src.count(anchor) == 1
src = src.replace(anchor, tests, 1)
io.open(P, "w", encoding="utf-8", newline="").write(src)
print("host.rs: mode shift test")
