"""§225 C: tests for the two exhaust-the-hand cards, and one audit test for every exhaust path."""
import io

H = 'kernel/rd-core/src/host.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


one(H, '''    /// §222：§221 加的十张牌''',
    '''    /// §225：`Second Wind` / `Fiend Fire` —— 整手牌逐张消耗，每张换一份效果。
    ///
    /// 这两张牌同时钉住三件事：
    /// ① `forEachCardInZone` 的快照语义（循环体搬走卡不影响这一趟）；
    /// ② 迭代卡的 **tag 位**被填进 `event_flags`（§225 A），否则"**非攻击**牌"会把攻击牌也算进去；
    /// ③ 消耗走 `moveCardToZone` ⇒ `move_card_for` ⇒ `LifecyclePrograms[Exhausted]`（§220 那条路）。
    #[test]
    fn the_hand_exhausting_cards_do_what_their_pages_say() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① `Second Wind`：手里 1 张打击（attack）+ 1 张防御（skill）⇒ 只消耗防御、只给 5 格挡。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        let card = card_in_hand(&mut state, &content, "hero", "second_wind");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("second wind is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            block_of(&state, "hero"),
            5,
            "wiki: Gain 5 Block for each card Exhausted -- one card (the Skill), so 5"
        );
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::Hand),
            vec!["strike".to_string()],
            "the Attack card is still in hand: non-Attack is the filter"
        );
        let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile);
        assert!(
            exhausted.contains(&"defend".to_string()) && exhausted.contains(&"second_wind".to_string()),
            "the Skill and the Second Wind itself are exhausted, got {exhausted:?}"
        );
        assert!(
            !exhausted.contains(&"strike".to_string()),
            "the Attack card must NOT be exhausted"
        );

        // ② `Fiend Fire`：整手牌（含那张打击）逐张消耗，每张打 7。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        let card = card_in_hand(&mut state, &content, "hero", "fiend_fire");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("fiend fire is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            health(&state, "enemy_a"),
            20 - 14,
            "wiki: deal 7 for each card Exhausted -- two cards, so 14"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            0,
            "the whole hand is gone"
        );
        let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile);
        for expected in ["strike", "defend", "fiend_fire"] {
            assert!(
                exhausted.contains(&expected.to_string()),
                "{expected} must be exhausted, got {exhausted:?}"
            );
        }
    }

    /// §225：**消耗审计** —— 内核里把牌送进消耗堆的路径必须**都**跑 `LifecyclePrograms[Exhausted]`。
    ///
    /// 这条测试是本节"确认消耗逻辑是否统一"的机器版。三条路径，一条都不能漏：
    /// * **打出即消耗**（`PlayedCardDestinationZone = ExhaustPile`，经 `MoveCardToZone` 请求）；
    /// * **虚无**（`TurnEndHandDestinationZone = ExhaustPile`，经回合末弃手牌）；
    /// * **内容驱动**（`node.moveCardToZone` 指向消耗堆，经同一个 `move_card_for`）。
    ///
    /// 判据用 `sentinel`（它有一条 `Exhausted` 节目：+2 能量），因为"节目跑过"比"牌到了那个区"
    /// 更能说明问题 —— 牌到位但没有节目，正是 §220 之前的状态。
    #[test]
    fn every_way_into_the_exhaust_pile_runs_the_exhausted_program() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 打出即消耗：`sentinel` 不是"打出即消耗"的牌，用 `slimed` 不行（它没有节目）
        //    —— 所以这条路径改用"把 sentinel 经内容搬到消耗堆"，见 ③。
        // ② 虚无：回合末把 `sentinel` 送进消耗堆（`TurnEndHandDestinationZone = ExhaustPile`）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_s1", "sentinel", None);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        give_energy(&mut state, "hero", 0);
        let before = energy_of(&state, "hero");
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            1,
            "the ethereal sweep moved it"
        );
        assert_eq!(
            energy_of(&state, "hero"),
            before + 2,
            "and the `Exhausted` program ran (+2 energy)"
        );

        // ③ 内容驱动：`node.moveCardToZone` 指到消耗堆 —— 与 ② 是**同一条** `move_card_for`。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_s2", "sentinel", None);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        give_energy(&mut state, "hero", 0);
        let before = energy_of(&state, "hero");
        let slot = state
            .card_zones(&cid("hero"))
            .and_then(|zones| zones.slot_at(CardZone::Hand, 0))
            .expect("the sentinel is in hand");
        let card_id = state.card(slot).expect("card").id;
        state
            .enqueue_effect(rd_core::state::EffectRequest::MoveCardToZone {
                owner: cid("hero"),
                card: card_id,
                to_zone: CardZone::ExhaustPile,
                placement: rd_core::state::ZonePlacement::Bottom,
            })
            .expect("enqueue");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            energy_of(&state, "hero"),
            before + 2,
            "a content-driven move into the exhaust pile runs the same program"
        );
    }

    /// §222：§221 加的十张牌''',
    'two tests')
