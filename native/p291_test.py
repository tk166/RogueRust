"""§291 判据：`MinGold` 的两侧，以及"付不起就别画"的可用性两侧。"""
import io

CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'

CORE_TEST = r'''        // §291：`The Joust` 的金币门槛 —— wiki "can only be encountered with more than 50 Gold"。
        // 两侧都要验：50 金币时它**不出现**（否则那个没有 `[Leave]` 的房间会零按钮卡死），
        // 51 金币时它出现。
        {
            let poor = content.event_pool_at("Events2", 3, 50).expect("act-2 pool");
            let ids: std::vec::Vec<&str> =
                poor.iter().filter(|id| !id.is_empty()).copied().collect();
            assert!(
                !ids.contains(&"the_joust"),
                "50 gold must not offer The Joust: {ids:?}"
            );
            let rich = content.event_pool_at("Events2", 3, 51).expect("act-2 pool");
            let ids: std::vec::Vec<&str> =
                rich.iter().filter(|id| !id.is_empty()).copied().collect();
            assert!(
                ids.contains(&"the_joust"),
                "51 gold must offer The Joust: {ids:?}"
            );

            // "付不起就别画"：两个押注项带着 `Requires: gold at_least 50` ——
            // 50 金币可选、49 金币**不可选**（按钮不画，于是没有人能点出一条 `-2`）。
            let offer = content.event_step("the_joust.offer").expect("the offer step");
            assert_eq!(offer.count, 2, "Murderer / Owner, and **no** Leave");
            let facts = |gold: i32| crate::run_expr::RunFacts {
                gold,
                health: 80,
                health_max: 80,
                ascension: 0,
                relics: &[],
                deck: &[],
                max_hit_damage: 0,
            };
            for option in offer.options() {
                assert!(
                    crate::run_expr::option_is_available(content_ref(), option.term, &facts(50))
                        .expect("the condition reads"),
                    "with 50 gold the bet is available"
                );
                assert!(
                    !crate::run_expr::option_is_available(content_ref(), option.term, &facts(49))
                        .expect("the condition reads"),
                    "with 49 gold the bet is hidden (a drawn button would be refused)"
                );
            }
        }

'''


def main():
    c = io.open(CORE, encoding='utf-8').read()
    anchor = '''        // ★ 没有孤儿段：`EVND` 里每一行都要被某个 `EV.Entry` 或某个 `Next` 指到。'''
    assert c.count(anchor) == 1
    c = c.replace(anchor, CORE_TEST + anchor)
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(c)
    print('§291 core test appended')


main()
