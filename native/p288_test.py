"""§288 判据：① `After` 打完回到事件；② 定数奖励；③ 楼层门槛（两侧）；④ 稀有度码。"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'

STATE_TESTS = r'''    /// §288：`After` —— 战斗打完之后**回到事件**，而且房间**还没**结算
    /// （`The Colosseum` 的第一场：wiki 说它 "gives no rewards"，奖励是事件继续）。
    #[test]
    fn a_fight_can_return_to_the_event() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        assert!(walk_to(&mut run, NodeKind::Unknown), "a `?` node must exist");
        run.begin_node(&pool, &[]).expect("the node opens");
        run.begin_event("the_colosseum", "the_colosseum").expect("the event");

        run.resolve_event_effects(
            &EventMove {
                fight: 1,
                fight_pool: "ColosseumSlavers",
                fight_after: "the_colosseum.after",
                ..EventMove::none()
            },
            &pool,
        )
        .expect("the first fight starts");

        assert_eq!(run.event_fight(), 1, "the band is recorded");
        assert_eq!(
            run.event(),
            "the_colosseum",
            "the event is **not** over: the fight comes back to it"
        );
        assert_eq!(run.event_step(), "", "no step is open while the fight runs");
        assert!(!run.node_resolved(), "the node still owes the rest of the event");
        assert_eq!(run.event_fight_pool(), "ColosseumSlavers");

        // 战斗结束（由 wasm 在**胜利**分支调用）⇒ 事件回到 `After` 那一段。
        assert!(run.resume_event_after_fight(), "there is a step to return to");
        assert_eq!(run.event_step(), "the_colosseum.after", "we are back in the event");
        assert_eq!(run.pending(), Pending::Event, "the event wants a choice again");
        assert_eq!(run.event_fight(), 0, "the fight is over");
        assert_eq!(run.event_fight_pool(), "", "and its pool with it");
        // 再问一次：没有第二次"回去"（否则一场战斗能被回两次）。
        assert!(!run.resume_event_after_fight(), "the resume is a one-shot");
    }

    /// §288：**定数奖励**（`The Colosseum` 的 `100 Gold, 1 Rare Relic, 1 Uncommon Relic`）。
    #[test]
    fn the_fight_reward_overrides_are_exact() {
        let cards = curse_pool();
        let relics = [
            PoolRelic { id: "anchor", rarity: Rarity::Common },
            PoolRelic { id: "vajra", rarity: Rarity::Common },
            PoolRelic { id: "meat_on_the_bone", rarity: Rarity::Uncommon },
            PoolRelic { id: "ice_cream", rarity: Rarity::Rare },
        ];
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("the_colosseum", "the_colosseum.after").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[
                    (EventEffect::FightGoldSet(100), None),
                    (EventEffect::FightRelicRarity(Rarity::Rare), None),
                    (EventEffect::FightExtraRelic(Rarity::Uncommon), None),
                ],
                fight: 2,
                fight_pool: "ColosseumChampions",
                ..EventMove::none()
            },
            &cards,
        )
        .expect("the victory fight starts");

        run.roll_reward(&cards, &[], &relics, FightKind::Elite)
            .expect("the rewards land");
        assert_eq!(run.reward_gold(), 100, "`fight_gold_set` **replaces** the band");
        assert_eq!(
            run.reward_relic(),
            Some("ice_cream"),
            "the reward relic is locked to Rare (only one is in the pool)"
        );
        assert!(
            run.relics().iter().any(|held| held.as_str() == "meat_on_the_bone"),
            "the extra Uncommon relic went straight into the belt: {:?}",
            run.relics().iter().map(|held| held.as_str()).collect::<std::vec::Vec<_>>()
        );

        // 只付一次：第二场是普通结算。
        run.roll_reward(&cards, &[], &relics, FightKind::Elite)
            .expect("the second payout");
        let (low, high) = reward_bands(FightKind::Elite, run.rarity_offset());
        assert!(
            run.reward_gold() >= low && run.reward_gold() <= high,
            "no override left: {} must be inside {low}..={high}",
            run.reward_gold()
        );
    }

    /// §288：稀有度的**码**——每个变体码不同，而且 `code`/`of_code` 互为逆。
    #[test]
    fn every_rarity_has_a_distinct_code() {
        let all = [
            Rarity::Basic,
            Rarity::Common,
            Rarity::Uncommon,
            Rarity::Rare,
            Rarity::Status,
            Rarity::Curse,
            Rarity::Special,
            Rarity::Event,
            Rarity::Starter,
            Rarity::Boss,
        ];
        let mut seen: std::vec::Vec<u8> = std::vec::Vec::new();
        for rarity in all {
            let code = rarity_code(rarity);
            assert_ne!(code, 0, "0 means `unset`, so no rarity may own it");
            assert!(!seen.contains(&code), "two rarities share code {code}");
            assert_eq!(rarity_of_code(code), rarity, "code round trip for {rarity:?}");
            seen.push(code);
        }
    }

'''

CORE_TEST = r'''        // §288：`The Colosseum` —— 第一场 `After` 回到事件，第二场按定数奖励。
        {
            let intro = content.event_step("the_colosseum").expect("the arena");
            let option = intro.options()[0];
            assert_eq!(option.label, "Fight");
            assert_eq!(option.fight, 1, "the slavers are an ordinary fight");
            assert_eq!(option.fight_pool, "ColosseumSlavers");
            assert_eq!(
                option.fight_after, "the_colosseum.after",
                "the first fight returns to the event"
            );
            let after = content.event_step("the_colosseum.after").expect("the outcome step");
            let victory = after.options()[0];
            assert_eq!(victory.label, "VICTORY");
            assert_eq!(victory.fight, 2, "the champions are an elite-tier fight");
            assert_eq!(victory.fight_pool, "ColosseumChampions");
            assert!(victory.fight_after.is_empty(), "VICTORY ends the event");
            assert_eq!(after.options()[1].label, "COWARDICE");
        }

        // §288：**楼层门槛** —— `Dead Adventurer` 只在第 7 层之后出现（wiki）。
        // 两侧都要验：第 6 层筛掉它，第 7 层它在。
        {
            let low = content.event_pool_at("Events", 6).expect("the act-1 pool");
            let ids: std::vec::Vec<&str> = low.iter().filter(|id| !id.is_empty()).copied().collect();
            assert!(
                !ids.contains(&"dead_adventurer"),
                "floor 6 must not offer Dead Adventurer: {ids:?}"
            );
            let high = content.event_pool_at("Events", 7).expect("the act-1 pool");
            let ids: std::vec::Vec<&str> = high.iter().filter(|id| !id.is_empty()).copied().collect();
            assert!(
                ids.contains(&"dead_adventurer"),
                "floor 7 must offer Dead Adventurer: {ids:?}"
            );
            // 门槛只影响那一个：其余事件在两层都在（否则"门槛"其实是"整张表变短了"）。
            let low_all: std::vec::Vec<&str> =
                content.event_pool("Events").expect("the whole pool")
                    .iter().filter(|id| !id.is_empty()).copied().collect();
            assert_eq!(ids.len() + 1, low_all.len(), "exactly one event is gated");
            for id in ids {
                assert!(low_all.contains(&id), "{id} must also be on the floor-6 list");
            }
        }

'''


def main():
    s = io.open(STATE, encoding='utf-8').read()
    anchor = '''    /// §286：**进入效果**在**到达**目标段时兑，而且和选项效果同一个事务。'''
    assert s.count(anchor) == 1
    s = s.replace(anchor, STATE_TESTS + anchor)
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)

    c = io.open(CORE, encoding='utf-8').read()
    anchor2 = '''        // ★ 没有孤儿段：`EVND` 里每一行都要被某个 `EV.Entry` 或某个 `Next` 指到。'''
    assert c.count(anchor2) == 1
    c = c.replace(anchor2, CORE_TEST + anchor2)
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(c)
    print('§288 tests appended')


main()
