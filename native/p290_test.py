"""§290 判据：`gold_all` / `card:<id>` / `The Nest`。"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'

STATE_TESTS = r'''    /// §290：`gold_all` —— 失去**全部**金币，而且**永远付得起**（金额由局面决定）。
    ///
    /// 两侧：有钱 ⇒ 归零；没钱 ⇒ 仍然是 0（不报 `NotEnoughGold` —— 那是 `gold_cost` 的规矩）。
    #[test]
    fn gold_all_takes_everything_and_never_refuses() {
        let pool = curse_pool();
        let mut rich = RunState::new(7, 80, 120, &["strike"; 5]).expect("a run");
        rich.begin_event("probe", "probe").expect("the event");
        rich.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::LoseAllGold, None)],
                ..EventMove::none()
            },
            &pool,
        )
        .expect("paying everything is never refused");
        assert_eq!(rich.gold(), 0, "80 gold becomes 0");

        let mut broke = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        broke.begin_event("probe", "probe").expect("the event");
        broke.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::LoseAllGold, None)],
                ..EventMove::none()
            },
            &pool,
        )
        .expect("with no gold the choice is still available");
        assert_eq!(broke.gold(), 0, "and it stays 0 (not negative)");
    }

    /// §290：`card:<id>` —— 给**指定**的一张牌，而且走的是 `push_card`（不是第二套加牌逻辑）。
    ///
    /// 判据钉三件事：
    /// ① 那张牌进了牌组（`Ritual Dagger` 是 `Special` 稀有度 —— `curse:` 给不了它）；
    /// ② `ceramic_fish` 那类"加牌给钱"的遗物**照旧**生效（证明走的是同一条路）；
    /// ③ 拼错的 id 被拒（`NoSuchCard`），而**不是**静默加一张幽灵卡。
    #[test]
    fn a_named_card_goes_through_the_one_add_card_path() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.push_relic("ceramic_fish", &pool).expect("the fish");
        run.begin_event("the_nest", "the_nest").expect("the event");
        let gold_before = run.gold();
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::GainCard, Some("ritual_dagger")),
                           (EventEffect::LoseHealth(6), None)],
                ..EventMove::none()
            },
            &pool,
        )
        .expect("the dagger lands");
        assert!(
            run.deck().iter().any(|card| card.as_str() == "ritual_dagger"),
            "the named card is in the deck: {:?}",
            run.deck().iter().map(|c| c.as_str()).collect::<std::vec::Vec<_>>()
        );
        assert_eq!(run.health(), 74, "the 6 HP cost landed");
        assert_eq!(
            run.gold(),
            gold_before + 9,
            "`ceramic_fish` pays for **any** card -- so this went through `push_card`"
        );

        // 拼错的 id ⇒ 拒绝，而且**什么都没改**（整结构体相等）。
        let mut typo = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        typo.begin_event("the_nest", "the_nest").expect("the event");
        let before = typo;
        assert_eq!(
            typo.resolve_event_effects(
                &EventMove {
                    effects: &[(EventEffect::GainCard, Some("ritual_daggr"))],
                    ..EventMove::none()
                },
                &pool,
            ),
            Err(RunError::NoSuchCard),
            "a misspelt card id must be refused"
        );
        assert!(typo == before, "not one byte moved");
    }

'''

CORE_TEST = r'''        // §290：`The Nest` —— `[Smash and Grab]` 99（A15 50）金币、`[Stay in Line]` 给 Ritual Dagger
        // 并掉 6 血；两个选项都去一屏"Leave"（wiki 的 Screen 3/4）。
        {
            let nest = content.event_step("the_nest").expect("the nest");
            assert_eq!(nest.count, 2, "two options, no decline");
            let grab = nest.options()[0];
            assert_eq!(grab.label, "Smash and Grab");
            assert_eq!(grab.effects[0].effect, "gold");
            assert_eq!(grab.effects[0].amount, 99, "99 gold on the base");
            let asc = grab.effects_at(15, 15);
            assert_eq!(asc[0].amount, 50, "A15 pays 50");
            let stay = nest.options()[1];
            assert_eq!(stay.label, "Stay in Line");
            assert_eq!(stay.effects[0].effect, "card:ritual_dagger", "§290 `card:<id>`");
            assert_eq!(stay.effects[1].effect, "damage");
            assert_eq!(stay.effects[1].amount, 6, "6 HP");
            for option in nest.options() {
                let next = option.goes_on().expect("both lead to a screen");
                assert_eq!(content.event_step(next).expect("the screen").count, 1);
            }
        }

'''

def main():
    s = io.open(STATE, encoding='utf-8').read()
    anchor = '''    /// §289：**指名遗物**（`fight_relic:<id>`）—— 命中 / 不在池里 / 已持有，三种都要答得清。'''
    assert s.count(anchor) == 1
    s = s.replace(anchor, STATE_TESTS + anchor)
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)

    c = io.open(CORE, encoding='utf-8').read()
    anchor2 = '''        // ★ 没有孤儿段：`EVND` 里每一行都要被某个 `EV.Entry` 或某个 `Next` 指到。'''
    assert c.count(anchor2) == 1
    c = c.replace(anchor2, CORE_TEST + anchor2)
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(c)
    print('§290 tests appended')


main()
