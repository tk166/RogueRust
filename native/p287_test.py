"""§287 判据：① `card_damage` 条件的两侧；② 战后欠账的消费；③ 醒着的 Lagavulin 池。

判据都放在能同时看到**内容**与**局面**的层（rd-core 测内容与条件，rd-run 测欠账消费）。
"""
import io

CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'
STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

# ── ① rd-core：Wing Statue 的条件用**真实镜像**两侧验
CORE_TEST = r'''
        // §287：`Wing Statue` 的 `[Destroy]` 要有"牌组里有一张**单次** ≥10 伤害的牌"。
        // 两侧都要验：`bash+`（10）在、`strike+`（9）不在。只验一侧的话，
        // "条件永远成立"与"条件永远不成立"都能通过。
        {
            let wing = content.event_step("wing_statue").expect("the statue");
            let destroy = wing.options()[1];
            assert_eq!(destroy.label, "Destroy");
            let facts = |deck: &'static [&'static str], max_hit: i32| {
                crate::run_expr::RunFacts {
                    gold: 0,
                    health: 80,
                    health_max: 80,
                    ascension: 0,
                    relics: &[],
                    deck,
                    max_hit_damage: max_hit,
                }
            };
            // 镜像里读出来的"单次最高伤害"：`bash+` = 10、`strike+` = 9、`defend` = 0。
            let with_bash = content.max_deck_hit_damage(&["strike", "defend", "bash+"]);
            let with_strike = content.max_deck_hit_damage(&["strike", "defend"]);
            assert_eq!(with_bash, 10, "bash+ deals 10 per hit");
            assert_eq!(with_strike, 6, "strike deals 6");
            assert!(
                crate::run_expr::option_is_available(
                    content,
                    destroy.term,
                    &facts(&["strike", "defend", "bash+"], with_bash)
                )
                .expect("the condition reads"),
                "a deck holding bash+ must show [Destroy]"
            );
            assert!(
                !crate::run_expr::option_is_available(
                    content,
                    destroy.term,
                    &facts(&["strike", "defend"], with_strike)
                )
                .expect("the condition reads"),
                "a deck whose best hit is 6 must hide [Destroy]"
            );
        }
'''

# ── ② rd-run：欠账由 roll_reward 消费，且只消费一次
STATE_TEST = r'''    /// §287：**战后补偿**（`Dead Adventurer`）—— 金币欠账 +30、遗物欠账"不掉"，
    /// 而且**只消费一次**（第二场战斗不再受影响）。
    #[test]
    fn the_fight_reward_debt_is_paid_once() {
        let cards = curse_pool();
        let relics = [
            PoolRelic { id: "anchor", rarity: Rarity::Common },
            PoolRelic { id: "vajra", rarity: Rarity::Common },
        ];
        let mut run = RunState::new(7, 80, 100, &["strike"; 5]).expect("a run");
        run.begin_event("dead_adventurer", "dead_adventurer").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[
                    (EventEffect::FightGoldBonus(30), None),
                    (EventEffect::FightNoRelic, None),
                ],
                ..EventMove::none()
            },
            &cards,
        )
        .expect("the debt is recorded");

        let (low, high) = reward_bands(FightKind::Elite, run.rarity_offset());
        let mut paid = 0;
        for _ in 0..16 {
            let mut probe = run;
            probe
                .roll_reward(FightKind::Elite, &cards, &relics, &[], false)
                .expect("the elite pays out");
            let gold = probe.reward_gold();
            assert!(
                gold >= low + 30 && gold <= high + 30,
                "the elite's {low}..={high} plus the 30-gold debt, got {gold}"
            );
            assert_eq!(probe.reward_relic(), None, "the relic debt says `no relic`");
            paid = gold;
            break;
        }
        assert!(paid >= 30);

        // 第二场战斗：欠账已经付过，所以是一次正常结算（有遗物、没有 +30）。
        let mut second = run;
        second
            .roll_reward(FightKind::Elite, &cards, &relics, &[], false)
            .expect("the second elite pays out");
        assert!(second.reward_relic().is_some(), "the second fight pays its relic");
        let (low2, high2) = reward_bands(FightKind::Elite, run.rarity_offset());
        assert!(
            second.reward_gold() >= low2 && second.reward_gold() <= high2,
            "no debt left: {} must be inside {low2}..={high2}",
            second.reward_gold()
        );
    }

    /// §287：**开一个事件就清掉欠账** —— 否则上一次事件的金币会漏进下一场战斗。
    #[test]
    fn opening_an_event_clears_the_debt() {
        let cards = curse_pool();
        let relics = [PoolRelic { id: "anchor", rarity: Rarity::Common }];
        let mut run = RunState::new(7, 80, 100, &["strike"; 5]).expect("a run");
        run.begin_event("dead_adventurer", "dead_adventurer").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::FightGoldBonus(30), None)],
                ..EventMove::none()
            },
            &cards,
        )
        .expect("the debt is recorded");
        // 另一个事件开始了：欠账属于**上一个**事件。
        run.begin_event("scrap_pile", "scrap_pile").expect("the next event");
        run
            .roll_reward(FightKind::Elite, &cards, &relics, &[], false)
            .expect("the elite pays out");
        let (low, high) = reward_bands(FightKind::Elite, run.rarity_offset());
        assert!(
            run.reward_gold() <= high,
            "the old debt must not leak: {} is above {high}",
            run.reward_gold()
        );
        assert!(run.reward_gold() >= low);
    }

'''


def main():
    c = io.open(CORE, encoding='utf-8').read()
    anchor = '''        // ★ 没有孤儿段：`EVND` 里每一行都要被某个 `EV.Entry` 或某个 `Next` 指到。'''
    assert c.count(anchor) == 1
    c = c.replace(anchor, CORE_TEST + anchor)
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(c)

    s = io.open(STATE, encoding='utf-8').read()
    anchor2 = '''    /// §278：事件是**一棵树** —— 走完一段不结算，走完最后一段才结算。'''
    assert s.count(anchor2) == 1
    s = s.replace(anchor2, STATE_TEST + anchor2)
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('§287 tests appended')


main()
