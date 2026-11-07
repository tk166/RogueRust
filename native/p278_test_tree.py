"""§278：事件判据的 golden_idol 抽查改成钉**树**（两段、三选一、百分比）。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'

OLD = '''        // Spot-check the pair this section exists for: **relic + curse**, and the A15 branch is a
        // different list (`port-plan.md` §188).
        let index = (0..content.event_count())
            .find(|index| content.event(*index).map(|e| e.0) == Some("golden_idol"))
            .expect("golden_idol");
        let (_, _, entry) = content.event(index).unwrap();
        let step = content.event_step(entry).expect("golden_idol's first step");
        let choices = step.options;
        assert_eq!(choices[0].count, 2, "two effects in one option");
        assert_eq!(choices[0].effects[0].effect, "relic:golden_idol");
        assert_eq!(choices[0].effects[1].effect, "curse:injury");
        assert_eq!(choices[0].asc_count, 2, "and an A15 variant of the same length");
        assert_eq!(choices[0].asc[1].effect, "damage", "A15: the idol costs HP instead");
        assert_eq!(choices[0].asc[1].amount, 20, "25% of 80, the wiki's Smash branch");

        // `effects_at` is the **only** place the level decides which list applies.
        assert_eq!(choices[0].effects_at(0, 15)[1].effect, "curse:injury");
        assert_eq!(choices[0].effects_at(14, 15)[1].effect, "curse:injury");
        assert_eq!(choices[0].effects_at(15, 15)[1].effect, "damage");
        assert_eq!(choices[0].effects_at(20, 15)[1].effect, "damage");

        // Leaving costs nothing, and `nothing` has no worse version.
        assert_eq!(choices[1].count, 1);
        assert_eq!(choices[1].effects[0].effect, "nothing");
        assert_eq!(choices[1].asc_count, 0, "no A15 variant where nothing happens");
'''

NEW = '''        // §278：这棵树是这一节存在的理由 —— `golden_idol` 有**两段**，第二段是**三选一**，
        // 而三选一的代价按**最大 HP 的百分比**算（wiki: Smash 25%/A15 35%，Hide 8%/A15 10%）。
        let index = (0..content.event_count())
            .find(|index| content.event(*index).map(|e| e.0) == Some("golden_idol"))
            .expect("golden_idol");
        let (_, _, entry) = content.event(index).unwrap();
        let step = content.event_step(entry).expect("golden_idol's first step");
        let choices = step.options;
        assert_eq!(step.count, 2, "the first step still has two options");
        // 第一段：拿遗物，**然后**去下一段。旧内容把"遗物 + 诅咒"挤在一个选项里，
        // 那正是"两屏被压成一屏"的形状。
        assert_eq!(choices[0].count, 1, "taking the idol is only half of it now");
        assert_eq!(choices[0].effects[0].effect, "relic:golden_idol");
        assert_eq!(
            choices[0].goes_on(),
            Some("golden_idol.boulder"),
            "`Take it` must lead to the boulder scene"
        );
        assert_eq!(choices[0].asc_count, 0, "the relic itself is the same at every ascension");

        // 第二段：三个逃生选项。
        let boulder = content
            .event_step("golden_idol.boulder")
            .expect("the boulder step");
        assert!(!boulder.text.is_empty(), "the boulder step has its own text");
        assert_eq!(boulder.count, 3, "**three** escape options, not two");
        let escape = boulder.options;
        assert_eq!(escape[0].label, "Outrun");
        assert_eq!(escape[0].effects[0].effect, "curse:injury");
        assert_eq!(escape[0].asc_count, 0, "Outrun's curse does not get worse");
        assert_eq!(escape[1].label, "Smash");
        assert_eq!(escape[1].effects[0].effect, "damage_pct:25");
        assert_eq!(escape[1].asc[0].effect, "damage_pct:35", "A15: 25% -> 35%");
        assert_eq!(escape[2].label, "Hide");
        assert_eq!(escape[2].effects[0].effect, "max_hp_pct:8");
        assert_eq!(escape[2].asc[0].effect, "max_hp_pct:10", "A15: 8% -> 10%");

        // `effects_at` is the **only** place the level decides which list applies.
        assert_eq!(escape[1].effects_at(0, 15)[0].effect, "damage_pct:25");
        assert_eq!(escape[1].effects_at(14, 15)[0].effect, "damage_pct:25");
        assert_eq!(escape[1].effects_at(15, 15)[0].effect, "damage_pct:35");
        assert_eq!(escape[1].effects_at(20, 15)[0].effect, "damage_pct:35");
        assert_eq!(escape[2].effects_at(14, 15)[0].effect, "max_hp_pct:8");
        assert_eq!(escape[2].effects_at(15, 15)[0].effect, "max_hp_pct:10");

        // Leaving costs nothing, and `nothing` has no worse version.
        assert_eq!(choices[1].count, 1);
        assert_eq!(choices[1].effects[0].effect, "nothing");
        assert_eq!(choices[1].asc_count, 0, "no A15 variant where nothing happens");
        assert_eq!(choices[1].goes_on(), None, "`Leave it` ends the event");
'''


def main():
    s = io.open(P, encoding='utf-8').read()
    assert s.count(OLD) == 1
    s = s.replace(OLD, NEW)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('golden_idol test now pins the tree')


main()
