"""§245 判据：apotheosis / thinking_ahead / panic_button。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §244：`Chrysalis` / `Metamorphosis` / `Jack of All Trades`'

TESTS = r'''    /// §245：`Apotheosis` —— **全部牌区**的牌都升级（不是只升手牌）。
    ///
    /// 判据必须跨牌区断言：只测手牌的话，"只升手牌"的实现也会全绿（Armaments 就是那个语义）。
    /// 所以四个区分开放牌、再逐区检查。
    #[test]
    fn apotheosis_upgrades_every_zone() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_h", "strike", None);
        give_card(&mut state, "hero", CardZone::DrawPile, "card_d", "defend", None);
        give_card(&mut state, "hero", CardZone::DiscardPile, "card_s", "bash", None);
        give_card(&mut state, "hero", CardZone::ExhaustPile, "card_e", "cleave", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_x", "apotheosis", None);
        let instance = crate::state::CardInstanceId::new("card_x").expect("short id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), instance, Some(cid("enemy_a"))),
        )
        .expect("apotheosis is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        // 四个区各一张，现在都该是 `+` 行。
        for (zone, expected) in [
            (CardZone::Hand, "strike+"),
            (CardZone::DrawPile, "defend+"),
            (CardZone::DiscardPile, "bash+"),
            (CardZone::ExhaustPile, "cleave+"),
        ] {
            assert!(
                zone_definitions(&state, "hero", zone)
                    .iter()
                    .any(|id| id == expected),
                "{zone:?} should hold {expected}: {:?}",
                zone_definitions(&state, "hero", zone)
            );
        }
        assert!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile)
                .iter()
                .any(|id| id == "apotheosis"),
            "apotheosis itself was upgraded too (it is a card in the exhaust pile now)"
        );
    }

    /// §245：`Panic Button` —— 30/40 格挡，**然后**"2 回合内不能从牌里获得格挡"。
    ///
    /// 三段，第三段是这条判据的价值所在：
    /// ① 它自己给的格挡照常到账（先给后挂，队列顺序决定）；
    /// ② 状态在身上的时候，**牌**给的格挡是 0；
    /// ③ 状态在身上的时候，**状态/遗物**（不带 `resolving_card`）给的格挡**照常** ——
    ///    "不能从**牌**里获得"而不是"不能获得"。少了第 ③ 段，一个"有状态就全拦"的实现也全绿。
    #[test]
    fn panic_button_only_blocks_block_from_cards() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 自己那一发照常到账。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_x", "panic_button", None);
        let instance = crate::state::CardInstanceId::new("card_x").expect("short id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), instance, Some(cid("enemy_a"))),
        )
        .expect("panic button is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 30, "its own 30 Block lands");
        assert_eq!(
            stacks_of(&state, "hero", "standard.no_block_from_cards"),
            1,
            "and the lock is on"
        );

        // ② 牌给的格挡：0。
        let card = card_in_hand(&mut state, &content, "hero", "defend");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("defend is still playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 30, "Defend adds nothing while the lock is on");

        // ③ 状态给的格挡照常（`metallicize` 是 `TurnEnded` 触发器，节目里没有 resolving card）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_met", "standard.metallicize", 4));
        give(&mut state, "hero", status("st_nb", "standard.no_block_from_cards", 1));
        turn::end_current_turn(&mut state, &config(), &mut host).expect("turn ends");
        assert_eq!(
            block_of(&state, "hero"),
            4,
            "Metallicize still grants Block -- the lock is 'from cards', not 'from anything'"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'apotheosis_upgrades_every_zone' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 3 tests')


main()
