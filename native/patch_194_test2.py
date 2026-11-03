"""§194 effect tests (host.rs): Sharp Hide, Divider's computed repeat, and `sel.allAllies`.

These are the three places where §194 uses a mechanism for the first time in this content, and each
has a failure mode that the number tables cannot see:

* **Sharp Hide**: `CardPlayed` + `card.hasTag.attack` -> damage the card player. If the tag filter is
  wrong the status fires on every card; if the target is wrong it damages the Guardian itself.
* **Divider**: `repeat(add(divide(currentHealth(hero), 12), 1), hit(6))`. A wrong divisor or a
  `repeat` that rounds the wrong way is invisible in any "the action does damage" test.
* **`sel.allAllies`**: Donu's Circle of Power must buff **both** bosses and leave the hero alone.
  `sel.allEnemies` is the opposing team; picking it (the obvious-looking choice, since the wiki says
  "all enemies") would buff the hero -- and the fight would look *easier*, not broken.
"""
import io

P = "kernel/rd-core/src/host.rs"
src = io.open(P, encoding="utf-8").read()

anchor = """    #[test]
    fn regen_heals_at_the_end_of_the_turn() {"""

tests = '''    /// §194: Sharp Hide is a `CardPlayed` trigger filtered on the card's **tag**.
    ///
    /// Three assertions, because three things can each be wrong independently: an Attack hurts the
    /// hero, a Skill does not, and Twin Slam drops the stacks (the wiki: "Loses Sharp Hide").
    #[test]
    fn sharp_hide_hurts_the_player_for_attacks_and_only_attacks() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_hide", "standard.sharp_hide", 3));
        let attack = card_in_hand(&mut state, &content, "hero", "strike");
        let skill = card_in_hand(&mut state, &content, "hero", "defend");

        // An Attack: the Guardian bites back for 3.
        let before = health(&state, "hero");
        state
            .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card: attack })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(health(&state, "hero"), before - 3, "Sharp Hide 3 punishes an Attack");

        // A Skill: nothing happens.
        let before = health(&state, "hero");
        state
            .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card: skill })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(health(&state, "hero"), before, "a Skill is not an Attack");

        // Twin Slam drops it, so the next Attack is free.
        let row = u32::from(
            content
                .lookup_in("the_guardian.twin_slam", crate::content::EK_EACTION)
                .expect("twin slam is in the image")
                .index,
        );
        crate::intent::execute_action(&mut state, &content, &cid("enemy_a"), row, Some(cid("hero")))
            .expect("Twin Slam lands");
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.sharp_hide"),
            0,
            "wiki: Twin Slam loses Sharp Hide"
        );
        let before = health(&state, "hero");
        state
            .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card: attack })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(health(&state, "hero"), before, "with the stacks gone, nothing bites back");
    }

    /// §194: Hexaghost's Divider -- `(hero HP / 12 + 1)` hits of 6, i.e. the first content move whose
    /// repeat count is **computed**. 70 HP -> `70/12 = 5` -> 6 hits -> 36 damage.
    ///
    /// Two different health totals are checked on purpose: a constant count would satisfy one.
    #[test]
    fn hexaghosts_divider_repeats_ceil_of_hp_over_twelve_plus_one() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let row = u32::from(
            content
                .lookup_in("hexaghost.divider", crate::content::EK_EACTION)
                .expect("divider is in the image")
                .index,
        );
        for (hero_hp, hits) in [(70, 6), (12, 2), (11, 1), (0, 0)] {
            let mut state = arena();
            if let Some(hero) = state.combatant_mut(&cid("hero")) {
                hero.health_current = hero_hp;
            }
            let before = health(&state, "hero");
            crate::intent::execute_action(&mut state, &content, &cid("enemy_a"), row, Some(cid("hero")))
                .expect("Divider lands");
            let dealt = before - health(&state, "hero");
            assert_eq!(
                dealt,
                hits * 6,
                "hero at {hero_hp}: {hits} hits of 6 = {}",
                hits * 6
            );
        }
    }

    /// §194: `sel.allAllies` -- Donu's Circle of Power buffs **both** bosses and not the hero.
    #[test]
    fn donus_circle_of_power_buffs_the_enemy_team_and_not_the_player() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut state = arena();
        state
            .add_combatant(unit("donu", "enemy", 250, 250))
            .expect("donu");
        state
            .add_combatant(unit("deca", "enemy", 250, 250))
            .expect("deca");
        let row = u32::from(
            content
                .lookup_in("donu.circle_of_power", crate::content::EK_EACTION)
                .expect("circle of power is in the image")
                .index,
        );
        crate::intent::execute_action(&mut state, &content, &cid("donu"), row, Some(cid("hero")))
            .expect("the buff lands");
        assert_eq!(stacks_of(&state, "donu", "standard.strength"), 3, "Donu buffs itself");
        assert_eq!(stacks_of(&state, "deca", "standard.strength"), 3, "and its ally");
        assert_eq!(
            stacks_of(&state, "hero", "standard.strength"),
            0,
            "`sel.allEnemies` would have buffed the hero -- this is the assertion that pins which \
             team the selector means"
        );
    }

''' + anchor
assert src.count(anchor) == 1
src = src.replace(anchor, tests, 1)
io.open(P, "w", encoding="utf-8", newline="").write(src)
print("host.rs: three §194 effect tests")
