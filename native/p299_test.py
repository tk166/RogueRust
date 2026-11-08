"""§299 判据：enchiridion / dead_branch / orange_pellets（三件纯内容程序）。"""
import io

HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'

TESTS = r'''
    /// §299：`enchiridion` —— 开战第一回合把一张 **Power** 牌加进手牌，且它这次免费。
    ///
    /// 两侧：① 带状态 ⇒ 手牌多一张 Power 牌、它带着 `card_cost_override = 0`；
    /// ② 不带 ⇒ 手牌就是正常那几张（这是"程序没跑"与"程序跑了"的分界）。
    #[test]
    fn enchiridion_adds_a_free_power_card_on_the_first_turn() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);

        let draw = |host: &mut Host, with_relic: bool| -> (Vec<String>, usize) {
            let mut state = arena();
            if with_relic {
                give(&mut state, "hero", status("st_en", "standard.enchiridion", 1));
            }
            host.try_run_turn_started_triggers(&mut state, &cid("hero"))
                .expect("the turn starts");
            host.try_resolve_pending_queues(&mut state).expect("triggers");
            let hand = state
                .card_zones(&cid("hero"))
                .expect("zones")
                .slots(crate::state::CardZone::Hand)
                .to_vec();
            let mut definitions = Vec::new();
            let mut free = 0usize;
            for slot in hand {
                let Some(card) = state.card(crate::state::CardSlot::from_index(slot)) else {
                    continue;
                };
                definitions.push(std::string::String::from(card.definition_id.as_str()));
                if card.mark_counters().iter().any(|counter| {
                    counter.key.as_str() == "standard.card_cost_override" && counter.value == 0
                }) {
                    free += 1;
                }
            }
            (definitions, free)
        };

        let (plain, plain_free) = draw(&mut host, false);
        assert_eq!(plain_free, 0, "without the relic nothing is free");
        let (with_relic, free) = draw(&mut host, true);
        assert_eq!(
            with_relic.len(),
            plain.len() + 1,
            "exactly one card is added: {plain:?} -> {with_relic:?}"
        );
        assert_eq!(free, 1, "and exactly one card is free");
        let added: Vec<&String> = with_relic
            .iter()
            .filter(|definition| !plain.contains(definition))
            .collect();
        assert_eq!(added.len(), 1, "one new definition: {with_relic:?}");
        assert_eq!(
            content.card_has_tag(added[0], "power"),
            Some(true),
            "the added card is a Power card, got `{}`",
            added[0]
        );
    }

    /// §299：`dead_branch` —— 每**消耗**一张牌，往手牌加一张随机牌。
    ///
    /// ① 带状态时手牌 +1；② 不带时不动；③ 新牌是**基础牌**（不是 `+` 行、不是 X 费牌 ——
    /// 那两条是随机池的规矩，通配 tag `*` **不**越过它们）。
    #[test]
    fn dead_branch_adds_a_random_base_card_when_a_card_is_exhausted() {
        use crate::state::{CardZone, EffectRequest};

        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);

        let run = |host: &mut Host, with_relic: bool| -> Vec<String> {
            let mut state = arena();
            if with_relic {
                give(&mut state, "hero", status("st_db", "standard.dead_branch", 1));
            }
            // 手牌里放一张，然后把它移进消耗堆（三条入堆路径都会发 `CardExhausted`）。
            let card = card_in_hand(&mut state, &content, "hero", "strike");
            state
                .enqueue_effect_with_owner(
                    EffectRequest::MoveCardToZone {
                        owner: cid("hero"),
                        card,
                        to_zone: CardZone::ExhaustPile,
                        placement: crate::state::ZonePlacement::Bottom,
                    },
                    None,
                )
                .unwrap();
            host.try_resolve_pending_queues(&mut state).expect("triggers");
            let mut hand: Vec<String> = state
                .card_zones(&cid("hero"))
                .expect("zones")
                .slots(CardZone::Hand)
                .iter()
                .filter_map(|slot| state.card(crate::state::CardSlot::from_index(*slot)))
                .map(|card| std::string::String::from(card.definition_id.as_str()))
                .collect();
            hand.sort();
            hand
        };

        assert!(
            run(&mut host, false).is_empty(),
            "without the relic the hand is empty again"
        );
        let with_relic = run(&mut host, true);
        assert_eq!(with_relic.len(), 1, "dead_branch adds exactly one card");
        let added = &with_relic[0];
        assert!(!added.contains('+'), "the pool only holds base rows, got `{added}`");
        assert_eq!(
            content.card_has_tag(added, "x_cost"),
            Some(false),
            "and never an X-cost card, got `{added}`"
        );
    }

    /// §299：`orange_pellets` —— 一回合里 Power / Attack / Skill 各打一张 ⇒ +3 力量、+3 敏捷。
    ///
    /// 三侧：① 只有两类 ⇒ 不付；② 三类齐 ⇒ +3/+3；③ 第四张牌**不重复付**（计数器已清零）。
    #[test]
    fn orange_pellets_pays_once_all_three_card_kinds_were_played() {
        use crate::state::ResourceId;

        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);

        let stacks = |state: &crate::state::CombatState, definition: &str| -> i32 {
            state
                .combatant(&cid("hero"))
                .map(|hero| {
                    hero.statuses()
                        .iter()
                        .filter(|status| status.definition_id.as_str() == definition)
                        .map(|status| status.stacks)
                        .sum()
                })
                .unwrap_or(0)
        };
        let play_all = |host: &mut Host, cards: &[&str]| -> (i32, i32) {
            let mut state = arena();
            {
                let foe = state.combatant_mut(&cid("enemy_a")).expect("foe");
                foe.health_max = 400;
                foe.health_current = 400;
            }
            state
                .combatant_mut(&cid("hero"))
                .expect("hero")
                .set_resource(ResourceId::new("standard.energy").unwrap(), 20, Some(20))
                .expect("energy");
            give(&mut state, "hero", status("st_op", "standard.orange_pellets", 1));
            for id in cards {
                let card = card_in_hand(&mut state, &content, "hero", id);
                let request =
                    crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a")));
                crate::play::play_card(&mut state, Some(&content), &request)
                    .unwrap_or_else(|e| panic!("{id}: {e:?}"));
                host.try_resolve_pending_queues(&mut state).expect("triggers");
            }
            (
                stacks(&state, "standard.strength"),
                stacks(&state, "standard.dexterity"),
            )
        };

        // ① 只有 Attack + Skill。
        assert_eq!(
            play_all(&mut host, &["strike", "defend"]),
            (0, 0),
            "two kinds is not enough"
        );
        // ② 三类齐（`metallicize` 是纯 Power，自己不加力量，判据读起来干净）。
        assert_eq!(
            play_all(&mut host, &["strike", "defend", "metallicize"]),
            (3, 3),
            "Power + Attack + Skill pays 3 Strength and 3 Dexterity"
        );
        // ③ 第四张不重复付。
        assert_eq!(
            play_all(&mut host, &["strike", "defend", "metallicize", "strike"]),
            (3, 3),
            "the counters reset, so a fourth card does not pay again"
        );
    }
'''


def main():
    s = io.open(HOST, encoding='utf-8').read()
    assert s.rstrip('\n').endswith('}')
    cut = s.rstrip('\n').rfind('\n}')
    s = s[:cut] + TESTS + s[cut:]
    io.open(HOST, 'w', encoding='utf-8', newline='\n').write(s)
    print('tests appended')


main()
