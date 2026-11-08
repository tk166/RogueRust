"""§302/§303 判据。

## `strange_spoon`

* 带状态时**同一次出牌**要么进消耗堆、要么进弃牌堆（两边的计数加起来永远是 1）；
* **没有状态时永远进消耗堆**（不掷骰、随机步不推进）—— 这是负控之外最重要的一条：
  如果实现忘了检查状态，一半的"消耗牌"会静默变成弃牌堆；
* 掷很多次之后两边**都到过**（50% 不是 0% 也不是 100%）；同一颗种子 → 同一条序列；
* **边界**：`Ethereal` 的回合末消耗、被效果逼着消耗，都**不**受它影响（wiki 写死的三行）。

## `wing_boots`

* 没有遗物 ⇒ `reachable()` 里没有不相连的房间，`enter_node` 拒绝；
* 有遗物 ⇒ `reachable()` 里出现**下一层全部**房间，且**真连着的仍排在最前面**；
* 飞一次扣一次；3 次之后恢复成普通地图；走真连着的路**不扣**；
* Boss 那一步不扣（它不在"下一层的房间"里）。
"""
import io

PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

CORE_TEST = r'''
    // ── §302：`strange_spoon` ────────────────────────────────────────────────────────────────
    //
    // 三条判据都从**同一个入口**走（`play_card`），因为落区的答案只有一个来源。

    /// §302：带状态时一次出牌只落**一个**区（消耗堆 xor 弃牌堆）。
    fn spoon_landing(state: &mut CombatState) -> CardZone {
        let request = PlayRequest::new(TEST_HERO, "card_a", None);
        let plan = plan_play(state, None, &request).expect("a plan");
        let destination = plan.destination;
        assert_eq!(destination, CardZone::ExhaustPile, "the card exhausts when played");
        play_card(state, None, &request).expect("the play");
        // 打完它必然在两者之一（不在手牌里）。
        let in_exhaust = zone_count(state, TEST_HERO, CardZone::ExhaustPile);
        let in_discard = zone_count(state, TEST_HERO, CardZone::DiscardPile);
        assert_eq!(in_exhaust + in_discard, 1, "exactly one landing");
        if in_exhaust == 1 {
            CardZone::ExhaustPile
        } else {
            CardZone::DiscardPile
        }
    }

    /// §302：没有 `strange_spoon` 时**永远**进消耗堆，而且**不消耗随机流**。
    ///
    /// 后一半是这条判据的重点：一次"不该掷的骰"会让同一颗种子后面每一次随机都错位，
    /// 而那时只有"某张牌的伤害差 1"这种间接症状。
    #[test]
    fn without_strange_spoon_an_exhausting_card_always_exhausts_and_never_rolls() {
        let mut state = CombatState::new(7).expect("a state");
        install_hero(&mut state);
        state
            .combatant_mut(&hero_id())
            .expect("the hero")
            .set_resource(ResourceKind::Energy, 3, 3)
            .expect("energy");
        give_card_def(&mut state, TEST_HERO, CardZone::Hand, "card_a", "slimed");
        let step_before = state.random_step();
        for _ in 0..8 {
            if zone_count(&state, TEST_HERO, CardZone::Hand) == 0 {
                give_card_def(&mut state, TEST_HERO, CardZone::Hand, "card_a", "slimed");
            }
            let card = first_card_in(&state, TEST_HERO, CardZone::Hand);
            let request = PlayRequest::new(TEST_HERO, card, None);
            let destination = plan_play(&state, None, &request).expect("a plan").destination;
            assert_eq!(destination, CardZone::ExhaustPile, "still the card's own rule");
            play_card(&mut state, None, &request).expect("the play");
            assert_eq!(
                zone_count(&state, TEST_HERO, CardZone::DiscardPile),
                0,
                "without the relic nothing is saved"
            );
        }
        assert_eq!(
            state.random_step(),
            step_before,
            "no roll at all without the relic (a stray roll shifts every later random)"
        );
    }

    /// §302：带状态时，很多次之后**两边都到过**（50% 不是 0 也不是 100%），
    /// 且同一颗种子给出同一条序列。
    #[test]
    fn strange_spoon_saves_about_half_of_the_exhausts_and_is_deterministic() {
        fn run(seed: u32) -> Vec<CardZone> {
            let mut state = CombatState::new(seed).expect("a state");
            install_hero(&mut state);
            let hero = hero_id();
            state
                .combatant_mut(&hero)
                .expect("the hero")
                .set_resource(ResourceKind::Energy, 99, 99)
                .expect("energy");
            add_status(
                state.combatant_mut(&hero).expect("the hero"),
                crate::play::STRANGE_SPOON_STATUS,
            );
            let mut out = Vec::new();
            for _ in 0..24 {
                give_card_def(&mut state, TEST_HERO, CardZone::Hand, "card_a", "slimed");
                out.push(spoon_landing(&mut state));
            }
            out
        }
        let first = run(7);
        assert!(first.contains(&CardZone::DiscardPile), "it does save some: {first:?}");
        assert!(first.contains(&CardZone::ExhaustPile), "and it does not save all: {first:?}");
        assert_eq!(first, run(7), "same seed, same sequence");
    }

    /// §302：**边界** —— `Ethereal`（回合末消耗）与"被效果逼着消耗"都不经过出牌计划，
    /// 所以那颗骰子对它们不存在。这条钉住的是"切口在落区，而不是在所有消耗"。
    #[test]
    fn strange_spoon_does_not_touch_ethereal_or_forced_exhausts() {
        let mut state = CombatState::new(11).expect("a state");
        install_hero(&mut state);
        let hero = hero_id();
        add_status(
            state.combatant_mut(&hero).expect("the hero"),
            crate::play::STRANGE_SPOON_STATUS,
        );
        // `dazed` 是 Ethereal：回合末进消耗堆，全程没有人掷骰。
        give_card_def(&mut state, TEST_HERO, CardZone::Hand, "card_a", "dazed");
        let step_before = state.random_step();
        end_turn(&mut state).expect("the turn ends");
        assert_eq!(
            zone_count(&state, TEST_HERO, CardZone::ExhaustPile),
            1,
            "Ethereal still exhausts"
        );
        assert_eq!(state.random_step(), step_before, "and nothing was rolled");
    }
'''

