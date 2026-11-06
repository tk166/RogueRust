"""§248 判据：Enlightenment（SetMin）/ Madness（随机一张 Set 0）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §247：`Mind Blast` —— 伤害 = **抽牌堆的张数**'

TESTS = r'''    /// §248：`Enlightenment` —— **降到至多 1**（`SetMin`），不是"设成 1"。
    ///
    /// 三段，第二段是这一节存在的全部理由（§247 就是被它挡回的）：
    /// ① 2 费牌 ⇒ 只收 1；
    /// ② **0 费牌 ⇒ 仍然是 0**（`Set` 会把它抬成 1 —— 免费牌变收费牌，页面上看不出来）；
    /// ③ 3 费牌 ⇒ 只收 1（"降到 1"而不是"减 1"）。
    #[test]
    fn enlightenment_caps_hand_costs_at_one() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 返回"打完 Enlightenment 后再打 `card_id` 花掉多少能量"。
        let cost_after = |card_id: &str| -> i32 {
            let mut host = Host::new(&content);
            let mut state = arena();
            state
                .combatant_mut(&cid("hero"))
                .expect("hero")
                .set_resource(
                    crate::state::ResourceId::new("standard.energy").expect("energy"),
                    9,
                    Some(99),
                )
                .expect("the pool accepts a bigger cap");
            if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
                enemy.health_max = 200;
                enemy.health_current = 200;
            }
            give_card(&mut state, "hero", CardZone::Hand, "card_t", card_id, None);
            give_card(&mut state, "hero", CardZone::Hand, "card_en", "enlightenment", None);
            let enlighten = crate::state::CardInstanceId::new("card_en").expect("short id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), enlighten, Some(cid("enemy_a"))),
            )
            .expect("enlightenment is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");

            let before = energy_of(&state, "hero");
            let target = crate::state::CardInstanceId::new("card_t").expect("short id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), target, Some(cid("enemy_a"))),
            )
            .expect("the discounted card is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            before - energy_of(&state, "hero")
        };

        assert_eq!(cost_after("bash"), 1, "a 2-cost card now costs 1");
        assert_eq!(cost_after("bludgeon"), 1, "a 3-cost card costs 1 too (capped, not reduced)");
        assert_eq!(
            cost_after("flex"),
            0,
            "a 0-cost card STAYS at 0 -- `SetMin`, not `Set`"
        );
    }

    /// §248：`Madness` —— 手里**恰好一张**变成 0 费，其余不动；而且**不是总挑第一张**。
    ///
    /// 三段：
    /// ① 三张 2 费牌、打完 Madness ⇒ 只有**一张**免费（两张仍收 2）；
    /// ② 同一局面换种子 ⇒ 免费的那张**会换人**（`Order: "Random"` 真的在洗；
    ///    一个"总是取第一张"的实现会让 ① 也过）；
    /// ③ 打得出的前提也一起钉：Madness 自己 1 费、自消耗。
    #[test]
    fn madness_frees_exactly_one_random_hand_card() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 返回"三张 bash 里哪几张变成 0 费"（按 `card_a/b/c` 的顺序）。
        let freed = |seed: i32| -> Vec<bool> {
            let mut host = Host::new(&content);
            let mut state = CombatState::new(CombatId::new("c1").unwrap(), seed);
            state.add_combatant(unit("hero", "player", 70, 70)).unwrap();
            state.add_combatant(unit("enemy_a", "enemy", 20, 20)).unwrap();
            state
                .combatant_mut(&cid("hero"))
                .expect("hero")
                .set_resource(
                    crate::state::ResourceId::new("standard.energy").expect("energy"),
                    9,
                    Some(99),
                )
                .expect("the pool accepts a bigger cap");
            for id in ["card_a", "card_b", "card_c"] {
                give_card(&mut state, "hero", CardZone::Hand, id, "bash", None);
            }
            give_card(&mut state, "hero", CardZone::Hand, "card_m", "madness", None);
            let madness = crate::state::CardInstanceId::new("card_m").expect("short id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), madness, Some(cid("enemy_a"))),
            )
            .expect("madness is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");

            let mut out = Vec::new();
            for id in ["card_a", "card_b", "card_c"] {
                let card = state
                    .find_card(&cid("hero"), &crate::state::CardInstanceId::new(id).unwrap())
                    .and_then(|(_, slot)| state.card(slot))
                    .expect("the card is still in hand");
                let free = card
                    .mark_counters()
                    .iter()
                    .any(|counter| {
                        counter.key.as_str() == crate::state::CARD_COST_OVERRIDE_COUNTER
                            && counter.value == 0
                    });
                out.push(free);
            }
            // ③ Madness 自己进了消耗堆（"Exhaust"）。
            assert!(
                zone_definitions(&state, "hero", CardZone::ExhaustPile)
                    .iter()
                    .any(|id| id == "madness"),
                "Madness exhausts itself"
            );
            out
        };

        // ① 恰好一张。
        for seed in [1, 2, 3, 4, 5] {
            let marks = freed(seed);
            assert_eq!(
                marks.iter().filter(|free| **free).count(),
                1,
                "seed {seed}: exactly one card is free ({marks:?})"
            );
        }
        // ② 换种子会换人（否则 `Order: Random` 没生效，只是"总取第一张"）。
        let picks: Vec<usize> = [1, 2, 3, 4, 5, 6, 7, 8]
            .iter()
            .map(|seed| {
                let marks = freed(*seed);
                marks.iter().position(|free| *free).expect("one is free")
            })
            .collect();
        assert!(
            picks.iter().any(|pick| *pick != picks[0]),
            "the free card changes with the seed: {picks:?}"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'enlightenment_caps_hand_costs' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 2 tests')


main()
