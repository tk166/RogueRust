"""§309（四）：判据。

1. **五件开战状态遗物 ⇒ 五条状态，一条都不许丢**（审阅报告的最小复现，也是"4 格"的真实形态）；
2. 三件拾取类遗物 + `pickup_add` 的**失败原子性**：拒了就必须整局相等；
   同时验"同样条件下合格的池子必须真的生效"（否则上面那条可以被"永远拒绝"满足）。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

TESTS = '''
    /// §309：**五件开战状态遗物 ⇒ 五条状态**（审阅报告的最小复现）。
    ///
    /// 旧容量是 4，而每件带战斗程序的遗物都推一条 `standard.<relic>` 标记 —— 所以拿着
    /// `vajra` + `oddly_smooth_stone` + `thread_and_needle` + `bronze_scales` + `orichalcum`
    /// 这五件**合法且常见**的遗物，第 5 件的效果会**静默消失**（release 里没有任何痕迹）。
    #[test]
    fn a_run_with_five_status_relics_keeps_all_five() {
        let mut run = ironclad();
        let five = [
            ("vajra", "standard.strength", 1),
            ("oddly_smooth_stone", "standard.dexterity", 1),
            ("thread_and_needle", "standard.plated_armor", 4),
            ("bronze_scales", "standard.thorns", 3),
            ("orichalcum", "standard.orichalcum", 1),
        ];
        for (relic, _, _) in five {
            run.push_relic(relic, &[]).expect("a relic with no pickup effect");
        }
        let bonus = run.combat_bonus();
        assert_eq!(bonus.status_count, five.len(), "五件各一条，一条都不许丢");
        for (relic, id, stacks) in five {
            let found = bonus
                .statuses
                .iter()
                .flatten()
                .find(|entry| entry.id == id)
                .unwrap_or_else(|| panic!("{relic} 的状态 {id} 丢了"));
            assert_eq!(found.stacks, stacks, "{relic} 的层数");
        }
    }

    /// §309：拾取类遗物**失败 ⇒ 一个字节都不改**（与 `archive::restore` 同一条纪律）。
    ///
    /// `tiny_house` 会先加金币 / 上限 / 当前血 / 欠一瓶药水 / 欠一张牌，再抽一手候选；
    /// 池子不合格时（空池）抽牌失败 —— 旧实现把前面那些改动留在原地，而遗物没进腰带。
    #[test]
    fn a_refused_tiny_house_changes_nothing_and_a_good_pool_does_everything() {
        let mut run = ironclad();
        let before = run;
        assert!(
            run.push_relic("tiny_house", &[]).is_err(),
            "an empty card pool cannot offer anything"
        );
        assert!(run == before, "a refused pickup changed the run");
        // 反向的一半：同样的遗物、合格的池子必须**真的**生效（否则上面那条可以被"永远拒绝"满足）。
        assert_eq!(run.push_relic("tiny_house", &TYPED_CARDS), Ok(()));
        assert_eq!(run.gold(), before.gold() + TINY_HOUSE_GOLD, "50 gold");
        assert_eq!(
            run.health_max(),
            before.health_max() + TINY_HOUSE_MAX_HEALTH,
            "5 max HP"
        );
        assert_eq!(run.pickup_potions(), 1, "one potion owed");
        assert_eq!(run.pickup_add(), 1, "one card owed");
        assert!(run.deck_contains("tiny_house").is_false(), "sanity: not a card");
    }

    /// §309：`orrery` 同理 —— 先记 5 次欠账再抽一手，抽失败必须整体回滚。
    #[test]
    fn a_refused_orrery_changes_nothing_and_a_good_pool_does_everything() {
        let mut run = ironclad();
        let before = run;
        assert!(run.push_relic("orrery", &[]).is_err(), "an empty pool cannot offer");
        assert!(run == before, "a refused pickup changed the run");
        assert_eq!(run.push_relic("orrery", &TYPED_CARDS), Ok(()));
        assert_eq!(run.pickup_add(), 5, "five cards owed");
        assert_eq!(run.pickup_offer().len(), MAX_REWARD_CARDS, "one offer in hand");
    }

    /// §309：`pickup_add_card` 的"加了一张、再抽下一手失败"路径。
    ///
    /// 触发方式是**池子超过容量**（`MAX_POOL`）：那张牌找得到（所以 `push_card` 成功）、
    /// 但下一次抽候选会在 `pool_fits` 上失败 —— 旧实现会留下"牌进了牌组、欠账没按规矩走"。
    #[test]
    fn a_pickup_add_that_cannot_roll_again_rolls_back_the_card_it_added() {
        // 一个比 `MAX_POOL` 多一格的池子：第一张就是候选里的那张牌。
        let mut oversized = [PoolCard::plain("strike"); MAX_POOL + 1];
        oversized[1] = TYPED_CARDS[2];
        let mut run = ironclad();
        run.push_relic("orrery", &TYPED_CARDS).expect("orrery");
        assert_eq!(run.pickup_add(), 5, "five to go");
        // 先把这一手换成"必定能挑到 anger"（池子里的第三张有类型）。
        run.pickup_offer[0] = RunId::new("anger").expect("an id");
        run.pickup_offer[1] = RunId::EMPTY;
        run.pickup_offer[2] = RunId::EMPTY;
        run.pickup_offer_len = 1;
        let before = run;
        assert!(
            run.pickup_add_card(0, &oversized).is_err(),
            "the next offer cannot be rolled from an oversized pool"
        );
        assert!(run == before, "the card that was added must be rolled back");
    }
'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    anchor = '''    /// §308：删掉一张带成长的牌，**尾槽的 mark 必须归零**。'''
    assert text.count(anchor) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        text.replace(anchor, TESTS + '\n' + anchor))
    print('tests added')


main()
