"""§302/§303 判据（第二版：用 play.rs 测试模块里**真实存在**的 helper）。

第一版自己发明了 `install_hero` / `give_card_def` / `zone_count` —— 一个都不存在。
真实的是 `arena()` / `give_card(&mut state, who, zone, instance, definition)` /
`give_status` / `available_request` / `zone_of` / `energy_of` / `request`。
"""
import io

PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

CORE_TEST = r'''
    // ── §302：`strange_spoon` ────────────────────────────────────────────────────────────────

    /// §302：没有 `strange_spoon` 时**永远**进消耗堆，而且**一次骰子都不掷**。
    ///
    /// 后一半是重点：一次"不该掷的骰"会让同一颗种子后面每一次随机都错位，而症状只会是
    /// "某张牌的伤害差 1"。判据直接看 `random_step`。
    #[test]
    fn without_strange_spoon_an_exhausting_card_always_exhausts_and_never_rolls() {
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        let step_before = state.random_step();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "slimed");
        let report = play_card(&mut state, Some(&content), &request("card_h1", None))
            .expect("slimed is playable");
        assert_eq!(report.landed, Some(CardZone::ExhaustPile));
        assert_eq!(zone_of(&state, "hero", "card_h1"), Some(CardZone::ExhaustPile));
        assert_eq!(
            state.random_step(),
            step_before,
            "no relic ⇒ no roll (a stray roll shifts every later random)"
        );
    }

    /// §302：带状态时，很多次之后**两边都到过**（50% 不是 0% 也不是 100%），
    /// 而且同一颗种子给出同一条落区序列。
    ///
    /// 用 `slimed`（打出即消耗、没有节目、费用 1）—— 没有节目就没有别的随机来源，
    /// 于是"两边都到过"只可能来自这一颗骰子。
    #[test]
    fn strange_spoon_saves_about_half_of_the_exhausts_and_is_deterministic() {
        fn landings(seed: u32) -> Vec<CardZone> {
            let blob = core_image();
            let content = parse(&blob);
            let mut state = CombatState::new(CombatId::new("c1").unwrap(), seed);
            state.add_combatant(unit("hero", "player", 70, 70)).unwrap();
            state
                .combatant_mut(&cid("hero"))
                .unwrap()
                .set_resource(energy(), 99, Some(99))
                .unwrap();
            give_status(&mut state, "hero", STRANGE_SPOON_STATUS);
            let mut out = Vec::new();
            for index in 0..24 {
                let instance = std::format!("spoon_{index}");
                give_card(&mut state, "hero", CardZone::Hand, &instance, "slimed");
                let report = play_card(&mut state, Some(&content), &request(&instance, None))
                    .expect("slimed is playable");
                out.push(report.landed.expect("it landed somewhere"));
            }
            out
        }
        let first = landings(7);
        assert!(
            first.contains(&CardZone::DiscardPile),
            "it saves some: {first:?}"
        );
        assert!(
            first.contains(&CardZone::ExhaustPile),
            "and it does not save all: {first:?}"
        );
        assert_eq!(first, landings(7), "same seed, same sequence");
    }

    /// §302：**边界** —— 骰子只属于"打出即消耗"那一条路。
    ///
    /// * 打一张**本来就不消耗**的牌：不掷（否则每一张牌都在偷随机流）；
    /// * 被效果直接搬进消耗堆（`move_card`，`Fiend Fire` / `Burning Pact` 那条路）：
    ///   照旧进消耗堆，也不掷。
    ///
    /// wiki 的原话是 *"Strange Spoon specifically only works on cards that Exhaust when played"*，
    /// 这两条就是那句话的两侧。
    #[test]
    fn strange_spoon_only_rolls_for_cards_that_exhaust_when_played() {
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        give_status(&mut state, "hero", STRANGE_SPOON_STATUS);

        // ① 不消耗的牌 ⇒ 落弃牌堆、不掷骰。
        let step_before = state.random_step();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "strike");
        let report = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("strike is playable");
        assert_eq!(report.landed, Some(CardZone::DiscardPile));
        assert_eq!(state.random_step(), step_before, "a discard never rolls");

        // ② 被效果搬进消耗堆 ⇒ 不掷骰、照旧消耗。
        let step_before = state.random_step();
        give_card(&mut state, "hero", CardZone::Hand, "card_h2", "slimed");
        let slot = find_card_slot(&state, &cid("hero"), &CardInstanceId::new("card_h2").unwrap())
            .map(|(_, slot)| slot)
            .expect("the card");
        state
            .move_card(
                &cid("hero"),
                CardZone::Hand,
                CardZone::ExhaustPile,
                slot,
                ZonePlacement::Bottom,
            )
            .expect("a forced exhaust");
        assert_eq!(
            zone_of(&state, "hero", "card_h2"),
            Some(CardZone::ExhaustPile),
            "a forced exhaust is not the relic's business"
        );
        assert_eq!(state.random_step(), step_before, "and it does not roll");
    }
'''

