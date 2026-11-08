"""§299：`dead_branch` 的"任意牌"断言要**在同一场战斗里连抽**（不同 seed 的同一 seed 会抽到同一张）。

第一版每次 `run()` 都新建 `arena()`（seed 恒 42、`random_step` 恒 0）⇒ 40 次抽到的是**同一张**，
于是"三种卡都出现"永远不成立。判据本身没写错断言，错在**驱动的形状**。
"""
import io

HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'

OLD = '''        // ★ 池子必须是**任意牌**，不是"某一类"。
        // 负控"池子只要 power"曾经**照样绿** —— 因为上面三条对"随便哪一类的任意一张"都成立。
        // 所以这里连抽 40 次并统计**三种卡的种类**：只收一类的话，另外两类永远不出现。
        let mut kinds = (false, false, false); // (attack, skill, power)
        for _ in 0..40 {
            let hand = run(&mut host, true);
            assert_eq!(hand.len(), 1, "each exhaustion adds one card");
            let tag = |name: &str| content.card_has_tag(&hand[0], name) == Some(true);
            kinds.0 |= tag("attack");
            kinds.1 |= tag("skill");
            kinds.2 |= tag("power");
            if kinds.0 && kinds.1 && kinds.2 {
                break;
            }
        }
        assert!(
            kinds.0 && kinds.1 && kinds.2,
            "the pool is *any* base card, so 40 draws must cover all three kinds; got \\
             attack={} skill={} power={}",
            kinds.0,
            kinds.1,
            kinds.2
        );
    }'''

NEW = '''        // ★ 池子必须是**任意牌**，不是"某一类"。
        // 负控"池子只要 power"曾经**照样绿** —— 上面三条对"随便哪一类的任意一张"都成立。
        // ⚠️ 连抽必须在**同一场战斗里**：每次新建 `arena()` 会拿到同一个 seed 与 `random_step`，
        // 于是抽到的是**同一张**（第一版就是这么写的，40 次全是同一张 skill）。
        let mut kinds = (false, false, false); // (attack, skill, power)
        let mut state = arena();
        give(&mut state, "hero", status("st_db2", "standard.dead_branch", 1));
        for _ in 0..60 {
            let before: Vec<String> = state
                .card_zones(&cid("hero"))
                .expect("zones")
                .slots(crate::state::CardZone::Hand)
                .iter()
                .filter_map(|slot| state.card(crate::state::CardSlot::from_index(*slot)))
                .map(|card| std::string::String::from(card.definition_id.as_str()))
                .collect();
            // 喂一张 `strike` 进去再消耗它（`card_in_hand` 是 append）。
            let card = card_in_hand(&mut state, &content, "hero", "strike");
            state
                .enqueue_effect_with_owner(
                    EffectRequest::MoveCardToZone {
                        owner: cid("hero"),
                        card,
                        to_zone: CardZone::ExhaustPile,
                        placement: crate::state::ZonePlacement::Bottom,
                    },
                    None,
                )
                .unwrap();
            host.try_resolve_pending_queues(&mut state).expect("triggers");
            let after: Vec<String> = state
                .card_zones(&cid("hero"))
                .expect("zones")
                .slots(crate::state::CardZone::Hand)
                .iter()
                .filter_map(|slot| state.card(crate::state::CardSlot::from_index(*slot)))
                .map(|card| std::string::String::from(card.definition_id.as_str()))
                .collect();
            let added: Vec<&String> =
                after.iter().filter(|definition| !before.contains(definition)).collect();
            assert_eq!(added.len(), 1, "each exhaustion adds exactly one card");
            let tag = |name: &str| content.card_has_tag(added[0], name) == Some(true);
            kinds.0 |= tag("attack");
            kinds.1 |= tag("skill");
            kinds.2 |= tag("power");
            if kinds.0 && kinds.1 && kinds.2 {
                break;
            }
        }
        assert!(
            kinds.0 && kinds.1 && kinds.2,
            "the pool is *any* base card, so enough draws must cover all three kinds; got \\
             attack={} skill={} power={}",
            kinds.0,
            kinds.1,
            kinds.2
        );
    }'''


def main():
    s = io.open(HOST, encoding='utf-8').read()
    assert s.count(OLD) == 1, s.count(OLD)
    io.open(HOST, 'w', encoding='utf-8', newline='\n').write(s.replace(OLD, NEW))
    print('drive fixed')


main()
