"""§180 test: the charm catches one killing blow and is spent doing it.

The judgment is three-sided, because "it did not die" alone is satisfied by a bug that also refuses
every *other* death:

1. a lethal hit leaves the hero **alive at 30% of max HP**;
2. the status is **consumed** (wiki: "works once"), so
3. the **next** lethal hit kills -- and the fight ends in a loss.

`the_status_catalogue_is_honest` already pins that the kernel has a rule for the status; this pins
that the rule is at the right *moment* (after Block/Buffer/Plated Armor, before `Downed`).
"""
import io

HOST = "kernel/rd-core/src/host.rs"

ANCHOR = """    #[test]
    fn regen_heals_at_the_end_of_the_turn() {"""

NEW = r'''    /// §180: `DeathPrevention` -- the famous one-shot charm.
    ///
    /// A status with `Percent: 30` turns a killing blow into "you survive at 30% of max HP" **once**.
    /// The second killing blow is a real death, which is what makes this a test of the whole rule
    /// rather than of "the hero did not die".
    #[test]
    fn the_charm_catches_one_killing_blow_and_is_spent() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena(); // hero 70/70
        give(
            &mut state,
            "hero",
            status("st_fairy", "standard.fairy_in_a_bottle", 1),
        );

        // Lethal: 200 > 70. `Percent: 30` of 70 = 21.
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("enemy_a")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("hero"), 200, false).expect("the blow lands");
        }
        host.try_resolve_pending_queues(&mut state).expect("settle");

        assert_eq!(
            health(&state, "hero"),
            21,
            "survived at 30% of the 70 max HP (Percent), not at 1 HP and not at full"
        );
        assert_eq!(
            lifecycle(&state, "hero"),
            CombatantLifecycleState::Alive,
            "the hero is alive, not a corpse that happens to have HP"
        );
        assert_eq!(
            stacks_of(&state, "hero", "standard.fairy_in_a_bottle"),
            0,
            "the charm is spent doing it (wiki: `works once`)"
        );

        // The second lethal blow must kill: the charm is gone.
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("enemy_a")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("hero"), 200, false).expect("the blow lands");
        }
        host.try_resolve_pending_queues(&mut state).expect("settle");
        assert_eq!(health(&state, "hero"), 0, "no health left");
        assert_eq!(
            lifecycle(&state, "hero"),
            CombatantLifecycleState::Downed,
            "with the charm spent, a killing blow is a killing blow"
        );
    }

    #[test]
    fn regen_heals_at_the_end_of_the_turn() {'''


def main():
    text = io.open(HOST, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    io.open(HOST, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("§180 test inserted")


if __name__ == "__main__":
    main()
