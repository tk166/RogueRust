"""§299：把 `dead_branch` 的判据补强 —— 池子是**任意牌**，不是"只要能加一张"。

负控"池子只要 power"没红，说明原判据只验了"加了一张、不是 `+`、不是 X 费"——
把池子缩成 power 它照样满足。补一条**穷尽**断言：连抽多次，结果里必须出现
**至少一个 attack/skill 标签之外**的牌（Power），即池子不是单一类。
"""
import io

HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'

OLD = '''        assert!(
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
    }'''

NEW = '''        assert!(
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

        // ★ 池子必须是**任意牌**，不是"某一类"。
        // 负控"池子只要 power"曾经**照样绿** —— 因为上面三条对"随便哪一类的任意一张"都成立。
        // 所以这里连抽 40 次并统计**三种卡的种类**：只收一类的话，另外两类永远不出现。
        let mut kinds = (false, false, false); // (attack, skill, power)
        for _ in 0..40 {
            let hand = run(&mut host, true);
            assert_eq!(hand.len(), 1, "each exhaustion adds one card");
            let tag = |name: &str| content.card_has_tag(&hand[0], name) == Some(true);
            kinds.0 |= tag("attack");
            kinds.1 |= tag("skill");
            kinds.2 |= tag("power");
            if kinds.0 && kinds.1 && kinds.2 {
                break;
            }
        }
        assert!(
            kinds.0 && kinds.1 && kinds.2,
            "the pool is *any* base card, so 40 draws must cover all three kinds; got \
             attack={} skill={} power={}",
            kinds.0,
            kinds.1,
            kinds.2
        );
    }'''


def main():
    s = io.open(HOST, encoding='utf-8').read()
    assert s.count(OLD) == 1, s.count(OLD)
    io.open(HOST, 'w', encoding='utf-8', newline='\n').write(s.replace(OLD, NEW))
    print('dead_branch assertion strengthened')


main()
