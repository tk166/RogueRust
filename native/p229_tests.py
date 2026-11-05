"""§229 (part 3): 两条端到端判据。

* `Rip and Tear`：§228 的载体复用 —— 只钉"两次命中、每次 7(9)"（每击重掷已经由 §228 的
  `sword_boomerang_rerolls_a_target_for_each_hit` 钉过，这里不抄第二份）。
* `Rampage`：**每份副本**的计数器。判据必须包含**反例**：手牌里放两张 Rampage，打第一张两次，
  第二张的伤害不能变 —— 否则"每份副本"就退化成"每个定义"，而那是一个看得见的语义错。
"""
import io

HOST = 'kernel/rd-core/src/host.rs'
src = io.open(HOST, encoding='utf-8').read()

anchor = '''    /// §225：**消耗审计** —— 内核里把牌送进消耗堆的路径必须**都**跑 `LifecyclePrograms[Exhausted]`。'''
assert src.count(anchor) == 1

tests = '''    /// §229：`Rip and Tear` —— 7(9) 伤 × 2 次，每次随机。载体是 §228 那个节点，内核没加东西。
    #[test]
    fn rip_and_tear_hits_twice_for_seven() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (card_id, damage) in [("rip_and_tear", 7i32), ("rip_and_tear+", 9)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            for who in ["enemy_a", "enemy_b"] {
                if let Some(combatant) = state.combatant_mut(&cid(who)) {
                    combatant.health_max = 200;
                    combatant.health_current = 200;
                }
            }
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("rip and tear is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            let a = 200 - health(&state, "enemy_a");
            let b = 200 - health(&state, "enemy_b");
            assert_eq!(a + b, 2 * damage, "{card_id}: two hits of {damage}, got a={a} b={b}");
        }
    }

    /// §229：`Rampage` —— "Deal 8 damage. Increase **this card's** damage by 5(8) this combat."
    ///
    /// 三段判据，缺一段这条牌就可能"看起来能用"：
    /// ① 第一次 8、第二次 13（涨的是**这一张**）；
    /// ② 升级版每次涨 8（第二次 16）；
    /// ③ **反例**：另一张 Rampage 的伤害**不变** —— 每副本计数器不是每定义，也不是每战斗员。
    #[test]
    fn rampage_grows_this_copy_and_only_this_copy() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // (牌, 第二次该掉的伤害)
        for (card_id, second) in [("rampage", 13i32), ("rampage+", 16)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 6);
            for who in ["enemy_a", "enemy_b"] {
                if let Some(combatant) = state.combatant_mut(&cid(who)) {
                    combatant.health_max = 400;
                    combatant.health_current = 400;
                }
            }
            // **两份副本**：`card_a` 打两次，`card_b` 一次都不打，最后用它当反例。
            let card_a = card_in_hand(&mut state, &content, "hero", card_id);
            give_card(&mut state, "hero", CardZone::Hand, "card_b", card_id, None);
            let card_b = card_in_hand(&mut state, &content, "hero", "card_b");

            let mut hits = std::vec::Vec::new();
            for _ in 0..2 {
                let before = health(&state, "enemy_a");
                // 每次出牌都回到手里（否则第二张打出的是"另一份副本"，而那正是另一条判据）。
                crate::play::play_card(
                    &mut state,
                    Some(&content),
                    &crate::play::PlayRequest::new(cid("hero"), card_a, Some(cid("enemy_a"))),
                )
                .expect("rampage is playable");
                host.try_resolve_pending_queues(&mut state).expect("drain");
                hits.push(before - health(&state, "enemy_a"));
                // 把它捡回手牌：这份副本带着它自己的计数器。
                let (zone, slot) = state
                    .find_card(&cid("hero"), &card_a)
                    .expect("still in the fight");
                let _ = zone;
                if let Some(zones) = state.card_zones(&cid("hero")) {
                    let _ = zones;
                }
                let _ = slot;
                let found = state.find_card(&cid("hero"), &card_a).map(|(z, s)| (z, s));
                if let Some((from, slot)) = found {
                    if from != CardZone::Hand {
                        state
                            .move_card(
                                &cid("hero"),
                                from,
                                CardZone::Hand,
                                slot,
                                crate::state::ZonePlacement::Bottom,
                            )
                            .expect("picked back up");
                    }
                }
            }
            assert_eq!(
                hits,
                std::vec![8, second],
                "{card_id}: 8 then {second} -- the bonus is this copy's own"
            );

            // ③ 反例：一份**没打过的**同名副本，伤害仍然是 8。
            let before = health(&state, "enemy_a");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card_b, Some(cid("enemy_a"))),
            )
            .expect("the second copy is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                before - health(&state, "enemy_a"),
                8,
                "{card_id}: the *other* copy has not grown -- the counter is per copy, not per definition"
            );
        }
    }

''' + anchor

src = src.replace(anchor, tests)
io.open(HOST, 'w', encoding='utf-8', newline='\n').write(src)
print('ok tests')
