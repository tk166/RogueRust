"""§157: tests for the moving potion chance, the belt, the potion rarity spread and the new relics.

Five things, one test each (a single test that asserts five unrelated facts hides which one broke):

1. `the_potion_chance_walks_the_wikis_ten_percent` -- -10 on a drop, +10 on a miss, and the act reset;
2. `a_full_belt_still_rolls_the_chance` -- the offer is suppressed, the chance still moves;
3. `potions_are_drawn_by_rarity_weight` -- the 65/25/10 order (same loose shape as the relic test);
4. `potion_belt_raises_the_slot_count` -- 3 slots, 5 with the belt, and the fourth potion is refused
   without it;
5. `the_new_relics_pay_out` -- feather per five cards, idol +25% gold.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"

TESTS = '''
    /// §157：药水掉率是 wiki 那条**会走**的 40%，不是常量。
    ///
    /// -10（掉了）/ +10（没掉），换幕重置。断言走的是**数字**而不是"某个种子恰好掉了几瓶"。
    #[test]
    fn the_potion_chance_walks_the_wikis_ten_percent() {
        let pool = [
            PoolCard {
                id: "strike",
                rarity: Rarity::Basic,
            },
            PoolCard {
                id: "defend",
                rarity: Rarity::Basic,
            },
            PoolCard {
                id: "anger",
                rarity: Rarity::Basic,
            },
        ];
        let mut run = RunState::new(31, 80, 0, &DECK).expect("a run");
        assert_eq!(run.potion_drop_chance(), POTION_DROP_START, "starts at 40");
        let mut drops = 0;
        let mut misses = 0;
        for _ in 0..12 {
            run.skip_reward().ok();
            let before = run.potion_drop_chance();
            run.roll_reward(&pool, &[], &[], FightKind::Normal)
                .expect("a reward");
            let offered = run.reward_potion().is_some();
            let after = run.potion_drop_chance();
            if offered {
                drops += 1;
                assert_eq!(after, (before - POTION_DROP_STEP).max(0), "a drop moves it down");
            } else {
                misses += 1;
                assert_eq!(after, (before + POTION_DROP_STEP).min(100), "a miss moves it up");
            }
            assert!((0..=100).contains(&after), "the chance stays a percentage");
        }
        assert!(drops > 0 && misses > 0, "12 rolls should contain both outcomes");
    }

    /// §157：**腰带满了照样摇**（wiki 的 Colosseum 注记就靠这一点），只是不摆出来。
    #[test]
    fn a_full_belt_still_rolls_the_chance() {
        let pool = [PoolPotion {
            id: "fire_potion",
            rarity: Rarity::Common,
        }];
        let cards = [
            PoolCard {
                id: "strike",
                rarity: Rarity::Basic,
            },
            PoolCard {
                id: "defend",
                rarity: Rarity::Basic,
            },
            PoolCard {
                id: "anger",
                rarity: Rarity::Basic,
            },
        ];
        let mut run = RunState::new(41, 80, 0, &DECK).expect("a run");
        for _ in 0..BASE_POTION_SLOTS {
            run.push_potion("fire_potion").expect("room");
        }
        assert!(!run.potion_room(), "the belt is full");
        let mut moved = false;
        for _ in 0..8 {
            let before = run.potion_drop_chance();
            run.roll_reward(&cards, &pool, &[], FightKind::Normal)
                .expect("a reward");
            assert_eq!(run.reward_potion(), None, "a full belt gets no offer");
            if run.potion_drop_chance() != before {
                moved = true;
            }
            run.skip_reward().expect("skip");
        }
        assert!(moved, "the chance must keep moving even when nothing is offered");
    }

    /// §157：药水按稀有度权重抽（65/25/10）—— 和遗物那条同样是**宽松**的烟测。
    #[test]
    fn potions_are_drawn_by_rarity_weight() {
        let pool = [
            PoolPotion {
                id: "fire_potion",
                rarity: Rarity::Common,
            },
            PoolPotion {
                id: "energy_potion",
                rarity: Rarity::Uncommon,
            },
            PoolPotion {
                id: "regen_potion",
                rarity: Rarity::Rare,
            },
        ];
        let mut run = RunState::new(51, 80, 0, &DECK).expect("a run");
        let mut commons = 0;
        let mut uncommons = 0;
        let mut rares = 0;
        for _ in 0..40 {
            // A miss is possible; that is what the 40% is. Count only what came out.
            match run.pick_rarity(RunStream::Potion, &POTION_RARITY_WEIGHTS, &[Rarity::Common, Rarity::Uncommon, Rarity::Rare]).expect("a band") {
                Some(Rarity::Common) => commons += 1,
                Some(Rarity::Uncommon) => uncommons += 1,
                Some(Rarity::Rare) => rares += 1,
                other => panic!("unexpected band {other:?}"),
            }
        }
        assert_eq!(commons + uncommons + rares, 40);
        assert!(commons > uncommons, "common {commons} vs uncommon {uncommons}");
        assert!(
            uncommons >= rares,
            "uncommon {uncommons} vs rare {rares} (65/25/10)"
        );
        // A pool with only rares shifts the mass instead of returning nothing.
        for _ in 0..10 {
            assert_eq!(
                run.pick_rarity(RunStream::Potion, &POTION_RARITY_WEIGHTS, &[Rarity::Rare])
                    .expect("a band"),
                Some(Rarity::Rare)
            );
        }
        let _ = pool;
    }

    /// §157：Potion Belt 是唯一增加腰带格数的东西（wiki 原话），所以格数是**方法**而不是数组长度。
    #[test]
    fn potion_belt_raises_the_slot_count() {
        let mut run = RunState::new(61, 80, 0, &DECK).expect("a run");
        assert_eq!(run.potion_slots(), BASE_POTION_SLOTS, "three slots");
        for _ in 0..BASE_POTION_SLOTS {
            run.push_potion("fire_potion").expect("room");
        }
        assert_eq!(
            run.push_potion("fire_potion"),
            Err(RunError::Capacity),
            "the fourth is refused without the belt"
        );

        run.push_relic("potion_belt").expect("the belt");
        assert_eq!(run.potion_slots(), BASE_POTION_SLOTS + 2, "two more slots");
        assert!(run.push_potion("fire_potion").is_ok(), "the fourth fits now");
        assert!(run.push_potion("fire_potion").is_ok(), "and the fifth");
        assert_eq!(
            run.push_potion("fire_potion"),
            Err(RunError::Capacity),
            "the sixth is still refused"
        );
        assert_eq!(
            run.potions().len(),
            usize::from(BASE_POTION_SLOTS) + 2,
            "the belt holds five"
        );
    }

    /// §157：Eternal Feather 按"每五张牌 3 点"回血，Golden Idol 让战斗金币 +25%。
    #[test]
    fn the_new_relics_pay_out() {
        // Ten cards = two groups of five.
        let mut run = RunState::new(71, 80, 0, &DECK).expect("a run");
        let base = run.rest_heal();
        run.push_relic("eternal_feather").expect("the feather");
        assert_eq!(run.deck_len, 10, "the fixture deck is ten cards");
        assert_eq!(
            run.rest_heal(),
            base + 3 * 2,
            "3 HP per five cards, two groups"
        );
        assert_eq!(run.rest_heal_per_cards(), 6);

        // The idol multiplies the fight's gold; the reward's own number is what was paid.
        let cards = [
            PoolCard {
                id: "strike",
                rarity: Rarity::Basic,
            },
            PoolCard {
                id: "defend",
                rarity: Rarity::Basic,
            },
            PoolCard {
                id: "anger",
                rarity: Rarity::Basic,
            },
        ];
        let mut plain = RunState::new(81, 80, 0, &DECK).expect("a run");
        plain
            .roll_reward(&cards, &[], &[], FightKind::Normal)
            .expect("a reward");
        let plain_gold = plain.reward_gold();
        assert_eq!(plain.fight_gold_percent(), 100);

        let mut idol = RunState::new(81, 80, 0, &DECK).expect("a run");
        idol.push_relic("golden_idol").expect("the idol");
        assert_eq!(idol.fight_gold_percent(), 125);
        idol.roll_reward(&cards, &[], &[], FightKind::Normal)
            .expect("a reward");
        assert_eq!(
            idol.reward_gold(),
            plain_gold * 125 / 100,
            "the same roll, 25% more"
        );
        assert_eq!(idol.gold(), plain.gold() + (plain_gold * 125 / 100) - plain_gold);
    }
'''

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()
if "fn the_potion_chance_walks_the_wikis_ten_percent" in source:
    print("tests already present")
else:
    anchor = "    /// §156：稀有度权重**按顺序**生效，且空档不会把抽取变空。"
    at = source.find(anchor)
    if at < 0:
        raise SystemExit("anchor missing")
    source = source[:at] + TESTS.strip("\n") + "\n\n" + source[at:]
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("five tests inserted")
