"""§289 判据：`MaxFloor` 两侧 / `fight_relic:<id>` 三条 / 独立药水概率不动追踪值。"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'

STATE_TESTS = r'''    /// §289：**指名遗物**（`fight_relic:<id>`）—— 命中 / 不在池里 / 已持有，三种都要答得清。
    ///
    /// `Event` 稀有度（`red_mask`）的**不可掉落**属性意味着按权重/按稀有度都永远抽不到它，
    /// 所以"就是这一件"是唯一能给它的形状 —— 这条判据也顺手钉住了那件事。
    #[test]
    fn a_named_relic_is_paid_exactly_or_not_at_all() {
        let cards = curse_pool();
        let relics = [
            PoolRelic { id: "red_mask", rarity: Rarity::Event },
            PoolRelic { id: "anchor", rarity: Rarity::Common },
        ];
        // ① 命中：指名的那一件就是奖励，不看稀有度。
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("probe", "probe").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::FightRelic, Some("red_mask"))],
                ..EventMove::none()
            },
            &cards,
        )
        .expect("the named relic is recorded");
        run.roll_reward(&cards, &[], &relics, FightKind::Normal)
            .expect("the fight pays out");
        assert_eq!(run.reward_relic(), Some("red_mask"), "the named one, not a weighted one");

        // ② 不在池里 ⇒ **没有遗物**（不退回按权重抽 —— 那会把"就是这一件"变成"随便一件"）。
        let relics_small = [PoolRelic { id: "anchor", rarity: Rarity::Common }];
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("probe", "probe").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::FightRelic, Some("red_mask"))],
                ..EventMove::none()
            },
            &cards,
        )
        .expect("recorded");
        run.roll_reward(&cards, &[], &relics_small, FightKind::Normal)
            .expect("the fight pays out");
        assert_eq!(run.reward_relic(), None, "not in the pool ⇒ nothing, not a substitute");

        // ③ 已经持有 ⇒ 也没有（"再给一件"对遗物是重复）。
        let mut held = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        held.push_relic("red_mask", &cards).expect("already held");
        held.begin_event("probe", "probe").expect("the event");
        held.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::FightRelic, Some("red_mask"))],
                ..EventMove::none()
            },
            &cards,
        )
        .expect("recorded");
        held.roll_reward(&cards, &[], &relics, FightKind::Normal)
            .expect("the fight pays out");
        assert_eq!(held.reward_relic(), None, "already held ⇒ no duplicate");
    }

    /// §289：**独立药水概率** —— 这一场按给定的 pct 掷，而且**不动**那一幕的追踪值。
    #[test]
    fn an_independent_potion_chance_leaves_the_tracker_alone() {
        let cards = curse_pool();
        let relics = [PoolRelic { id: "anchor", rarity: Rarity::Common }];
        // 追踪值先压到 100（下一场"必定掉"），再用 0% 的独立概率覆盖它。
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.set_potion_chance_for_test(100);
        run.begin_event("probe", "probe").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::FightPotionChance(0), None)],
                ..EventMove::none()
            },
            &cards,
        )
        .expect("the override is recorded");
        run.roll_reward(&cards, &[], &relics, FightKind::Normal)
            .expect("the fight pays out");
        assert_eq!(run.reward_potion(), None, "0% must not drop, whatever the tracker says");
        assert_eq!(
            run.potion_drop_chance(),
            100,
            "the act's tracker must be **untouched** by an independent roll"
        );

        // 反证：没有覆盖时，同一颗种子 + 100% 追踪值就**会**掉 —— 否则上面那条只是
        // "药水永远不掉"。
        let mut plain = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        plain.set_potion_chance_for_test(100);
        plain.roll_reward(&cards, &[], &relics, FightKind::Normal)
            .expect("the fight pays out");
        assert!(
            plain.reward_potion().is_some(),
            "without an override, a 100% tracker drops -- otherwise the check above is empty"
        );
    }

'''

CORE_TEST = r'''        // §289：`The Colosseum` 只在**上半场**（`MaxFloor`）—— 两侧都要验。
        {
            let at_3 = content.event_pool_at("Events2", 3).expect("act-2 pool");
            let ids: std::vec::Vec<&str> =
                at_3.iter().filter(|id| !id.is_empty()).copied().collect();
            assert!(
                ids.contains(&"the_colosseum"),
                "floor 3 is the top half: {ids:?}"
            );
            let at_9 = content.event_pool_at("Events2", 9).expect("act-2 pool");
            let ids: std::vec::Vec<&str> =
                at_9.iter().filter(|id| !id.is_empty()).copied().collect();
            assert!(
                !ids.contains(&"the_colosseum"),
                "floor 9 is the bottom half: {ids:?}"
            );
            // 只有它被上界筛掉（其余事件在两层都在）。
            let all: std::vec::Vec<&str> = content
                .event_pool("Events2")
                .expect("the whole act-2 pool")
                .iter()
                .filter(|id| !id.is_empty())
                .copied()
                .collect();
            assert_eq!(all.len(), ids.len() + 1, "exactly one event has an upper bound");
        }

'''


def main():
    s = io.open(STATE, encoding='utf-8').read()
    anchor = '''    /// §288：**定数奖励**（`The Colosseum` 的 `100 Gold, 1 Rare Relic, 1 Uncommon Relic`）。'''
    assert s.count(anchor) == 1
    s = s.replace(anchor, STATE_TESTS + anchor)
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)

    c = io.open(CORE, encoding='utf-8').read()
    anchor2 = '''        // ★ 没有孤儿段：`EVND` 里每一行都要被某个 `EV.Entry` 或某个 `Next` 指到。'''
    assert c.count(anchor2) == 1
    c = c.replace(anchor2, CORE_TEST + anchor2)
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(c)
    print('§289 tests appended')


main()
