"""§269 判据：战斗类型层（4）+ 奖励层（5）。

这两组都**不在战斗里跑**，所以判据落在运行层的数字上：

* 战斗类型层：`combat_bonus_for(kind)` 在**不同 kind** 下给出**不同**的加成，
  以及 `enemy_health_bonus_percent(Elite)` 比 `Normal` 少 25；
* 奖励层：`reward_card_count(kind)` 与"药水必掉"/"精英多一件遗物"。

⚠️ 每条都两面：**该生效的 kind 生效**、**不该生效的 kind 不生效**。没有反面，
`sling_of_courage` 就会变成"任何战斗都 +2 力量"而判据全绿。
"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
ANCHOR = '''    /// §268：零基建档收尾的接线'''

TESTS = r'''    /// §269：**战斗类型层** —— 同一个遗物在不同 `FightKind` 下给出不同的加成。
    #[test]
    fn the_kind_gated_relics_only_fire_in_their_own_kinds() {
        use rd_run::state::{FightKind, KindMask};

        // ---- Sling of Courage：**只有**精英战 +2 力量。
        let mut run = ironclad();
        run.push_relic("sling_of_courage").expect("sling");
        for (kind, want) in [
            (FightKind::Normal, 0),
            (FightKind::Elite, 1),
            (FightKind::Boss, 0),
        ] {
            let bonus = run.combat_bonus_for(kind);
            assert_eq!(bonus.status_count, want, "sling_of_courage in {kind:?}");
            if want == 1 {
                let entry = bonus.statuses[0].expect("entry");
                assert_eq!(entry.id, "standard.strength");
                assert_eq!(entry.stacks, 2, "sling_of_courage: +2 Strength");
            }
        }

        // ---- Slaver's Collar：Boss 与精英战各 +1 能量的载体；普通战没有。
        let mut run = ironclad();
        run.push_relic("slavers_collar").expect("collar");
        for (kind, want) in [
            (FightKind::Normal, 0),
            (FightKind::Elite, 1),
            (FightKind::Boss, 1),
        ] {
            let bonus = run.combat_bonus_for(kind);
            assert_eq!(bonus.status_count, want, "slavers_collar in {kind:?}");
            if want == 1 {
                assert_eq!(bonus.statuses[0].expect("entry").id, "standard.slavers_collar");
            }
        }

        // ---- Pantograph：**只有** Boss 战开战回 25。
        let mut run = ironclad();
        run.push_relic("pantograph").expect("pantograph");
        assert_eq!(run.combat_bonus_for(FightKind::Normal).start_heal, 0);
        assert_eq!(run.combat_bonus_for(FightKind::Elite).start_heal, 0);
        assert_eq!(run.combat_bonus_for(FightKind::Boss).start_heal, 25);

        // ---- Preserved Insect：**只有**精英战的敌人血量 -25%。
        let mut run = ironclad();
        run.push_relic("preserved_insect").expect("insect");
        assert_eq!(run.enemy_health_bonus_percent(FightKind::Normal), 0);
        assert_eq!(
            run.enemy_health_bonus_percent(FightKind::Elite),
            -25,
            "preserved_insect: elite enemies lose 25% HP"
        );
        assert_eq!(run.enemy_health_bonus_percent(FightKind::Boss), 0);

        // 与升阶的 +75% 叠加（同一条通道 ⇒ 加法）：A7 对精英给 +75，于是净 +50。
        let mut ascended = rd_run::state::RunState::new_with_ascension(
            7,
            80,
            i32::MAX,
            &["strike"; 10],
            rd_run::state::A_ELITE_HP,
        )
        .expect("an ascended run");
        ascended.push_relic("preserved_insect").expect("insect");
        assert_eq!(
            ascended.enemy_health_bonus_percent(FightKind::Elite),
            50,
            "the ascension bonus and the relic share one channel (75 - 25)"
        );
        assert!(
            KindMask::ELITE.covers(FightKind::Elite) && !KindMask::ELITE.covers(FightKind::Boss),
            "the mask itself"
        );
    }

    /// §269：**奖励层** —— 卡数 / 药水 / 额外遗物。
    #[test]
    fn the_reward_layer_relics_change_the_payout() {
        use rd_run::state::{FightKind, MAX_REWARD_CARDS};

        // 卡数：基线 3。
        let run = ironclad();
        assert_eq!(run.reward_card_count(FightKind::Normal), 3, "baseline");
        assert_eq!(run.reward_card_count(FightKind::Normal), MAX_REWARD_CARDS);

        // Question Card：任何战斗 +1。
        let mut run = ironclad();
        run.push_relic("question_card").expect("question_card");
        assert_eq!(run.reward_card_count(FightKind::Normal), 4, "question_card: +1");
        assert_eq!(run.reward_card_count(FightKind::Boss), 4, "…and on a boss too");

        // Prayer Wheel：**只有**普通怪 +1。
        let mut run = ironclad();
        run.push_relic("prayer_wheel").expect("prayer_wheel");
        assert_eq!(run.reward_card_count(FightKind::Normal), 4, "prayer_wheel: normal +1");
        assert_eq!(run.reward_card_count(FightKind::Elite), 3, "…and not on an elite");

        // Busted Crown：-2（钳到下限 1）+ 每回合 +1 能量的载体。
        let mut run = ironclad();
        run.push_relic("busted_crown").expect("busted_crown");
        assert_eq!(run.reward_card_count(FightKind::Normal), 1, "busted_crown: 3 - 2");
        assert_eq!(
            run.combat_bonus_for(FightKind::Normal).status_count,
            1,
            "busted_crown also grants its energy carrier"
        );
        assert_eq!(
            run.combat_bonus_for(FightKind::Normal).statuses[0].expect("entry").id,
            "standard.busted_crown"
        );

        // 两件一起：+1 -2 = 2。
        let mut run = ironclad();
        run.push_relic("question_card").expect("q");
        run.push_relic("busted_crown").expect("b");
        assert_eq!(run.reward_card_count(FightKind::Normal), 2, "+1 and -2 make 2");
    }

'''


def main():
    src = io.open(RUN, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'the_kind_gated_relics_only_fire_in_their_own_kinds' not in src
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('tests appended')


main()
