"""§222 B: give the §221 content named tests (it only had the generic layers).

The coverage matrix said "harness only" for these: the content gate pins numbers, and the diff
harnesses play cards -- but nothing asserted *this card's* observable behaviour. One table-driven test
beats ten copy-pasted ones: each row says which card, what to read, and what it must read.
"""
import io

H = 'kernel/rd-core/src/host.rs'
R = 'kernel/rd-run/src/state.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


# ── ① rd-core：一张表，十张牌 + 两张诅咒 ──────────────────────────────────────────────────────
one(H, '''    /// §220：`LifecyclePrograms[Drawn]`''',
    '''    /// §222：§221 加的十张牌 —— 一张表，每行说"打哪张、读哪一格、应当是多少"。
    ///
    /// 这一批之前只有通用层覆盖：内容门钉数字（`INV_CARDS`）、`CARD_DIFF` 跑程序文本，
    /// **没有任何东西断言"这张牌打出来真的做了那件事"**。矩阵把它们标成 `harness`，这里把它们
    /// 抬成具名测试。
    ///
    /// 判据口径：读**一个**可观察量（敌人血量 / 英雄格挡 / 手牌数 / 抽牌堆 / 弃牌堆 / 敌人状态），
    /// 而不是"整份状态"，因为这些牌各自只动一格 —— 读整份会让"读错格子"也看起来正确。
    #[test]
    fn the_ten_cards_added_in_221_do_what_the_wiki_says() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // (card, 打出去之后的断言) —— 每一行都在 `arena()`（敌人 20 血、英雄 70）上跑。
        for card_id in [
            "cleave",
            "pommel_strike",
            "shrug_it_off",
            "thunderclap",
            "bludgeon",
            "impervious",
            "pummel",
            "wild_strike",
            "ghostly_armor",
            "battle_trance",
        ] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .unwrap_or_else(|error| panic!("{card_id}: {error:?}"));
            host.try_resolve_pending_queues(&mut state).expect("drain");

            match card_id {
                // 单体伤害
                "pommel_strike" => {
                    assert_eq!(health(&state, "enemy_a"), 11, "9 damage");
                    assert_eq!(zone_count(&state, "hero", CardZone::Hand), 1, "draw 1");
                }
                "bludgeon" => assert_eq!(health(&state, "enemy_a"), -12, "32 damage (20 HP)"),
                // 全体伤害：两个敌人都要掉血（这是 `sel.allEnemies` 的唯一可观察差别）
                "cleave" => {
                    assert_eq!(health(&state, "enemy_a"), 12, "8 to enemy_a");
                    assert_eq!(health(&state, "enemy_b"), 2, "8 to enemy_b");
                }
                "thunderclap" => {
                    assert_eq!(health(&state, "enemy_a"), 16, "4 to enemy_a");
                    assert_eq!(health(&state, "enemy_b"), 6, "4 to enemy_b");
                    assert_eq!(
                        stacks_of(&state, "enemy_a", "standard.vulnerable"),
                        1,
                        "and 1 Vulnerable on each"
                    );
                    assert_eq!(stacks_of(&state, "enemy_b", "standard.vulnerable"), 1);
                }
                // 多段：`repeat` 的每一段都过伤害管线（4×2 = 8）
                "pummel" => {
                    assert_eq!(health(&state, "enemy_a"), 12, "2 damage, 4 times");
                    assert_eq!(
                        zone_definitions(&state, "hero", CardZone::ExhaustPile),
                        vec!["pummel".to_string()],
                        "and it exhausts"
                    );
                }
                // 格挡 + 消耗
                "impervious" => {
                    assert_eq!(block_of(&state, "hero"), 30, "30 Block");
                    assert_eq!(
                        zone_definitions(&state, "hero", CardZone::ExhaustPile),
                        vec!["impervious".to_string()],
                        "and it exhausts"
                    );
                }
                "shrug_it_off" => {
                    assert_eq!(block_of(&state, "hero"), 8, "8 Block");
                    assert_eq!(zone_count(&state, "hero", CardZone::Hand), 1, "draw 1");
                }
                "ghostly_armor" => {
                    assert_eq!(block_of(&state, "hero"), 10, "10 Block");
                    assert_eq!(
                        zone_count(&state, "hero", CardZone::Hand),
                        1,
                        "Ethereal stays in hand until the turn ends"
                    );
                }
                // Wound 进**抽牌堆**（不是弃牌堆 —— 那是 Wild Strike 与其它塞牌的区别）
                "wild_strike" => {
                    assert_eq!(health(&state, "enemy_a"), 8, "12 damage");
                    assert_eq!(
                        zone_definitions(&state, "hero", CardZone::DrawPile),
                        vec!["wound".to_string()],
                        "a Wound goes into the DRAW pile"
                    );
                }
                // 抽 3 张 + "本回合不能再抽"
                "battle_trance" => {
                    assert_eq!(
                        zone_count(&state, "hero", CardZone::Hand),
                        3,
                        "draw 3 (the card itself left the hand)"
                    );
                    assert_eq!(
                        stacks_of(&state, "hero", "standard.draw_reduction"),
                        1,
                        "and the rest of the turn cannot draw"
                    );
                }
                other => panic!("{other} has no assertion in this table"),
            }
        }
    }

    /// §222：两张事件诅咒 —— `doubt` 的"回合末 +1 Weak"是 `LifecyclePrograms[TurnEndInHand]`，
    /// `writhe` 只是 `Innate` + `Unplayable`（没有节目 ⇒ 回合末什么都不发生）。
    #[test]
    fn the_two_event_curses_behave_as_their_pages_say() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // `doubt`：手里过回合 ⇒ 1 层 Weak。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_doubt", "doubt", None);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(
            stacks_of(&state, "hero", "standard.weak"),
            1,
            "wiki: at the end of your turn, gain 1 Weak"
        );

        // `writhe`：没有节目 ⇒ Weak 仍然是 0（成对，否则上面那条可能来自别处）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_writhe", "writhe", None);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(
            stacks_of(&state, "hero", "standard.weak"),
            0,
            "writhe has no lifecycle program"
        );
    }

    /// §220：`LifecyclePrograms[Drawn]`''',
    'rd-core tests')

# ── ② rd-run：两件新遗物的开战加成 ────────────────────────────────────────────────────────────
one(R, '''    /// §221：**内容里的卡行数不许超过池子上限**''',
    '''    /// §222：§221 的两件遗物 —— 开战各给 1 层状态（`StartCombatStatus`）。
    ///
    /// 判据读 `combat_bonus`：它是 run 层交给"建战斗"的那一份加成。**成对**：没带遗物时是空的，
    /// 否则"给了"与"本来就有"分不开。
    #[test]
    fn the_two_new_relics_grant_their_status_at_combat_start() {
        for (relic, status) in [("bag_of_marbles", "standard.vulnerable"),
                                ("oddly_smooth_stone", "standard.dexterity")] {
            let mut run = RunState::new(3, 80, 0, &DECK).expect("a run");
            assert!(
                run.combat_bonus().statuses().is_empty(),
                "{relic}: nothing before the relic is held"
            );
            run.push_relic(relic).expect("the relic enters the belt");
            let bonus = run.combat_bonus();
            let found: Vec<&str> = bonus.statuses().iter().map(|s| s.id).collect();
            assert_eq!(found, vec![status], "{relic}: one status at combat start");
            assert_eq!(bonus.statuses()[0].stacks, 1, "{relic}: exactly one stack");
        }
    }

    /// §221：**内容里的卡行数不许超过池子上限**''',
    'rd-run relic test')