RUN_TEST = r'''
    /// §303：`wing_boots` —— 免费的路不扣、飞一次扣一次、3 次之后回到普通地图、Boss 不扣。
    ///
    /// 一条判据走完所有分支，是因为它们共享同一份 `reachable()`：分开写会让"两个答案各来自
    /// 一处"（同一个词表两处认识的那种腐烂）看不出来。
    #[test]
    fn wing_boots_lets_you_fly_three_times_and_never_charges_the_free_paths() {
        let deck = ["strike", "defend"];
        let mut run = RunState::new(21, 80, 99, &deck).expect("a run");
        let first = *run.reachable().get(0).expect("a first node");
        run.enter_node(first).expect("onto row 0");
        run.mark_resolved().expect("settled");

        let neighbours: Vec<u8> = run.reachable().to_vec();
        assert!(!neighbours.is_empty(), "the map has edges");
        assert_eq!(run.wing_boots_left(), 0, "no relic, no charges");

        let row_one: Vec<u8> = (0..run.map().row(1).map_or(0, |row| row.len()))
            .filter_map(|local| run.map().global_of(1, local))
            .collect();
        let stranger = row_one
            .iter()
            .copied()
            .find(|node| !neighbours.contains(node))
            .expect("row 1 has a node the edges do not reach");
        // 没有遗物：下一层里不相连的房间被拒。
        assert_eq!(run.enter_node(stranger), Err(RunError::NotReachable));

        run.push_relic("wing_boots", &[]).expect("wing_boots");
        assert_eq!(run.wing_boots_left(), 3);
        let wide: Vec<u8> = run.reachable().to_vec();
        for node in &row_one {
            assert!(wide.contains(node), "row 1 node {node} becomes selectable");
        }
        // ⚠️ 真连着的仍排在**最前面**（下标是页面的动作号）。
        for (index, node) in neighbours.iter().enumerate() {
            assert_eq!(
                wide.get(index),
                Some(node),
                "free path {index} keeps its action index"
            );
        }

        // 走一次免费的路：不扣。
        run.enter_node(neighbours[0]).expect("the free walk");
        assert_eq!(run.wing_boots_left(), 3, "a real edge is free");
        run.mark_resolved().expect("settled");

        // 飞三次：每次扣一次；第三次之后不相连的房间重新被拒。
        for expected_left in [2u8, 1, 0] {
            let row = run.floor as usize;
            assert!(row < ROWS, "still on the map");
            let row_nodes: Vec<u8> = (0..run.map().row(row).map_or(0, |line| line.len()))
                .filter_map(|local| run.map().global_of(row, local))
                .collect();
            let reachable: Vec<u8> = run.reachable().to_vec();
            let far = row_nodes
                .iter()
                .copied()
                .find(|node| !reachable.contains(node))
                .expect("each row has a node the path does not reach (checked below)");
            assert!(far != crate::map::BOSS_NODE);
            run.enter_node(far).expect("a flight");
            assert_eq!(run.wing_boots_left(), expected_left, "a flight costs one");
            run.mark_resolved().expect("settled");
        }
        let row = run.floor as usize;
        if row < ROWS {
            let row_nodes: Vec<u8> = (0..run.map().row(row).map_or(0, |line| line.len()))
                .filter_map(|local| run.map().global_of(row, local))
                .collect();
            let reachable: Vec<u8> = run.reachable().to_vec();
            if let Some(far) = row_nodes.iter().copied().find(|n| !reachable.contains(n)) {
                assert_eq!(
                    run.enter_node(far),
                    Err(RunError::NotReachable),
                    "spent charges mean the ordinary map again"
                );
            }
        }

        // Boss 那一步不是飞行：站在最后一层时 `reachable()` 给的是哨兵，次数一点不动。
        run.floor = ROWS as i32;
        run.node = i32::from(run.map().global_of(ROWS - 1, 0).expect("a last-row node"));
        run.mark_resolved().expect("settled");
        assert_eq!(run.wing_boots_left(), 0);
        run.push_relic("wing_boots", &[]).expect("a second copy");
        assert_eq!(run.wing_boots_left(), 3, "a fresh relic has its own charges");
        assert_eq!(
            run.reachable().get(0).copied(),
            Some(crate::map::BOSS_NODE),
            "the boss is the only way forward"
        );
        assert_eq!(
            run.wing_boots_left(),
            3,
            "the boss step is not a flight"
        );
    }
'''


def main():
    s = io.open(PLAY, encoding='utf-8').read()
    cut = s.rstrip('\n').rfind('\n}')
    io.open(PLAY, 'w', encoding='utf-8', newline='\n').write(s[:cut] + CORE_TEST + s[cut:])
    print('core tests')

    t = io.open(STATE, encoding='utf-8').read()
    cut = t.rstrip('\n').rfind('\n}')
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t[:cut] + RUN_TEST + t[cut:])
    print('run tests')


main()