RUN_TEST = r'''
    /// §303：`wing_boots` —— 免费的路不扣、飞一次扣一次、3 次之后回到普通地图、Boss 不扣。
    ///
    /// 一条判据走完所有分支，是因为它们共享同一份 `reachable()`：分开写会让"两个答案
    /// 各来自一处"（§2 的老毛病）看不出漂。
    #[test]
    fn wing_boots_lets_you_fly_three_times_and_never_charges_the_free_paths() {
        let deck = ["strike", "defend"];
        let mut run = RunState::new(21, 80, 99, &deck).expect("a run");
        // 站到第 0 层的第一个节点上（`reachable()` 一开始给的是整层）。
        let first = run.reachable().get(0).expect("a first node");
        run.enter_node(first).expect("onto row 0");
        run.mark_resolved().expect("settled");
        let free = run.reachable();
        assert!(!free.is_empty(), "the map has edges");
        assert_eq!(run.wing_boots_left(), 0, "no relic, no charges");
        // 没有遗物：下一层里**不相连**的房间必须被拒。
        let row_one: Vec<u8> = (0..run.map().row(1).map_or(0, |row| row.len()))
            .filter_map(|local| run.map().global_of(1, local))
            .collect();
        let stranger = row_one.iter().copied().find(|node| !free.contains(*node));
        assert!(stranger.is_some(), "row 1 has a node the edges do not reach");
        assert_eq!(
            run.enter_node(stranger.expect("a disconnected node")),
            Err(RunError::NotReachable)
        );

        // 发遗物：下一次 `reachable()` 就该出现下一层的**全部**房间。
        run.push_relic("wing_boots", &[]).expect("wing_boots");
        assert_eq!(run.wing_boots_left(), 3);
        let wide = run.reachable();
        for node in &row_one {
            assert!(wide.contains(*node), "row 1 node {node} is selectable");
        }
        // ⚠️ 真连着的仍然排在**最前面**（下标是页面的动作号）。
        for (index, node) in free.iter().enumerate() {
            assert_eq!(wide.get(index), Some(*node), "free path {index} keeps its action index");
        }

        // 走一次免费的路：不扣。
        let step = wide.get(0).copied().expect("a free edge");
        run.enter_node(step).expect("the free walk");
        assert_eq!(run.wing_boots_left(), 3, "a real edge is free");
        run.mark_resolved().expect("settled");

        // 飞三次：每次扣一次，第三次之后 `reachable()` 缩回普通地图。
        for expected in [2u8, 1, 0] {
            let row = run.floor as usize;
            let nodes: Vec<u8> = (0..run.map().row(row).map_or(0, |r| r.len()))
                .filter_map(|local| run.map().global_of(row, local))
                .collect();
            let reachable = run.reachable();
            let far = nodes
                .iter()
                .copied()
                .find(|node| !reachable.contains(*node));
            let target = far.unwrap_or_else(|| {
                // 这一层每个房间都通（可能）：随便挑一个真正相连的，验证"免费"这条路。
                *reachable.get(0).expect("a reachable node")
            });
            run.enter_node(target).expect("fly or walk");
            run.mark_resolved().expect("settled");
            if far.is_some() {
                assert_eq!(run.wing_boots_left(), expected, "a flight costs one");
            } else {
                assert_eq!(run.wing_boots_left(), expected + 1, "nothing to fly to");
            }
        }
        // 用完：不相连的房间再次被拒。
        let row = run.floor as usize;
        if row < ROWS {
            let nodes: Vec<u8> = (0..run.map().row(row).map_or(0, |r| r.len()))
                .filter_map(|local| run.map().global_of(row, local))
                .collect();
            let reachable = run.reachable();
            if let Some(far) = nodes.iter().copied().find(|node| !reachable.contains(*node)) {
                assert_eq!(run.enter_node(far), Err(RunError::NotReachable));
            }
        }

        // Boss 那一步不扣：站在最后一层，`reachable()` 给的是哨兵。
        run.floor = ROWS as i32;
        run.node = run.map().global_of(ROWS - 1, 0).map(i32::from).expect("a last node");
        run.mark_resolved().expect("settled");
        let boss = run.reachable();
        assert_eq!(boss.get(0).copied(), Some(crate::map::BOSS_NODE));
        assert_eq!(run.wing_boots_left(), 0, "boss step is not a flight");
    }
'''


def main():
    s = io.open(PLAY, encoding='utf-8').read()
    cut = s.rstrip('\n').rfind('\n}')
    s = s[:cut] + CORE_TEST + s[cut:]
    io.open(PLAY, 'w', encoding='utf-8', newline='\n').write(s)
    print('core tests')

    t = io.open(STATE, encoding='utf-8').read()
    cut = t.rstrip('\n').rfind('\n}')
    t = t[:cut] + RUN_TEST + t[cut:]
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
    print('run tests')


main()
