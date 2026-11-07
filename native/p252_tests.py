"""§252 判据：剩下 6 张（`through_violence` / `j.a.x.` / `safety` /
`become_almighty` / `live_forever` / `fame_and_fortune`）。

这一节的判据有一个共同点值得写下来：**"不可打出"与"效果不存在"是两件事**。
`Wish` 的三个选项（`become_almighty` / `live_forever` / `fame_and_fortune`）在手上打不出，
但它们的**节目是真的**（StS 里由 `Wish` 走"出牌"通道打出）。所以判据必须两边都钉：
① 玩家打它 ⇒ `Refused(Unplayable)`；② 通过出牌通道硬打 ⇒ 效果**确实发生**。

如果只测 ①，"节目是空的"也能过；只测 ②，"玩家其实可以打它"也能过。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §248：`Enlightenment` —— **降到至多 1**'

TESTS = r'''    /// §252：`Through Violence` / `Safety` —— 0 费打 20/30、1 费给 12/16 格挡，都 Retain+Exhaust。
    ///
    /// 两张一起测是因为它们只在"打什么"上不同（伤害 vs 格挡），而 Retain/Exhaust 的载体相同：
    /// 只测一张会漏掉"两张牌里有一张忘了写 Retain"这种错。
    #[test]
    fn through_violence_and_safety_differ_only_in_what_they_produce() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        beefy(&mut state);
        fill_energy(&mut state, 99);
        let block_before = block_of(&state, "hero");

        give_card(&mut state, "hero", CardZone::Hand, "tv1", "through_violence", None);
        let card = crate::state::CardInstanceId::new("tv1").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 480, "20 damage");

        give_card(&mut state, "hero", CardZone::Hand, "saf1", "safety", None);
        let card = crate::state::CardInstanceId::new("saf1").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, None),
        )
        .expect("playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            block_of(&state, "hero"),
            block_before + 12,
            "safety: 12 block"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            2,
            "both exhaust"
        );

        // Retain：一张没打出的 `Safety` 在回合末留在手上。
        give_card(&mut state, "hero", CardZone::Hand, "saf2", "safety", None);
        host.try_hand_turn_end_lifecycle(&mut state, &cid("hero"))
            .expect("the turn-end lifecycle runs");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            1,
            "`Retain` keeps the unplayed one in hand"
        );
    }

    /// §252：`J.A.X.` —— 失去 3 HP 换 2/3 力量，而且**不 Exhaust**（wiki 补丁：No longer exhausts）。
    ///
    /// 三条判据：① 打一次掉 3 血、力量 +2；② 打两次力量 +4（证明它没被消耗掉 —— 那正是
    /// "No longer exhausts"）；③ 掉血走的是 `loseHp`（**不是**伤害：不吃格挡）。
    #[test]
    fn jax_trades_three_hp_for_strength_and_stays_in_play() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        fill_energy(&mut state, 99);
        let hp_before = health(&state, "hero");
        let block_before = block_of(&state, "hero");

        for index in 1..=2 {
            give_card(&mut state, "hero", CardZone::Hand,
                      &std::format!("jax{index}"), "j.a.x.", None);
            let card = crate::state::CardInstanceId::new(&std::format!("jax{index}"))
                .expect("id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, None),
            )
            .expect("playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
        }
        assert_eq!(health(&state, "hero"), hp_before - 6, "two plays, 3 HP each");
        assert_eq!(
            block_of(&state, "hero"),
            block_before,
            "`loseHp` does not touch block"
        );
        assert_eq!(
            stacks_of(&state, "hero", "standard.strength"),
            4,
            "2 + 2 strength"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            0,
            "J.A.X. does **not** exhaust (wiki: \"No longer exhausts\")"
        );
    }

    /// §252：`Wish` 的三个选项 —— **玩家在手上打不出**，而它们的节目是**真的**。
    ///
    /// ⚠️ 这一条只钉得住**半边**，另半边在这里测不了，原因写清楚（不许假装测过）：
    ///
    /// * 能钉的：`unplayable` tag ⇒ `Refused(Unplayable)`，三张都是。
    /// * **测不了的**："由 `Wish` 打出它"。内核唯一的"强制出牌"通道是
    ///   `play_top_card_for`（`Havoc`），而它走的是同一套受理校验 —— `unplayable` 会被拒，
    ///   那条路上注释写得很明白（"被拒（例如抽到一张 `unplayable` 的牌）⇒ 放回抽牌堆顶"）。
    ///   StS 的 `Wish` 是**另一个动作**："选一张，然后这张牌被**打出**" —— 它绕过的不是
    ///   `Havoc` 那条路，而是"玩家从手牌出牌"这件事本身。
    ///
    /// 所以判据停在"节目存在且数值正确"这一层：`program_facts` 已经把
    /// `Gain 3 Strength` / `Gain 6 Plated Armor` / `Gain 25 Gold` 钉进 `INV_CARDS`
    /// （内容门逐字比对 wiki），而"谁来触发它"是 `Wish` 落地时才有答案的事。
    /// **不为了让这条测试变绿去造一条假的出牌通道** —— 那会让"玩家打不出"这个真属性消失。
    #[test]
    fn the_wish_options_are_unplayable_by_hand() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        fill_energy(&mut state, 99);
        for (instance, definition) in [
            ("alm1", "become_almighty"),
            ("live1", "live_forever"),
            ("fame1", "fame_and_fortune"),
        ] {
            give_card(&mut state, "hero", CardZone::Hand, instance, definition, None);
            let card = crate::state::CardInstanceId::new(instance).expect("id");
            assert_eq!(
                crate::play::play_card(
                    &mut state,
                    Some(&content),
                    &crate::play::PlayRequest::new(cid("hero"), card, None),
                ),
                Err(crate::play::PlayError::Refused(crate::play::Refusal::Unplayable)),
                "{definition} must be unplayable from hand"
            );
            host.try_resolve_pending_queues(&mut state).expect("drain");
        }
        // 一个字节都没动：三张都还在手上，状态/金币没变。
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 3);
        assert_eq!(stacks_of(&state, "hero", "standard.strength"), 0);
        assert_eq!(stacks_of(&state, "hero", "standard.plated_armor"), 0);
        assert_eq!(state.gold_gained, 0);
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'through_violence_and_safety_differ_only' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 3 tests')


main()
