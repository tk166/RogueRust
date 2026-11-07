"""§271 判据：节点类 3 件 + 药水类 2 件。

每条都**两面**。⚠️ "节点类"的判据必须真的走 `begin_node`（那是唯一知道节点类型的地方）——
自己直接改 `pending` 就等于把被测的那一行绕过去。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
ANCHOR = '''    /// §270：**加牌类** —— 所有落点都在 `push_card` 一处。'''

TESTS = r'''    /// §271：**节点类** —— 三个 `begin_node` 分支各管一件事。
    ///
    /// 走的是 `walk_to`（与 §268 那条"节点都能结算"的判据同一招）：它把游标真的挪到一个
    /// 指定类型的节点上，所以 `begin_node` 里的分支**真的**被执行到。
    #[test]
    fn the_node_relics_pay_on_the_right_kind_of_room() {
        // ---- `meal_ticket`：进商店回 15（**进门就付**，不是买了东西才付）。
        let mut run = ironclad();
        run.push_relic("meal_ticket").expect("meal_ticket");
        if walk_to(&mut run, crate::map::NodeKind::Shop) {
            run.adjust_health(-30);
            let hp = run.health();
            run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the shop");
            assert_eq!(run.pending(), Pending::Shop);
            assert_eq!(run.health(), hp + 15, "meal_ticket: +15 on entering a shop");
        }

        // 反面：同一件遗物进**别的**房间不回血。
        let mut run = ironclad();
        run.push_relic("meal_ticket").expect("meal_ticket");
        if walk_to(&mut run, crate::map::NodeKind::Rest) {
            run.adjust_health(-30);
            let hp = run.health();
            run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the campfire");
            assert_eq!(run.health(), hp, "meal_ticket must not pay on a rest site");
        }

        // ---- `ssserpent_head`：进 `?` 房 +50 金。
        let mut run = ironclad();
        run.push_relic("ssserpent_head").expect("ssserpent_head");
        if walk_to(&mut run, crate::map::NodeKind::Unknown) {
            let gold = run.gold();
            let kind = run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the ? room");
            assert_eq!(kind, crate::map::NodeKind::Unknown);
            assert_eq!(run.gold(), gold + 50, "ssserpent_head: +50 per ? room");
        }

        // 反面：没有这件遗物时一分钱不多。
        let mut run = ironclad();
        if walk_to(&mut run, crate::map::NodeKind::Unknown) {
            let gold = run.gold();
            run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the ? room");
            assert_eq!(run.gold(), gold, "no ssserpent_head ⇒ no gold");
        }

        // ---- `ancient_tea_set`：进篝火 ⇒ **下一场**战斗开战 +2 能量；打完一场就没了。
        let mut run = ironclad();
        run.push_relic("ancient_tea_set").expect("ancient_tea_set");
        assert_eq!(
            run.combat_bonus_for(FightKind::Normal).status_count,
            0,
            "before any rest site there is nothing pending"
        );
        if walk_to(&mut run, crate::map::NodeKind::Rest) {
            run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the campfire");
            assert!(run.tea_set_pending(), "a rest site owes the next fight 2 energy");
            let bonus = run.combat_bonus_for(FightKind::Normal);
            assert_eq!(bonus.status_count, 1, "the pending status is in the bonus");
            let entry = bonus.statuses[0].expect("an entry");
            assert_eq!(entry.id, "standard.ancient_tea_set", "its own status, not lantern's");
            assert_eq!(entry.stacks, 1, "one stack of a +2 status");

            // 兑现：清掉之后**下一场**就不该再有它（"the next combat" 只是一场）。
            run.clear_tea_set();
            assert_eq!(
                run.combat_bonus_for(FightKind::Normal).status_count,
                0,
                "the charge is for one combat only"
            );
        }

        // 反面：没有这件遗物时进篝火不欠任何东西。
        let mut run = ironclad();
        if walk_to(&mut run, crate::map::NodeKind::Rest) {
            run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the campfire");
            assert!(!run.tea_set_pending(), "no relic ⇒ nothing pending");
            assert_eq!(run.combat_bonus_for(FightKind::Normal).status_count, 0);
        }
    }

    /// §271：**药水类** —— `sozu` 拦药水（两个入口），`toy_ornithopter` 的 5 由 wasm 兑现
    /// （这里只钉运行层那一半：遗物表里的数字）。
    #[test]
    fn sozu_refuses_potions_at_both_doors() {
        // ---- 门 1：`push_potion` 拒绝（事件/调试入口递过来的也收不了）。
        let mut run = ironclad();
        run.push_relic("sozu").expect("sozu");
        let before = *run.clone();
        assert_eq!(
            run.push_potion("fire_potion"),
            Err(RunError::PotionGainBlocked),
            "sozu: you can no longer obtain potions"
        );
        assert_eq!(run.potions().len(), 0, "nothing entered the belt");
        assert!(run == before, "a refused potion must not change the run");

        // ---- 门 2：奖励屏上**根本不该出现**那一格（不发，而不是"发了再拒绝"）。
        // 用一条固定种子把"40% 掉率"的随机流走满：无论掷骰结果如何，`sozu` 之下都没有药水。
        for seed in 0..24 {
            let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
            run.push_relic("sozu").expect("sozu");
            run.roll_reward(&TYPED_CARDS, &POTIONS, &RELICS, FightKind::Normal)
                .expect("a reward");
            assert_eq!(
                run.reward().potion().as_str(),
                "",
                "seed {seed}: sozu must not offer a potion"
            );
        }
        // 反面：没有 `sozu` 时 24 个种子里**至少有一个**掉药水（否则上一条什么也没证明）。
        let mut any = false;
        for seed in 0..24 {
            let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
            run.roll_reward(&TYPED_CARDS, &POTIONS, &RELICS, FightKind::Normal)
                .expect("a reward");
            if !run.reward().potion().as_str().is_empty() {
                any = true;
            }
        }
        assert!(any, "the control must actually drop a potion somewhere");

        // ---- `sozu` 的另一半：每回合 +1 能量的载体。
        let mut run = ironclad();
        run.push_relic("sozu").expect("sozu");
        let bonus = run.combat_bonus_for(FightKind::Normal);
        assert_eq!(bonus.status_count, 1, "sozu's energy half is granted");
        assert_eq!(
            bonus.statuses[0].expect("an entry").id,
            "standard.sozu",
            "the carrier is sozu's own status"
        );
    }

    /// §271：`toy_ornithopter` 的参数只存在于遗物表里（wasm 通过
    /// `RunState::relic_effect` 读它，不在 wasm 里写第二个 5）。
    #[test]
    fn the_potion_relics_carry_their_own_numbers() {
        use crate::state::RelicEffect;
        let mut run = ironclad();
        run.push_relic("toy_ornithopter").expect("toy_ornithopter");
        assert_eq!(
            RunState::relic_effect("toy_ornithopter"),
            Some(RelicEffect::PotionUseHeal(5)),
            "the heal amount lives in the relic table, not in the wasm layer"
        );
        // 反面：不是"任何遗物都给 +5"。
        assert_eq!(RunState::relic_effect("burning_blood"), Some(RelicEffect::EndOfCombatHeal(6)));
    }

'''


def main():
    src = io.open(P, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'the_node_relics_pay_on_the_right_kind_of_room' not in src
    src = src.replace(ANCHOR, TESTS + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('§271 tests appended')


main()
