"""§239 判据：`Burning Pact`（消耗一张 + 抽牌）与它的**顺序偏差**。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §239：`Clash` —— **手牌全是攻击牌才能打**'

TESTS = '''    /// §239：`Burning Pact` —— "Exhaust 1 card. Draw 2 cards."
    ///
    /// 这条判据同时把一处**顺序偏差**写死成断言（不让它以后悄悄变）：StS 是"先消耗、再抽"，
    /// 而本内核的节目会把整棵树先派发完 ⇒ 抽牌请求在**问句还开着的时候**就落地了。
    ///
    /// 为什么可以接受：候选清单在提问那一刻就快照了（`begin_choice` 的 `candidates`），所以
    /// "能消耗哪几张"在两种顺序下**完全一样**；而**终态也完全一样**
    /// （`H \ {c} ∪ {d1,d2}`）。唯一看得见差别的是"问句开着时手牌已经多了两张"。
    #[test]
    fn burning_pact_exhausts_a_card_and_draws() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        for index in 0..3 {
            give_card(&mut state, "hero", CardZone::Hand,
                      &std::format!("card_s{index}"), "strike", None);
        }
        for index in 0..2 {
            give_card(&mut state, "hero", CardZone::DrawPile,
                      &std::format!("card_d{index}"), "defend", None);
        }
        let card = card_in_hand(&mut state, &content, "hero", "burning_pact");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("burning pact is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let choice = state.pending_choice().expect("it asks which card to Exhaust");
        assert_eq!(choice.source.zone(), Some(CardZone::Hand), "candidates come from hand");
        assert_eq!((choice.min, choice.max), (1, 1), "exactly one card");
        assert_eq!(
            choice.then,
            crate::state::ChoiceThen::Exhaust,
            "the `then` is Exhaust, not a copy/upgrade"
        );
        // 偏差（见文档）：问句开着时，那两张**已经**抽到手里了。
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            3 + 2,
            "the draw already landed while the question is open (StS draws after the Exhaust)"
        );

        // 回答：消耗掉第一张 strike。
        let picks = [state
            .zone_cards(&cid("hero"), CardZone::Hand)
            .find(|card| card.id.as_str() == "card_s0")
            .expect("card_s0 is in hand")
            .id];
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&picks), 0)
            .expect("the answer is accepted");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        assert_eq!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile),
            [CardDefinitionId::new("strike").unwrap()],
            "the chosen card is the only thing in the Exhaust pile"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            4,
            "3 - the exhausted one + the 2 drawn"
        );
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DiscardPile),
            [CardDefinitionId::new("burning_pact").unwrap()],
            "Burning Pact itself is **not** exhausted (the wiki `Exhaust` there is a verb)"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'burning_pact_exhausts_a_card_and_draws' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 1 test')


main()
