"""§318（二）：两条新事件的判据 —— 选项效果与"事件中途开战斗"的奖励覆盖。

判据直接从**内容**读选项（而不是硬编码 id），因为这两条事件的数值是 wiki 的：
* `Winding Halls` 的 `Embrace Madness`：2 张 `madness` + 失去 12.5% 最大生命（A15: 18%）；
  跑一层就是"牌组多两张、血少了"。
* `Mysterious Sphere` 的 `Open Sphere`：`fight = 1`、`fight_pool = MysteriousSphere`、
  `fight_after` 指回收尾段，奖励覆盖里带 `rare` 遗物。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

TESTS = '''
    /// §318：`Winding Halls` 的 `Embrace Madness` —— 2 张 Madness + 失去 12.5% 最大生命。
    ///
    /// 判据读**跑层算出来的结果**（牌组多两张、血少 12.5%），不是读内容里的字符串：
    /// 内容门已经比过词表，这里问的是"点下去到底发生了什么"。
    #[test]
    fn winding_halls_embrace_madness_gives_two_madness_and_costs_health() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        assert!(walk_to(&mut run, NodeKind::Unknown), "a `?` node must exist");
        run.begin_node(&pool, &[]).expect("the node opens");
        run.begin_event("winding_halls", "winding_halls").expect("the event");
        let deck_before = run.deck().len();
        let hp_before = run.health();

        // 选项 0 = `Embrace Madness`（内容里的顺序，wiki 的第一个）。
        run.resolve_event_effects(
            &EventMove {
                effects: effects_from(0),
                ..EventMove::none()
            },
            &pool,
        )
        .expect("the choice resolves");

        assert_eq!(run.deck().len(), deck_before + 2, "two Madness cards");
        let madness = run
            .deck()
            .iter()
            .filter(|card| card.as_str().starts_with("madness"))
            .count();
        assert_eq!(madness, 2, "and they are Madness");
        // 12.5% 的 80 = 10。
        assert_eq!(run.health(), hp_before - 10, "and it costs 12.5% of max HP");
    }

    /// §318：`Mysterious Sphere` 的 `Open Sphere` —— 事件开战斗 + Rare 遗物，战斗完**回到**事件。
    #[test]
    fn mysterious_sphere_starts_a_fight_that_pays_a_rare_relic() {
        let pool = curse_pool();
        let mut run = RunState::new(11, 80, 0, &["strike"; 5]).expect("a run");
        assert!(walk_to(&mut run, NodeKind::Unknown), "a `?` node must exist");
        run.begin_node(&pool, &[]).expect("the node opens");
        run.begin_event("mysterious_sphere", "mysterious_sphere").expect("the event");

        let choice = fight_option("mysterious_sphere", 0);
        assert_eq!(choice.fight, 1, "it is a normal-monster fight");
        assert_eq!(choice.fight_pool, "MysteriousSphere");
        assert_eq!(choice.fight_after, "mysterious_sphere.after");
        assert_eq!(
            choice.fight_relic_rarity, Some(3),
            "wiki: the reward is a **Rare** relic (3 = the rarity code + 1)"
        );

        run.resolve_event_effects(&choice, &pool).expect("the fight starts");
        assert_eq!(run.event_fight(), 1);
        assert_eq!(run.event_fight_pool(), "MysteriousSphere");
        assert!(!run.node_resolved(), "the node still owes the relic screen");

        assert!(run.resume_event_after_fight(), "the fight returns to the event");
        assert_eq!(run.event_step(), "mysterious_sphere.after");
    }
'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    anchor = '''    /// §288：`After` —— 战斗打完之后**回到事件**，而且房间**还没**结算'''
    assert text.count(anchor) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(anchor, TESTS + '\n' + anchor))
    print('event tests added')


main()
