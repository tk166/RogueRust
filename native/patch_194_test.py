"""§194 tests: each new boss's *behaviour*, not just its numbers.

Six things here are new mechanism combinations rather than new numbers, and each one has a failure
mode that no numeric table would catch:

1. **Hexaghost's rotated cycle.** The wiki's pattern is `Sear, Tackle, Sear, Inflame, Tackle, Sear,
   Inferno` from turn 3 on, while the kernel's default cycle is `Actions[(round-1) % n]`. The list is
   therefore *rotated*; if someone "tidies" the order the boss still fights and only the move order
   drifts -- invisible in every fact table.
2. **Hexaghost's Divider**: `repeat(add(divide(currentHealth(hero), 12), 1))` -- the first content use
   of a **computed repeat count**, so both the arithmetic and the target matter.
3. **The Guardian's Sharp Hide**: a `CardPlayed` trigger filtered on `card.hasTag.attack`, i.e. the
   first content status that reacts to *the player's card type* by dealing damage back.
4. **Donu's Circle of Power**: `sel.allAllies` -- the first content that buffs the boss's own team.
   With `sel.allEnemies` (the obvious-looking choice) it would buff the hero and heal the fight.
5. **Bronze Automaton's A19 `Stunned -> Boost` swap** and **the Awakened One's phase flip**: both are
   intent rules keyed on counters/rounds, so "the rule never fires" is silent.
6. **The Champ's phase two** (Anger at <= 50%, Execute the round after, Taunt every 4th round).
"""
import io

P = "kernel/rd-core/src/intent.rs"
src = io.open(P, encoding="utf-8").read()

anchor = """    // ---------------------------------------------------------------- 补丁工具"""

