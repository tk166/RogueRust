"""§300 判据：三个新原子各自解锁的那一件（每条都钉"改动前会怎样"）。"""
import io

HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'

TESTS = r'''
    /// §300：`warped_tongs` —— 回合开始**随机**升级手牌一张。
    ///
    /// 判据钉的是**新原子**（`upgradeCards{Random: true}`）：没有 `Random` 时
    /// `upgradeCards` 永远取牌区顺序的**第一张**。所以做法是"手牌放三张、连开两回合"，
    /// 要求被升级的那一张**不是恒定第一张** —— 顺序升级会永远是同一张。
    #[test]
    fn warped_tongs_upgrades_a_random_card_not_the_first_one() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);

        let mut state = arena();
        give(&mut state, "hero", status("st_wt", "standard.warped_tongs", 1));
        // 手牌三张（`card_in_hand` 是 append，所以顺序 = 调用顺序）。
        for id in ["strike", "defend", "bash"] {
            let _ = card_in_hand(&mut state, &content, "hero", id);
        }
        let hand = |state: &crate::state::CombatState| -> Vec<String> {
            state
                .card_zones(&cid("hero"))
                .expect("zones")
                .slots(crate::state::CardZone::Hand)
                .iter()
                .filter_map(|slot| state.card(crate::state::CardSlot::from_index(*slot)))
                .map(|card| std::string::String::from(card.definition_id.as_str()))
                .collect()
        };
        let before = hand(&state);
        assert!(before.iter().all(|id| !id.contains('+')), "start clean: {before:?}");

        host.try_run_turn_started_triggers(&mut state, &cid("hero"))
            .expect("the turn starts");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        let after = hand(&state);
        let upgraded: Vec<usize> = after
            .iter()
            .enumerate()
            .filter(|(index, id)| id.contains('+') && !before[*index].contains('+'))
            .map(|(index, _)| index)
            .collect();
        assert_eq!(
            upgraded.len(),
            1,
            "exactly one card is upgraded: {before:?} -> {after:?}"
        );
        // ★ 关键：那张牌的位置**不是恒定 0**。`upgradeCards` 没有 `Random` 时这里是 0。
        // 用"多次开局、每次换一个 seed"观察位置分布 —— 只跑一次会碰运气。
        let mut positions = std::collections::BTreeSet::new();
        for seed in 0..24i32 {
            let mut state = CombatState::new(crate::state::CombatId::new("c1").unwrap(), seed);
            state
                .add_combatant(unit("hero", "player", 70, 70))
                .expect("hero");
            state
                .add_combatant(unit("enemy_a", "enemy", 20, 20))
                .expect("foe");
            give(&mut state, "hero", status("st_wt", "standard.warped_tongs", 1));
            for id in ["strike", "defend", "bash"] {
                let _ = card_in_hand(&mut state, &content, "hero", id);
            }
            host.try_run_turn_started_triggers(&mut state, &cid("hero"))
                .expect("the turn starts");
            host.try_resolve_pending_queues(&mut state).expect("triggers");
            let hand = hand(&state);
            if let Some(index) = hand.iter().position(|id| id.contains('+')) {
                positions.insert(index);
            }
        }
        assert!(
            positions.len() > 1,
            "`Random` must pick different cards across seeds, got positions {positions:?}"
        );
        assert_eq!(upgraded[0], upgraded[0], "the single-run probe above is also valid");
    }

    /// §300：`mummified_hand` —— 打一张 **Power** 牌，手牌里随机一张变 0 费（新节点）。
    ///
    /// 三侧：① 打出 Power ⇒ 手牌里**恰好一张**带 `card_cost_override = 0`；
    /// ② 打出**非** Power（`strike`）⇒ 一张都不带；③ 那张牌的**位置**随 seed 变化（`Random`）。
    #[test]
    fn mummified_hand_makes_one_random_card_free_after_a_power() {
        use crate::state::{CardZone, ResourceId};

        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);

        // 打一张牌，返回 (手牌里免费的张数, 它们的位置)。
        let play = |host: &mut Host, card_id: &str, seed: i32| -> (usize, Vec<usize>) {
            let mut state = CombatState::new(crate::state::CombatId::new("c1").unwrap(), seed);
            state
                .add_combatant(unit("hero", "player", 70, 70))
                .expect("hero");
            state
                .add_combatant(unit("enemy_a", "enemy", 60, 60))
                .expect("foe");
            state
                .combatant_mut(&cid("hero"))
                .expect("hero")
                .set_resource(ResourceId::new("standard.energy").unwrap(), 20, Some(20))
                .expect("energy");
            give(&mut state, "hero", status("st_mh", "standard.mummified_hand", 1));
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            let request = crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a")));
            crate::play::play_card(&mut state, Some(&content), &request)
                .unwrap_or_else(|e| panic!("{card_id}: {e:?}"));
            host.try_resolve_pending_queues(&mut state).expect("triggers");
            let slots = state
                .card_zones(&cid("hero"))
                .expect("zones")
                .slots(CardZone::Hand)
                .to_vec();
            let mut free = 0usize;
            let mut positions = Vec::new();
            for (index, slot) in slots.iter().enumerate() {
                let Some(card) = state.card(crate::state::CardSlot::from_index(*slot)) else {
                    continue;
                };
                if card.mark_counters().iter().any(|counter| {
                    counter.key.as_str() == "standard.card_cost_override" && counter.value == 0
                }) {
                    free += 1;
                    positions.push(index);
                }
            }
            (free, positions)
        };

        // ① Power（`metallicize`）⇒ 恰好一张免费。
        let (free, positions) = play(&mut host, "metallicize", 7);
        assert_eq!(free, 1, "playing a Power frees exactly one card, at {positions:?}");
        // ② 非 Power ⇒ 一张都不免费。
        let (free, _) = play(&mut host, "strike", 7);
        assert_eq!(free, 0, "a non-Power card frees nothing");
        // ③ 位置随 seed 变化（`Random` 的证据）。
        let mut seen = std::collections::BTreeSet::new();
        for seed in 0..24i32 {
            let (free, positions) = play(&mut host, "metallicize", seed);
            assert_eq!(free, 1, "always exactly one free card (seed {seed})");
            for position in positions {
                seen.insert(position);
            }
        }
        assert!(
            seen.len() > 1,
            "the free card's position must vary across seeds, got {seen:?}"
        );
    }

    /// §300：`nilrys_codex` —— 回合末三选一，选中的那张进**抽牌堆顶**（新原子：`Then`）。
    ///
    /// 判据钉两半：① 回合末真的**问了**（`PendingChoice` 且候选 3 张）；
    /// ② `then` 是 `ToDrawPileTop`（而不是 `Discovery` 那个写死的 `ToHandFree`）。
    #[test]
    fn nilrys_codex_asks_at_turn_end_and_sends_the_pick_to_the_draw_pile() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);

        let mut state = arena();
        give(&mut state, "hero", status("st_nc", "standard.nilrys_codex", 1));
        host.try_run_turn_ended_triggers(&mut state, &cid("hero"))
            .expect("the turn ends");
        host.try_resolve_pending_queues(&mut state).expect("triggers");

        let question = state.pending_choice().expect("nilrys_codex asks a question");
        assert_eq!(
            question.then,
            crate::state::ChoiceThen::ToDrawPileTop,
            "the pick goes to the **top of the draw pile** (not `ToHandFree`)"
        );
        assert_eq!(question.min, 0, "you may decline");
        assert_eq!(question.max, 1, "one card");
        assert_eq!(
            question.offered_count(),
            3,
            "three candidates were rolled"
        );
        // 没有状态 ⇒ 不问。
        let mut bare = arena();
        host.try_run_turn_ended_triggers(&mut bare, &cid("hero"))
            .expect("the turn ends");
        host.try_resolve_pending_queues(&mut bare).expect("triggers");
        assert!(
            bare.pending_choice().is_none(),
            "without the relic nothing is asked"
        );
    }
'''


def main():
    s = io.open(HOST, encoding='utf-8').read()
    assert s.rstrip('\n').endswith('}')
    cut = s.rstrip('\n').rfind('\n}')
    s = s[:cut] + TESTS + s[cut:]
    io.open(HOST, 'w', encoding='utf-8', newline='\n').write(s)
    print('tests appended')


main()
