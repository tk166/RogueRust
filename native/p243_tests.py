"""§243 判据：无色 A 档 11 张。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §242：`Spot Weakness` —— "If the enemy intends to attack, gain 3 Strength."'

TESTS = r'''    /// §243：无色 A 档的**数字** —— 11 张一张不漏，每张都钉两个数字（基础/升级）。
    ///
    /// 为什么挤在一个测试里：它们的判据形状完全相同（"打出去 → 手牌/格挡/状态变多少"），
    /// 拆成 11 个只会让"哪张忘了测"更难看出来。**升级行与基础行都要测** —— 只测基础的话，
    /// 抄错升级数字（本批最容易错的一格）全绿。
    #[test]
    fn the_zero_cost_utility_batch_matches_its_pages() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 打一张牌，返回 (手牌数, 格挡, 能量, 状态层数之和)。
        let play = |card_id: &str| -> (usize, i32, i32, i32) {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            if let Some(combatant) = state.combatant_mut(&cid("enemy_a")) {
                combatant.health_max = 200;
                combatant.health_current = 200;
            }
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("the card is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            let statuses = ["standard.vulnerable", "standard.artifact"]
                .iter()
                .map(|id| {
                    stacks_of(&state, "hero", id)
                        + stacks_of(&state, "enemy_a", id)
                        + stacks_of(&state, "enemy_b", id)
                })
                .sum();
            (
                zone_count(&state, "hero", CardZone::Hand),
                block_of(&state, "hero"),
                energy_of(&state, "hero"),
                statuses,
            )
        };

        // `trip`：基础只打一个目标，升级打**全体**（"升级改目标"的唯一一张）。
        assert_eq!(play("trip").3, 2, "trip: 2 Vulnerable");
        assert_eq!(
            vulnerable_of(&content, "trip"),
            [2, 0],
            "trip hits only the chosen enemy"
        );
        assert_eq!(
            vulnerable_of(&content, "trip+"),
            [2, 2],
            "trip+ hits ALL enemies"
        );

        // 格挡类。
        assert_eq!(play("finesse"), (1, 2, 3, 0), "finesse: 2 Block + 1 card");
        assert_eq!(play("finesse+"), (1, 4, 3, 0), "finesse+: 4 Block + 1 card");
        assert_eq!(play("good_instincts").1, 6, "good instincts: 6 Block");
        assert_eq!(play("good_instincts+").1, 9, "good instincts+: 9 Block");

        // 抽牌类：`master_of_strategy` 3/4（自消耗，所以它不在手牌里）+ `insight` 2/3（retain）。
        assert_eq!(play("master_of_strategy").0, 3, "master of strategy: draw 3");
        assert_eq!(play("master_of_strategy+").0, 4, "master of strategy+: draw 4");
        assert_eq!(play("insight").0, 2, "insight: draw 2");
        assert_eq!(play("insight+").0, 3, "insight+: draw 3");

        // 能量类：0 费 ⇒ 净值就是加的那些。
        assert_eq!(play("miracle").2, 3 + 1, "miracle: +1 Energy");
        assert_eq!(play("miracle+").2, 3 + 2, "miracle+: +2 Energy");

        // `panacea`：Artifact 1/2。
        assert_eq!(play("panacea").3, 1, "panacea: 1 Artifact");
        assert_eq!(play("panacea+").3, 2, "panacea+: 2 Artifact");

        // `flash_of_steel`：打出 1 张、抽 1 张 ⇒ 手牌数不变。
        assert_eq!(play("flash_of_steel").0, 1, "flash of steel: draw 1");

        // `dramatic_entrance`：8/12 打**全体** + 自消耗。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        for enemy in ["enemy_a", "enemy_b"] {
            if let Some(combatant) = state.combatant_mut(&cid(enemy)) {
                combatant.health_max = 200;
                combatant.health_current = 200;
            }
        }
        let card = card_in_hand(&mut state, &content, "hero", "dramatic_entrance+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("dramatic entrance is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 188, "dramatic entrance+: 12 to enemy_a");
        assert_eq!(health(&state, "enemy_b"), 188, "dramatic entrance+: 12 to enemy_b");
        assert!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile)
                .iter()
                .any(|id| id == "dramatic_entrance+"),
            "and it exhausts itself"
        );
    }

    /// §243：`Impatience` —— **手上没有攻击牌**才抽（`hand.hasCardWithTag`）。
    ///
    /// 两侧 + 一个对照：只测"没有攻击时抽"会漏掉"条件被写成恒真"，
    /// 只测"有攻击时不抽"会漏掉"条件被写成恒假"。
    #[test]
    fn impatience_only_draws_when_the_hand_has_no_attack() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 返回"抽了几张"：手牌 -1（打出自己）+ 抽到的张数。
        let drawn = |hand: &[&str]| -> i32 {
            let mut host = Host::new(&content);
            let mut state = arena();
            for (index, definition) in hand.iter().enumerate() {
                give_card(&mut state, "hero", CardZone::Hand,
                          &std::format!("card_h{index}"), definition, None);
            }
            for index in 0..4 {
                give_card(&mut state, "hero", CardZone::DrawPile,
                          &std::format!("card_d{index}"), "defend", None);
            }
            let card = card_in_hand(&mut state, &content, "hero", "impatience");
            let before = zone_count(&state, "hero", CardZone::Hand) as i32;
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("impatience is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            let after = zone_count(&state, "hero", CardZone::Hand) as i32;
            after + 1 - before
        };

        assert_eq!(drawn(&["defend", "defend"]), 2, "no Attack in hand ⇒ draw 2");
        assert_eq!(drawn(&["defend", "strike"]), 0, "an Attack in hand ⇒ draw nothing");
    }

    /// §243：`Deep Breath` —— **先把弃牌堆洗回抽牌堆，再抽**（顺序是语义）。
    ///
    /// 两段：① 抽牌堆空时抽到"刚洗回去的那张"；② 抽牌堆**不空**时弃牌堆也必须被洗回去 ——
    /// 没有 ②，一个"只靠抽空自动重洗"的实现也会全绿。
    #[test]
    fn deep_breath_shuffles_the_discard_pile_back_first() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 抽牌堆空 ⇒ 洗弃牌堆再抽 1（抽到 `bash`）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::DiscardPile, "card_x", "bash", None);
        let card = card_in_hand(&mut state, &content, "hero", "deep_breath");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("deep breath is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert!(
            zone_definitions(&state, "hero", CardZone::Hand)
                .iter()
                .any(|id| id == "bash"),
            "the shuffled-back card is the one drawn"
        );
        assert!(
            zone_definitions(&state, "hero", CardZone::DiscardPile)
                .iter()
                .any(|id| id == "deep_breath"),
            "deep breath itself lands in the discard pile (it does not exhaust)"
        );

        // ② 抽牌堆不空 ⇒ 弃牌堆仍然要被洗回去。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::DrawPile, "card_d", "defend", None);
        give_card(&mut state, "hero", CardZone::DiscardPile, "card_x", "bash", None);
        let card = card_in_hand(&mut state, &content, "hero", "deep_breath");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("deep breath is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert!(
            !zone_definitions(&state, "hero", CardZone::DiscardPile)
                .iter()
                .any(|id| id == "bash"),
            "the discard pile was shuffled in even though the draw pile was not empty"
        );
    }

    /// §243 辅助：打一张牌，返回 `[enemy_a, enemy_b]` 身上的 Vulnerable（`trip` 的目标判据用）。
    fn vulnerable_of(content: &Content<'_>, card_id: &str) -> [i32; 2] {
        let mut host = Host::new(content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", card_id);
        crate::play::play_card(
            &mut state,
            Some(content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("the card is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        [
            stacks_of(&state, "enemy_a", "standard.vulnerable"),
            stacks_of(&state, "enemy_b", "standard.vulnerable"),
        ]
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'the_zero_cost_utility_batch' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 3 tests')


main()