tests = '''    // ================================================================ §194：Boss 池

    /// 三幕的 Boss 池各自三个（wiki：每幕三选一），而且每个成员都能真的建出一个遭遇。
    ///
    /// `encounter_pool` 是内核读 `EncounterTables.<Name>` 的唯一入口，所以这条同时证明了"池子里
    /// 有名字"和"名字指向的遭遇存在"—— 后者在内容门里也查，但这里查的是**内核读到的同一份**。
    #[test]
    fn every_act_has_three_bosses_and_each_one_is_a_buildable_encounter() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        for (pool, expected) in [
            ("Boss", ["enc_slime_boss", "enc_the_guardian", "enc_hexaghost"]),
            ("Boss2", ["enc_the_champ", "enc_bronze_automaton", "enc_the_collector"]),
            ("Boss3", ["enc_time_eater", "enc_awakened_one", "enc_donu_and_deca"]),
        ] {
            let ids = content
                .encounter_pool(pool)
                .unwrap_or_else(|| panic!("`EncounterTables.{pool}` must be readable"));
            let listed: Vec<&str> = ids.iter().copied().filter(|id| !id.is_empty()).collect();
            assert_eq!(listed, expected, "act pool `{pool}`");
            for id in listed {
                let row = encounter_row(&content, id);
                let enemies = content
                    .encounter_enemies(row)
                    .unwrap_or_else(|e| panic!("`{id}` must have enemies: {e:?}"));
                assert!(
                    (1..=3).contains(&enemies.len()),
                    "`{id}` places {} enemies (1..=3)",
                    enemies.len()
                );
            }
        }
    }

    /// Hexaghost 的 7 招循环**是从 wiki 的顺序轮转过的**：`Actions[(round-1) % 7]` 从第 3 回合起
    /// 必须正好落在 Sear, Tackle, Sear, Inflame, Tackle, Sear, Inferno 上。
    ///
    /// 这条测试是这一段唯一能发现"有人把列表理顺了"的判据：顺序错了 Boss 照样打，只是招式顺序漂了。
    #[test]
    fn hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let at = slot(&content, "enc_hexaghost", 0);
        let mut state = arena("hexaghost");
        let actor = cid("hexaghost");

        let mut seen = Vec::new();
        for round in 1..=9 {
            state.current_round = round;
            seen.push(
                select_action(&state, &content, at, &actor, round)
                    .expect("intent")
                    .expect("an action")
                    .action_id,
            );
        }
        let expected = [
            "hexaghost.activate",     // turn 1
            "hexaghost.divider",      // turn 2
            "hexaghost.sear",         // turn 3
            "hexaghost.tackle",       // turn 4
            "hexaghost.sear",         // turn 5
            "hexaghost.inflame",      // turn 6
            "hexaghost.tackle",       // turn 7
            "hexaghost.sear",         // turn 8
            "hexaghost.inferno",      // turn 9
        ];
        assert_eq!(seen, expected, "the wiki's pattern from `native/wiki_asc/hexaghost.txt`");
    }

    /// Bronze Automaton：`Stunned` 在**A19 才**被 `Boost` 顶替，而且只顶替那几轮。
    ///
    /// 两侧都测（A0 与 A19），因为"规则提前生效"与"规则根本不生效"在只看一侧时是同一种观察。
    #[test]
    fn the_automaton_swaps_stunned_for_boost_only_at_a19() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let at = slot(&content, "enc_bronze_automaton", 0);
        for (ascension, round_6, round_7) in [
            (0u8, "bronze_automaton.stunned", "bronze_automaton.flail"),
            (19, "bronze_automaton.boost", "bronze_automaton.flail"),
        ] {
            let mut state = arena("bronze_automaton");
            state.set_ascension(ascension);
            let actor = cid("bronze_automaton");
            state.current_round = 6;
            let six = select_action(&state, &content, at, &actor, 6).expect("intent").expect("an action");
            assert_eq!(six.action_id, round_6, "A{ascension} round 6");
            state.current_round = 7;
            let seven = select_action(&state, &content, at, &actor, 7).expect("intent").expect("an action");
            assert_eq!(seven.action_id, round_7, "A{ascension} round 7");
        }
    }

    /// The Champ：回合 4 是 Taunt；HP ≤ 50% 时先 Anger、下一回合 Execute。
    ///
    /// 三个判据各锁一条规则，而三者在"规则不生效"时都表现为"Boss 正常出招"。
    #[test]
    fn the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let at = slot(&content, "enc_the_champ", 0);
        let mut state = arena("the_champ");
        let actor = cid("the_champ");
        let pick = |state: &mut CombatState, round: i32| {
            state.current_round = round;
            select_action(state, &content, at, &actor, round)
                .expect("intent")
                .expect("an action")
                .action_id
        };

        assert_eq!(pick(&mut state, 4), "the_champ.taunt", "taunt lands every 4th round");
        assert_eq!(pick(&mut state, 5), "the_champ.heavy_slash", "and only on the 4th");

        // Drop the boss to half health: the *next* intent is Anger, then Execute.
        {
            let boss = state.combatant_mut(&actor).expect("the champ");
            boss.health_current = boss.health_max / 2;
        }
        assert_eq!(pick(&mut state, 6), "the_champ.anger", "phase two opens with Anger");
        // Anger sets the two counters; the fight would run the program, so set them the same way.
        set_counter(&mut state, &actor, "champ_phase", 1);
        set_counter(&mut state, &actor, "champ_exec", 0);
        assert_eq!(pick(&mut state, 7), "the_champ.execute", "then Execute");
        set_counter(&mut state, &actor, "champ_exec", 1);
        assert_eq!(pick(&mut state, 8), "the_champ.heavy_slash", "afterwards the cycle resumes");
    }

    /// The Awakened One：≤ 25% 血时意图变 Rebirth；Rebirth 之后先 Dark Echo，然后 Tackle/Sludge 交替。
    #[test]
    fn the_awakened_one_flips_to_phase_two_through_its_counters() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let at = slot(&content, "enc_awakened_one", 0);
        let mut state = arena("awakened_one");
        let actor = cid("awakened_one");
        let pick = |state: &mut CombatState, round: i32| {
            state.current_round = round;
            select_action(state, &content, at, &actor, round)
                .expect("intent")
                .expect("an action")
                .action_id
        };

        state.current_round = 1;
        assert_eq!(pick(&mut state, 1), "awakened_one.slash", "phase one opens with Slash");
        {
            let boss = state.combatant_mut(&actor).expect("the boss");
            boss.health_current = boss.health_max / 4;
        }
        assert_eq!(pick(&mut state, 2), "awakened_one.rebirth", "<= 25% => Rebirth");
        // Rebirth sets three counters; do what its program does.
        set_counter(&mut state, &actor, "ao_phase", 1);
        set_counter(&mut state, &actor, "ao_started", 0);
        set_counter(&mut state, &actor, "ao_toggle", 0);
        assert_eq!(pick(&mut state, 3), "awakened_one.dark_echo", "phase two opens with Dark Echo");
        set_counter(&mut state, &actor, "ao_started", 1);
        assert_eq!(pick(&mut state, 4), "awakened_one.tackle");
        set_counter(&mut state, &actor, "ao_toggle", 1);
        assert_eq!(pick(&mut state, 5), "awakened_one.sludge");
        set_counter(&mut state, &actor, "ao_toggle", 0);
        assert_eq!(pick(&mut state, 6), "awakened_one.tackle", "Tackle/Sludge alternate");
    }

''' + anchor
assert src.count(anchor) == 1
src = src.replace(anchor, tests, 1)
io.open(P, "w", encoding="utf-8", newline="").write(src)
print("intent.rs: five §194 behaviour tests")
