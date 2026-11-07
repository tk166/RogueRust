"""§253 判据：`node.playCard` 通道（`Wish` 打出不可打出的牌）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §248：`Enlightenment` —— **降到至多 1**'

TESTS = r'''    /// §253：`play_card_from_program` —— **默认照参考 no-op**，只有显式越门才真的打出。
    ///
    /// 判据两段，缺一段这条通道就不可信：
    /// ① `ignore_unplayable = false` ⇒ `Ok(false)`、牌还在手上、力量没变（**参考的行为**）；
    /// ② `true` ⇒ `Ok(true)`、力量 +3、牌离手（**StS 的 `Wish` 的行为**）。
    ///
    /// 只测 ② 的话，"默认就能打诅咒"这种回归会漏过去 —— 而那会让所有诅咒变成可打出的牌。
    #[test]
    fn play_card_from_program_respects_unplayable_unless_told_otherwise() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        fill_energy(&mut state, 99);
        give_card(&mut state, "hero", CardZone::Hand, "alm1", "become_almighty", None);
        let card = crate::state::CardInstanceId::new("alm1").expect("id");

        // ① 默认：照参考 no-op。
        let played = crate::play::play_card_from_program(
            &mut state,
            &content,
            &cid("hero"),
            &card,
            None,
            false,
        )
        .expect("no-op is not an error");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert!(!played, "unplayable + default ⇒ nothing happens");
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 1, "still in hand");
        assert_eq!(stacks_of(&state, "hero", "standard.strength"), 0, "no Strength");

        // ② 越门：`Wish` 的语义。
        let played = crate::play::play_card_from_program(
            &mut state,
            &content,
            &cid("hero"),
            &card,
            None,
            true,
        )
        .expect("playing it through the program channel works");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert!(played, "IgnoreUnplayable ⇒ it really is played");
        assert_eq!(
            stacks_of(&state, "hero", "standard.strength"),
            3,
            "become_almighty: +3 Strength"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile)
                + zone_count(&state, "hero", CardZone::DiscardPile),
            1,
            "it left the hand (its own `PlayedCardDestinationZone` decides where)"
        );
    }

    /// §253：**六种 no-op 里的三种**各测一次 —— 它们都必须是"安静地什么都不做"，不是错误。
    ///
    /// ① 玩家不在牌区里（给的实例根本不存在）；② 牌不在**手牌**（在抽牌堆里）；
    /// ③ 付不起费用。参考对这三种全是 no-op（`PlayCardEffects.cs:26-96`）；
    /// 把它们变成 `Err` 会让一张牌的边角情况炸掉整场战斗。
    #[test]
    fn play_card_from_program_is_a_quiet_no_op_when_it_cannot_play() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();

        // ① 实例不存在。
        let ghost = crate::state::CardInstanceId::new("nobody").expect("id");
        assert!(
            !crate::play::play_card_from_program(
                &mut state, &content, &cid("hero"), &ghost, None, true
            )
            .expect("not an error"),
            "a missing instance is a no-op"
        );

        // ② 在抽牌堆里（不在手牌）。
        give_card(&mut state, "hero", CardZone::DrawPile, "shiv_a", "shiv", None);
        let in_pile = crate::state::CardInstanceId::new("shiv_a").expect("id");
        assert!(
            !crate::play::play_card_from_program(
                &mut state, &content, &cid("hero"), &in_pile, None, true
            )
            .expect("not an error"),
            "a card outside the hand is a no-op"
        );

        // ③ 付不起（能量 0，牌费 1）。
        give_card(&mut state, "hero", CardZone::Hand, "def1", "defend", None);
        let card = crate::state::CardInstanceId::new("def1").expect("id");
        assert!(
            !crate::play::play_card_from_program(
                &mut state, &content, &cid("hero"), &card, None, true
            )
            .expect("not an error"),
            "unaffordable is a no-op, not an error"
        );
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 1, "it stayed in hand");
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'play_card_from_program_respects_unplayable' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 2 playCard tests')


main()
