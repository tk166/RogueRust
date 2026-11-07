"""§254 判据：`Wish` —— 「选一张，它立刻被打出」。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §248：`Enlightenment` —— **降到至多 1**'

TESTS = r'''    /// §254：`Wish` —— 三个选项**都真的会被打出来**，而且那张牌**不进手牌**。
    ///
    /// 一次测三个选项是刻意的：它们的载体同一条路（`offerCards` → `PlayChosen` →
    /// `EffectRequest::PlayCard`），但**效果落在三个完全不同的地方**
    /// （状态 / 状态 / 战斗层的金币账）。只测一个的话，"选项表连错了两张"也能过。
    ///
    /// 判据五步（每一步都有它存在的理由）：
    /// ① 问句是 `Offered` + `PlayChosen`，候选**恰好是那三张、按给定顺序**；
    /// ② 选 `become_almighty` ⇒ 力量 +3；
    /// ③ 选 `live_forever` ⇒ 板甲 +6；
    /// ④ 选 `fame_and_fortune` ⇒ `gold_gained` +25（§250 那本战斗层的账）；
    /// ⑤ **手牌不多一张**、那张选项牌在自己的落区里（`BanishedPile` = 离场，不是 Exhaust）。
    #[test]
    fn wish_offers_three_cards_and_plays_the_pick_at_once() {
        let content = sts_image();
        for (pick, strength, plated, gold) in [
            (0usize, 3i32, 0i32, 0i32),
            (1, 0, 6, 0),
            (2, 0, 0, 25),
        ] {
            let mut host = Host::new(&content);
            let mut state = arena();
            fill_energy(&mut state, 99);
            give_card(&mut state, "hero", CardZone::Hand, "wish1", "wish", None);
            let card = crate::state::CardInstanceId::new("wish1").expect("id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, None),
            )
            .expect("wish is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");

            // ① 问句的形状：三张**固定的**候选，选中的那张会被打出去。
            let question = state.pending_choice().expect("a question is owed");
            assert_eq!(question.source, crate::state::ChoiceSource::Offered);
            assert_eq!(question.then, crate::state::ChoiceThen::PlayChosen);
            let offered: Vec<&str> = question
                .offered
                .as_slice()
                .iter()
                .map(|definition| definition.as_str())
                .collect();
            assert_eq!(
                offered,
                ["become_almighty", "live_forever", "fame_and_fortune"],
                "the three options, in the order the content lists them"
            );

            let hand_before = zone_count(&state, "hero", CardZone::Hand);
            state
                .resolve_choice(crate::state::ChoiceAnswer::Offered(&[pick]), 0)
                .expect("answering with one index works");
            // 打出发生在**排空**里（§254：`resolve_choice` 手里没有内容）。
            host.try_resolve_pending_queues(&mut state).expect("drain");

            // ②③④ 三个选项各落在自己的地方。
            assert_eq!(
                stacks_of(&state, "hero", "standard.strength"),
                strength,
                "pick {pick}: Strength"
            );
            assert_eq!(
                stacks_of(&state, "hero", "standard.plated_armor"),
                plated,
                "pick {pick}: Plated Armor"
            );
            assert_eq!(state.gold_gained, gold, "pick {pick}: gold");

            // ⑤ 那张选项牌**没有留在手牌里**（wiki: "never enter your hand"），
            //    而且它离场的方式是 `BanishedPile`（wiki 没写 Exhaust，所以不许用消耗堆）。
            assert_eq!(
                zone_count(&state, "hero", CardZone::Hand),
                hand_before,
                "pick {pick}: the option did not stay in hand"
            );
            assert_eq!(
                zone_count(&state, "hero", CardZone::BanishedPile),
                1,
                "pick {pick}: it left play"
            );
            assert_eq!(
                zone_count(&state, "hero", CardZone::ExhaustPile),
                1,
                "pick {pick}: only Wish itself exhausted"
            );
        }
    }

    /// §254：`Wish+` 给的是三张 **`+`** 版本 —— 而 wiki 的原话是
    /// "Upgrading Wish itself is the only way to upgrade the cards that it creates"。
    ///
    /// 判据：`Wish+` 的候选是 `become_almighty+` / `live_forever+` / `fame_and_fortune+`，
    /// 选第一个 ⇒ 力量 **+4**（不是 +3）。只断言候选表的话，"候选对了但打出的是基础版"会漏。
    #[test]
    fn wish_plus_offers_the_upgraded_options() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        fill_energy(&mut state, 99);
        give_card(&mut state, "hero", CardZone::Hand, "wishp", "wish+", None);
        let card = crate::state::CardInstanceId::new("wishp").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, None),
        )
        .expect("wish+ is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let question = state.pending_choice().expect("a question is owed");
        let offered: Vec<&str> = question
            .offered
            .as_slice()
            .iter()
            .map(|definition| definition.as_str())
            .collect();
        assert_eq!(
            offered,
            ["become_almighty+", "live_forever+", "fame_and_fortune+"],
            "the upgraded options"
        );
        state
            .resolve_choice(crate::state::ChoiceAnswer::Offered(&[0]), 0)
            .expect("answering works");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            stacks_of(&state, "hero", "standard.strength"),
            4,
            "the upgraded option, not the base one"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'wish_offers_three_cards_and_plays_the_pick_at_once' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 2 Wish tests')


main()
