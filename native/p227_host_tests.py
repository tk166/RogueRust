"""§227 (part 6): 三张牌的端到端判据（真内容 + 真 Host）。

* `Armaments`：5 格挡 + 一个"升级哪张"的问句；**没有 `+` 行的牌不进候选**（`dazed`）；
* `Warcry`：抽 1 张 + 一个"放哪张到抽牌堆顶"的问句；答完那张牌**真的在堆顶**；
* `Nightmare`：选一张 ⇒ 3 份副本进 `SetAsidePile`，回合走一圈之后**在手里**，状态自摘。
"""
import io

HOST = 'kernel/rd-core/src/host.rs'
src = io.open(HOST, encoding='utf-8').read()

anchor = '''    /// §225：**消耗审计** —— 内核里把牌送进消耗堆的路径必须**都**跑 `LifecyclePrograms[Exhausted]`。'''
assert src.count(anchor) == 1

tests = '''    /// §227：`Armaments` —— 5 格挡 + "升级手牌里的一张（整场有效）"。
    ///
    /// 判据的重点不是"程序跑完了"，而是**候选本身就是规则**：
    /// * 问句里只有**有 `+` 行**的牌（`strike` / `defend`），`dazed` 不该出现 ——
    ///   否则玩家会拿到一个"点了什么都不发生"的选项；
    /// * 答完之后手牌**张数不变**（`Upgrade` 是原地改定义 id，不是搬牌），而那张牌的定义变成 `<id>+`。
    #[test]
    fn armaments_gains_block_then_upgrades_the_chosen_card() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        // `dazed` 没有 `+` 行 ⇒ 它必须**不在**候选里（那张牌升级不了）。
        give_card(&mut state, "hero", CardZone::Hand, "card_junk", "dazed", None);
        let card = card_in_hand(&mut state, &content, "hero", "armaments");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("armaments is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        assert_eq!(block_of(&state, "hero"), 5, "wiki: Gain 5 Block");
        let choice = state.pending_choice().expect("it asks which card to upgrade");
        assert_eq!(choice.then, crate::state::ChoiceThen::Upgrade);
        let mut legal = [CardInstanceId::EMPTY; 8];
        let count = state.choice_legal(&mut legal).expect("the options are listable");
        let options: Vec<String> = legal[..count]
            .iter()
            .map(|id| {
                state
                    .card(state.find_card(&cid("hero"), id).expect("in hand").1)
                    .expect("the card")
                    .definition_id
                    .as_str()
                    .to_string()
            })
            .collect();
        assert_eq!(
            options,
            vec!["strike".to_string(), "defend".to_string()],
            "only the cards that have a `+` row: {options:?}"
        );

        let hand_before = zone_definitions(&state, "hero", CardZone::Hand);
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&legal[..1]), 0)
            .expect("the upgrade is taken");
        let hand_after = zone_definitions(&state, "hero", CardZone::Hand);
        assert_eq!(hand_after.len(), hand_before.len(), "upgrading moves nothing");
        assert!(
            hand_after.iter().any(|id| id.as_str() == "strike+"),
            "the picked Strike is upgraded, got {hand_after:?}"
        );
        assert!(
            hand_after.iter().any(|id| id.as_str() == "defend"),
            "the other card is untouched, got {hand_after:?}"
        );
    }

    /// §227：`Warcry` —— 抽 1 张，然后"把一张手牌放到抽牌堆顶"。
    ///
    /// "堆顶"必须比"在抽牌堆里"更强：先往抽牌堆放一张垫底的牌，答完之后问"谁在最前面"。
    #[test]
    fn warcry_draws_one_then_puts_the_chosen_card_on_top() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        // 垫底：这张牌进抽牌堆之后**不该**是下一张。
        give_card(&mut state, "hero", CardZone::DrawPile, "card_bottom", "bash", None);
        let card = card_in_hand(&mut state, &content, "hero", "warcry");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("warcry is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        // 抽 1 张：`bash` 已经从抽牌堆进了手牌。
        let hand = zone_definitions(&state, "hero", CardZone::Hand);
        assert!(
            hand.iter().any(|id| id.as_str() == "bash"),
            "the drawn card joined the hand, got {hand:?}"
        );
        let choice = state.pending_choice().expect("it asks what to put on top");
        assert_eq!(choice.then, crate::state::ChoiceThen::ToDrawPileTop);

        // 选 `defend` 放回堆顶。
        let defend = {
            let mut legal = [CardInstanceId::EMPTY; 8];
            let count = state.choice_legal(&mut legal).expect("listable");
            legal[..count]
                .iter()
                .copied()
                .find(|id| {
                    state
                        .card(state.find_card(&cid("hero"), id).expect("in hand").1)
                        .expect("the card")
                        .definition_id
                        .as_str()
                        == "defend"
                })
                .expect("defend is in the hand")
        };
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&[defend]), 0)
            .expect("the move is taken");

        let draw = zone_definitions(&state, "hero", CardZone::DrawPile);
        assert_eq!(
            draw.first().map(|id| id.as_str()),
            Some("defend"),
            "the picked card is on **top**, got {draw:?}"
        );
        assert_eq!(draw.len(), 2, "the bottom card is still there, got {draw:?}");
        // wiki: "Warcry will then Exhaust itself."
        assert!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile)
                .iter()
                .any(|id| id.as_str() == "warcry"),
            "warcry exhausts itself"
        );
    }

    /// §227：`Nightmare` —— "选一张牌。**下一回合**把这 3 份副本加进手牌。Exhaust."
    ///
    /// "下一回合"整条规则在**内容**里（`standard.nightmare_pending` 的 `TurnStarted` 触发器），
    /// 内核一点都不知道 Nightmare —— 它只需要"复制到某个牌区"这一件事。要记住"复制的是哪张牌"
    /// 的只有那三份副本自己。
    #[test]
    fn nightmare_copies_into_the_aside_pile_and_next_turn_they_arrive() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        let card = card_in_hand(&mut state, &content, "hero", "nightmare");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, None),
        )
        .expect("nightmare is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let choice = state.pending_choice().expect("it asks which card to copy");
        assert_eq!(
            choice.then,
            crate::state::ChoiceThen::Copy {
                copies: 3,
                into: crate::state::CardZone::SetAsidePile,
            },
            "three copies, held aside until next turn"
        );
        // 选那张打击。
        let strike = {
            let mut legal = [CardInstanceId::EMPTY; 8];
            let count = state.choice_legal(&mut legal).expect("listable");
            legal[..count]
                .iter()
                .copied()
                .find(|id| {
                    state
                        .card(state.find_card(&cid("hero"), id).expect("in hand").1)
                        .expect("the card")
                        .definition_id
                        .as_str()
                        == "strike"
                })
                .expect("strike is in the hand")
        };
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&[strike]), 0)
            .expect("the copies are made");

        let aside = zone_definitions(&state, "hero", CardZone::SetAsidePile);
        assert_eq!(aside.len(), 3, "three copies wait aside, got {aside:?}");
        assert!(aside.iter().all(|id| id.as_str() == "strike"), "{aside:?}");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::Hand)
                .iter()
                .filter(|id| id.as_str() == "strike")
                .count(),
            1,
            "the original stays in hand (only the copies were made)"
        );
        let pending = state
            .combatant(&cid("hero"))
            .expect("hero")
            .statuses()
            .iter()
            .any(|instance| instance.definition_id.as_str() == "standard.nightmare_pending");
        assert!(pending, "the pending marker is on the hero");

        // 回合走一圈：结束这一回合、再开始下一回合 ⇒ 触发器把副本搬进手牌并自摘。
        turn::end_current_turn(&mut state, &config(), &mut host).expect("turn ends");
        turn::start_current_turn(&mut state, &config(), &mut host).expect("next turn starts");

        let hand = zone_definitions(&state, "hero", CardZone::Hand);
        assert_eq!(
            hand.iter().filter(|id| id.as_str() == "strike").count(),
            4,
            "the original + 3 copies are in hand, got {hand:?}"
        );
        assert!(
            zone_definitions(&state, "hero", CardZone::SetAsidePile).is_empty(),
            "the aside pile is empty again"
        );
        let still_pending = state
            .combatant(&cid("hero"))
            .expect("hero")
            .statuses()
            .iter()
            .any(|instance| instance.definition_id.as_str() == "standard.nightmare_pending");
        assert!(!still_pending, "the marker removed itself after firing once");
    }

''' + anchor

src = src.replace(anchor, tests)
io.open(HOST, 'w', encoding='utf-8', newline='\n').write(src)
print('ok host tests')
