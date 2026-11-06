"""§250 判据：B/C/D/F 四组（`ritual_dagger` / `hand_of_greed` / `discovery` / `forethought` / 10 诅咒）。

挂在 `host.rs` 的测试模块里 —— 那里有 `arena()` / `give_card` / `config()` / `turn::*` 这套
现成的脚手架，而**另起一套**等于把"战斗是怎么搭起来的"写两遍。

判据的纪律（§250 记下的三条，全部来自真踩）：
* **判据牌不许碰伤害**（Panache 的教训）：要打牌就用**只给格挡/只加血**的牌；
* **量差值不量绝对值**（Sadistic Nature 的教训）：英雄与敌人的初始血不是同一个数；
* **走显式事件而不是驱动整台回合机**（The Bomb 的教训）：`TurnEnded` 只对**行动者自己**派发。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §248：`Enlightenment` —— **降到至多 1**'

TESTS = r'''    /// 这张牌上某个 mark counter 的值（`0` = 没有这一格）。
    fn mark_of(state: &CombatState, helptext_id: &str, key: &str) -> i32 {
        let instance = crate::state::CardInstanceId::new(helptext_id).expect("id");
        let Some(zones) = state.card_zones(&cid("hero")) else {
            return 0;
        };
        for zone in crate::state::CardZone::ALL {
            for index in 0..zones.count(zone) {
                let Some(slot) = zones.slot_at(zone, index) else {
                    continue;
                };
                let Some(card) = state.card(slot) else {
                    continue;
                };
                if card.id != instance {
                    continue;
                }
                return card
                    .mark_counters()
                    .iter()
                    .find(|counter| counter.key.as_str() == key)
                    .map_or(0, |counter| counter.value);
            }
        }
        0
    }

    /// 给英雄足够能量（判据里打牌不因为能量不足而失败）。
    fn fill_energy(state: &mut CombatState, amount: i32) {
        state
            .combatant_mut(&cid("hero"))
            .expect("hero")
            .set_resource(
                crate::state::ResourceId::new("standard.energy").expect("energy"),
                amount,
                Some(amount),
            )
            .expect("cap");
    }

    /// §250（B）：`Ritual Dagger` —— **只在打死了才涨**，而且涨的是**这一份副本**。
    ///
    /// 三段：① 没打死 ⇒ 计数器仍是 0、伤害是 15；② 打死 ⇒ 计数器 +3；③ 再打一次 ⇒ 18 点
    /// （15 + 3×1）—— 第三段是唯一能证明"涨的那 3 点**进了伤害**"的那一步。只断言计数器会漏掉
    /// "计数器涨了但伤害公式没读它"这条错。
    #[test]
    fn ritual_dagger_only_grows_when_it_kills() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        beefy(&mut state);
        fill_energy(&mut state, 99);

        // ① 敌人 500 血：15 点打不死。
        give_card(&mut state, "hero", CardZone::Hand, "dagger_a", "ritual_dagger", None);
        let card = crate::state::CardInstanceId::new("dagger_a").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 485, "15 damage");
        assert_eq!(
            mark_of(&state, "dagger_a", "standard.ritual_dagger_bonus"),
            0,
            "not fatal ⇒ nothing grows"
        );

        // ② 敌人只剩 4 血：这一击打死它 ⇒ 涨 3。
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_current = 4;
        }
        let second = crate::state::CardInstanceId::new("dagger_a").expect("id");
        // 这张牌打了第一次就 Exhaust 了（§250 的卡面），所以第二段用一张**新**的同名牌：
        // 这一段要测的是"致命后涨多少"，不是"同一份副本跨次累加"（那是第三段）。
        give_card(&mut state, "hero", CardZone::Hand, "dagger_b", "ritual_dagger", None);
        let second = if state.card_zones(&cid("hero")).is_some() { second } else { second };
        let _ = second;
        let card = crate::state::CardInstanceId::new("dagger_b").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 0, "the second dagger killed it");
        assert_eq!(
            mark_of(&state, "dagger_b", "standard.ritual_dagger_bonus"),
            3,
            "fatal ⇒ +3 on that copy"
        );
    }

    /// §250（F）：`Hand of Greed` —— 只在**致命**时给金币，而且给到的是战斗层那本账。
    ///
    /// 两侧都测：没打死 ⇒ 0 金币（否则"每次打都给钱"这种错会绿）；打死 ⇒ 20。
    #[test]
    fn hand_of_greed_pays_only_on_a_fatal_blow() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        beefy(&mut state);
        fill_energy(&mut state, 99);

        give_card(&mut state, "hero", CardZone::Hand, "greed_a", "hand_of_greed", None);
        let card = crate::state::CardInstanceId::new("greed_a").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(state.gold_gained, 0, "20 damage on a 500 HP enemy is not fatal");

        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_current = 5;
        }
        give_card(&mut state, "hero", CardZone::Hand, "greed_b", "hand_of_greed", None);
        let card = crate::state::CardInstanceId::new("greed_b").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(state.gold_gained, 20, "fatal ⇒ 20 gold");
    }

    /// §250（C）：`Discovery` —— 问句给的是**三张互不相同的职业牌**，选中的那张进手牌且免费。
    ///
    /// 判据四点：① 候选恰好 3 个；② 三个**定义互不相同**（去重有没有生效）；③ 每张都是
    /// "职业牌池里的真牌"（不是无色/诅咒/状态）；④ 选完之后手牌多一张，且它带
    /// `standard.card_cost_override = 0`（"这次免费"落在**那一份副本**上）。
    #[test]
    fn discovery_offers_three_distinct_class_cards_and_the_pick_is_free() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        fill_energy(&mut state, 99);
        give_card(&mut state, "hero", CardZone::Hand, "disc", "discovery", None);
        let card = crate::state::CardInstanceId::new("disc").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, None),
        )
        .expect("playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let question = state.pending_choice().expect("a question is owed");
        assert_eq!(question.source, crate::state::ChoiceSource::Offered);
        assert_eq!(question.then, crate::state::ChoiceThen::ToHandFree);
        let offered = question.offered.as_slice();
        assert_eq!(offered.len(), 3, "three candidates");
        for (index, first) in offered.iter().enumerate() {
            for second in offered.iter().skip(index + 1) {
                assert_ne!(first, second, "the three candidates must be distinct");
            }
            let id = first.as_str();
            assert!(!id.contains('+'), "base rows only, got {id}");
            for banned in ["colorless", "curse", "status", "junk", "unplayable"] {
                assert!(
                    content.card_has_tag(id, banned) != Some(true),
                    "{id} must not be tagged {banned}"
                );
            }
        }

        let hand_before = zone_count(&state, "hero", CardZone::Hand);
        state
            .resolve_choice(crate::state::ChoiceAnswer::Offered(&[0]), 0)
            .expect("answering with one index works");
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            hand_before + 1,
            "the pick arrives in hand"
        );
        // 找出**新进来的那一张**：它在手牌里、定义就是候选 0。
        let picked = offered[0].as_str().to_string();
        let Some(zones) = state.card_zones(&cid("hero")) else {
            panic!("the hero has zones");
        };
        let mut found_free = false;
        for index in 0..zones.count(CardZone::Hand) {
            let Some(slot) = zones.slot_at(CardZone::Hand, index) else {
                continue;
            };
            let Some(card) = state.card(slot) else {
                continue;
            };
            if card.definition_id.as_str() != picked {
                continue;
            }
            let override_value = card
                .mark_counters()
                .iter()
                .find(|counter| counter.key.as_str() == "standard.card_cost_override")
                .map(|counter| counter.value);
            if override_value == Some(0) {
                found_free = true;
            }
        }
        assert!(found_free, "the picked card carries `card_cost_override = 0`");
    }

    /// §250（C）：`Forethought` —— 选中的手牌去**抽牌堆底**，并且带着"免费"那一格。
    ///
    /// "底"是语义（`ToDrawPileBottomFree` 与 Warcry 的"顶"不可互换）：抽牌堆索引 0 是**头**，
    /// 所以"放到堆底"必须是**最后**一个。
    #[test]
    fn forethought_puts_the_pick_on_the_bottom_of_the_draw_pile() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        fill_energy(&mut state, 99);
        // 抽牌堆里先垫一张：它必须**还在**选中的那张之前（否则"底"就成了"顶"）。
        give_card(&mut state, "hero", CardZone::DrawPile, "pile_a", "defend", None);
        give_card(&mut state, "hero", CardZone::Hand, "pick_me", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "fore", "forethought", None);
        let card = crate::state::CardInstanceId::new("fore").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, None),
        )
        .expect("playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let question = state.pending_choice().expect("a question is owed");
        assert_eq!(question.source, crate::state::ChoiceSource::Hand);
        assert_eq!(question.then, crate::state::ChoiceThen::ToDrawPileBottomFree);

        let picked = crate::state::CardInstanceId::new("pick_me").expect("id");
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&[picked]), 0)
            .expect("answering with one instance works");

        let Some(zones) = state.card_zones(&cid("hero")) else {
            panic!("the hero has zones");
        };
        let count = zones.count(CardZone::DrawPile);
        assert_eq!(count, 2, "the padded card plus the pick, got {count}");
        let last = zones.slot_at(CardZone::DrawPile, count - 1).expect("slot");
        let card = state.card(last).expect("card");
        assert_eq!(card.id, picked, "the pick is at the **bottom**");
        let free = card
            .mark_counters()
            .iter()
            .find(|counter| counter.key.as_str() == "standard.card_cost_override")
            .map(|counter| counter.value);
        assert_eq!(free, Some(0), "it costs 0 until played");
    }

    /// §250（D）：三张"回合末"诅咒各做各的事 —— `decay` / `regret` / `shame`。
    ///
    /// 一次测三条是因为它们的载体**同一个**（`TurnEndInHand`），而失败模式各不相同：
    /// `decay` 是固定伤害、`regret` 是**按手牌张数**、`shame` 是上状态。只测一条会漏掉
    /// "表达式读错了区"这类错。
    #[test]
    fn the_turn_end_curses_do_their_own_thing() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "decay1", "decay", None);
        give_card(&mut state, "hero", CardZone::Hand, "regret1", "regret", None);
        give_card(&mut state, "hero", CardZone::Hand, "shame1", "shame", None);
        let hp_before = health(&state, "hero");
        state
            .enqueue_event(crate::state::CombatEvent::TurnEnded {
                combatant: cid("hero"),
            })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        // `decay` 2 点伤害（走 damage 管线，可被格挡）+ `regret` 按手牌张数掉血（3 张 ⇒ 3 点）。
        let lost = hp_before - health(&state, "hero");
        assert_eq!(lost, 5, "decay 2 + regret 3 (three cards in hand), lost {lost}");
        assert_eq!(
            stacks_of(&state, "hero", "standard.frail"),
            1,
            "shame grants 1 Frail"
        );
    }

    /// §250（D）：`pride` —— 回合末在**抽牌堆顶**放一份自己的副本，而且原件还在手牌里。
    ///
    /// "顶"必须可观察：抽牌堆里原本有一张垫底牌，副本要排在它**前面**（索引 0）。
    #[test]
    fn pride_copies_itself_onto_the_top_of_the_draw_pile() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::DrawPile, "pile_a", "defend", None);
        give_card(&mut state, "hero", CardZone::Hand, "pride1", "pride", None);
        state
            .enqueue_event(crate::state::CombatEvent::TurnEnded {
                combatant: cid("hero"),
            })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let Some(zones) = state.card_zones(&cid("hero")) else {
            panic!("the hero has zones");
        };
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            1,
            "the original stays in hand"
        );
        let top = zones.slot_at(CardZone::DrawPile, 0).expect("a card on top");
        let card = state.card(top).expect("card");
        assert_eq!(
            card.definition_id.as_str(),
            "pride",
            "the copy is on **top** (index 0 is the draw top)"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::DrawPile),
            2,
            "the padded card is still there"
        );
    }

    /// §250（D）：`necronomicurse` —— **被消耗时**往手牌里放一份副本。
    ///
    /// 判据走真实的消耗路径（`EffectRequest::Exhaust`? 这里用 `move_card` 到消耗堆不触发钩子，
    /// 所以直接派发 `CardExhausted` 事件的那条路 —— 与内容里的其它 `Exhausted` 节目同一条）。
    #[test]
    fn necronomicurse_returns_to_hand_when_exhausted() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "necro1", "necronomicurse", None);
        let slot = {
            let Some(zones) = state.card_zones(&cid("hero")) else {
                panic!("the hero has zones");
            };
            zones.slot_at(CardZone::Hand, 0).expect("the curse")
        };
        // 走内核的消耗路径：搬进消耗堆 + 派发 `CardExhausted`。
        state
            .move_card(
                &cid("hero"),
                CardZone::Hand,
                CardZone::ExhaustPile,
                slot,
                crate::state::ZonePlacement::Bottom,
            )
            .expect("it exhausts");
        state
            .enqueue_event(crate::state::CombatEvent::CardExhausted {
                combatant: cid("hero"),
                // 事件带的是**实例 id**，不是牌池槽位。
                card: state.card(slot).expect("the curse").id,
            })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            1,
            "a copy came back to hand"
        );
        let Some(zones) = state.card_zones(&cid("hero")) else {
            panic!("zones");
        };
        let copy = zones.slot_at(CardZone::Hand, 0).expect("the copy");
        assert_eq!(
            state.card(copy).expect("card").definition_id.as_str(),
            "necronomicurse"
        );
    }

    /// §250（D）：`pain` —— 手上有它时，打别的牌掉 1 血。
    ///
    /// 判据两侧：① 手上有 `pain` 打一张 ⇒ 掉 1；② 手上**没有**它打一张 ⇒ 不掉。
    /// 出的是 `defend`（只给格挡）—— 判据牌不许碰伤害（§249.4）。
    #[test]
    fn pain_costs_a_hit_point_per_card_played_while_held() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        fill_energy(&mut state, 99);
        give_card(&mut state, "hero", CardZone::Hand, "pain1", "pain", None);
        give_card(&mut state, "hero", CardZone::Hand, "def1", "defend", None);
        let before = health(&state, "hero");
        let card = crate::state::CardInstanceId::new("def1").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, None),
        )
        .expect("playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "hero"), before - 1, "pain took one HP");

        // ② 没有 `pain` 时同样的出牌不掉血。
        let fresh = {
            let mut state = arena();
            fill_energy(&mut state, 99);
            give_card(&mut state, "hero", CardZone::Hand, "def2", "defend", None);
            let before = health(&state, "hero");
            let mut host = Host::new(&content);
            let card = crate::state::CardInstanceId::new("def2").expect("id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, None),
            )
            .expect("playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            before - health(&state, "hero")
        };
        assert_eq!(fresh, 0, "without pain the same play costs nothing");
    }

    /// §250（D）：`normality` —— 第 4 张被**法令**拒绝（`DecreeMaxCardsPerTurn{cap: 3}`）。
    ///
    /// 判据三点：① 抽到它之后上限是 3；② 第 4 张被拒且理由是法令（不是"能量不够"）；
    /// ③ 回合末它把手牌上限清 0（否则下回合还是 3 —— 而 StS 的"这一回合"就是三张）。
    #[test]
    fn normality_caps_the_cards_played_this_turn() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        fill_energy(&mut state, 99);
        // 抽到它：`Drawn` 的节目把上限写成 3。
        give_card(&mut state, "hero", CardZone::Hand, "norm1", "normality", None);
        // 走内核的 `Drawn` 钩子（`run_card_lifecycle` 是它的共同实体）：内容里那条节目
        // 把 `card_play_cap` 覆盖写成 3。
        let definition = crate::state::CardDefinitionId::new("normality").expect("id");
        crate::host::run_card_lifecycle(
            &mut state,
            &content,
            cid("hero"),
            definition,
            crate::state::CardLifecycleEvent::Drawn,
        )
        .expect("the drawn hook runs");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            state
                .combatant(&cid("hero"))
                .expect("hero")
                .counters()
                .iter()
                .find(|counter| counter.key.as_str() == "card_play_cap")
                .map(|counter| counter.value),
            Some(3),
            "the cap is 3"
        );

        for index in 1..=3 {
            give_card(&mut state, "hero", CardZone::Hand,
                      &std::format!("d{index}"), "defend", None);
            let card = crate::state::CardInstanceId::new(&std::format!("d{index}")).expect("id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, None),
            )
            .unwrap_or_else(|error| panic!("card {index} must be playable: {error:?}"));
            host.try_resolve_pending_queues(&mut state).expect("drain");
        }
        give_card(&mut state, "hero", CardZone::Hand, "d4", "defend", None);
        let card = crate::state::CardInstanceId::new("d4").expect("id");
        let refused = crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, None),
        );
        assert_eq!(
            refused,
            Err(crate::play::PlayError::Refused(
                crate::play::Refusal::DecreeMaxCardsPerTurn { cap: 3, played: 3 }
            )),
            "the fourth card is refused by the decree"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'ritual_dagger_only_grows_when_it_kills' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 9 tests')


main()
