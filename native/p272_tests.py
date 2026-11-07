"""§272 判据：`?` 房分流 + `tiny_chest` / `juzu_bracelet`。

四组，每组两面：
  1. 概率公式（基础 10/3/2，每次没出现 +基础值，命中归零）—— 直接读 `unknown_room_odds`；
  2. 分布本身（2000 个种子，基础概率下怪物落在 10% 附近）—— 证明掷骰真的用了那三个数；
  3. `tiny_chest`（第 4 个 `?` 房是宝箱、计数归零）与 `juzu_bracelet`（怪物**永不**出现）；
  4. `begin_node` 的四种结果各走既有通道（宝箱 → Chest、商人 → Shop 且摆好货架、
     战斗/事件 → None），以及换幕把计数归零。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
ANCHOR = '''    /// §271：**节点类** —— 三个 `begin_node` 分支各管一件事。'''

TESTS = r'''    /// §272：`?` 房的**概率公式**（wiki 的 10 / 3 / 2，每次"没出现"加一个基础值、命中归零）。
    #[test]
    fn the_unknown_room_odds_walk_the_wikis_base_values() {
        let mut run = ironclad();
        assert_eq!(
            run.unknown_room_odds(),
            [10, 3, 2],
            "an act starts at the wiki's base chances"
        );

        // 三次都没出商店 ⇒ 商店变成 3 × 4 = 12（wiki 的例子是"四个 ? 房没商店 ⇒ 15%"）。
        let mut run = ironclad();
        run.unknown = [0, 3, 0];
        assert_eq!(run.unknown_room_odds(), [10, 12, 2], "shop: 3 × (1 + 3 misses)");
        run.unknown = [0, 4, 0];
        assert_eq!(run.unknown_room_odds()[1], 15, "…and 15 after four, as the wiki says");

        // 三条各自独立推进：怪物连续 5 次没出现 ⇒ 60%。
        run.unknown = [5, 4, 0];
        assert_eq!(run.unknown_room_odds()[0], 60, "monster: 10 × (1 + 5)");

        // `juzu_bracelet` 把怪物那条按成 0（Event 因此变成 95% 的基础档）。
        run.push_relic("juzu_bracelet").expect("juzu_bracelet");
        assert_eq!(run.unknown_room_odds()[0], 0, "juzu_bracelet removes the monster band");
        assert_eq!(run.unknown_room_odds()[1], 15, "…and leaves the shop band alone");
    }

    /// §272：掷骰**真的**用了那三个数。
    ///
    /// 2000 个种子：基础概率下怪物 10%、商人 3%、宝箱 2%。区间取得很宽（±4 个点），
    /// 因为要证明的是"量级对"，不是"随机数好看"。⚠️ 这条判据的价值在于它**会**红：
    /// 把三条基础值写反、或把前缀累加写成独立掷骰，它立刻偏离。
    #[test]
    fn the_unknown_room_roll_matches_the_odds() {
        const SEEDS: i32 = 2000;
        let mut counts = [0i32; 4]; // monster, shop, treasure, event
        for seed in 0..SEEDS {
            let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
            match run.roll_unknown_room().expect("a roll") {
                UnknownRoom::Monster => counts[0] += 1,
                UnknownRoom::Shop => counts[1] += 1,
                UnknownRoom::Treasure => counts[2] += 1,
                UnknownRoom::Event => counts[3] += 1,
                UnknownRoom::Unresolved => panic!("a roll must resolve"),
            }
        }
        let per_cent = |n: i32| n * 100 / SEEDS;
        assert!(
            (6..=14).contains(&per_cent(counts[0])),
            "monster {}% is not near 10% (counts {counts:?})",
            per_cent(counts[0])
        );
        assert!(
            (1..=6).contains(&per_cent(counts[1])),
            "shop {}% is not near 3% (counts {counts:?})",
            per_cent(counts[1])
        );
        assert!(
            (0..=5).contains(&per_cent(counts[2])),
            "treasure {}% is not near 2% (counts {counts:?})",
            per_cent(counts[2])
        );
        // 事件吃掉剩下的（基础 85%）。
        assert!(
            (78..=92).contains(&per_cent(counts[3])),
            "event {}% is not near 85% (counts {counts:?})",
            per_cent(counts[3])
        );
    }

    /// §272：`tiny_chest` 每第 4 个 `?` 房是宝箱；`juzu_bracelet` 永不出现怪物。
    #[test]
    fn tiny_chest_and_juzu_bracelet_change_the_roll() {
        // ---- `tiny_chest`：四次里**必有一次**宝箱，而且是第 4 次。
        let mut run = ironclad();
        run.push_relic("tiny_chest").expect("tiny_chest");
        let mut treasure_at = None;
        for index in 1..=4u8 {
            let outcome = run.roll_unknown_room().expect("a roll");
            if outcome == UnknownRoom::Treasure {
                treasure_at = Some(index);
            }
        }
        assert_eq!(
            treasure_at,
            Some(TINY_CHEST_ROOMS),
            "the 4th ? room is forced to be a treasure room"
        );
        assert_eq!(run.tiny_chest_rooms(), 0, "the counter resets after it pays");
        // 宝箱出现 ⇒ treasure 的 miss 计数归零。
        assert_eq!(run.unknown_odds()[2], 0, "a treasure resets the treasure counter");

        // 反面：没有这件遗物时计数永远是 0（不增长）。
        let mut run = ironclad();
        for _ in 0..6 {
            run.roll_unknown_room().expect("a roll");
        }
        assert_eq!(run.tiny_chest_rooms(), 0, "without the relic the counter stays put");

        // ---- `juzu_bracelet`：怪物**永不**出现，哪怕怪物计数已经堆到必然会出的地步。
        let mut run = ironclad();
        run.push_relic("juzu_bracelet").expect("juzu_bracelet");
        run.unknown = [9, 0, 0]; // 没有 juzu 时这里已经 100% 怪物
        for seed in 0..200 {
            run.unknown[0] = 9;
            let outcome = run.roll_unknown_room().expect("a roll");
            assert_ne!(
                outcome, UnknownRoom::Monster,
                "seed {seed}: juzu_bracelet must keep monsters out of ? rooms"
            );
        }
    }

    /// §272：`begin_node` 的**四种结果**各走既有通道（这也是 `?` 房与内核其余部分的接线判据）。
    #[test]
    fn an_unknown_room_settles_into_the_channel_its_result_names() {
        use crate::map::NodeKind;
        // 四种结果各造一次：直接对着 `?` 房节点反复 `begin_node`，直到四种都见到。
        // 判定标准是**可观察的三件事**：pending、unknown_room()、以及商人的货架。
        let mut seen_treasure = false;
        let mut seen_shop = false;
        let mut seen_monster = false;
        let mut seen_event = false;
        for seed in 0..400 {
            let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
            if !walk_to(&mut run, NodeKind::Unknown) {
                continue;
            }
            let kind = run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the ? room");
            assert_eq!(kind, NodeKind::Unknown, "a ? room stays a ? room on the map");
            match run.unknown_room() {
                UnknownRoom::Treasure => {
                    assert_eq!(run.pending(), Pending::Chest, "a treasure opens the chest flow");
                    seen_treasure = true;
                }
                UnknownRoom::Shop => {
                    assert_eq!(run.pending(), Pending::Shop, "a merchant opens the shop flow");
                    assert!(
                        !run.shop().cards().is_empty(),
                        "…and the shelf is stocked by `begin_node` itself"
                    );
                    seen_shop = true;
                }
                UnknownRoom::Monster => {
                    assert_eq!(run.pending(), Pending::None, "a fight is the caller's business");
                    seen_monster = true;
                }
                UnknownRoom::Event => {
                    assert_eq!(run.pending(), Pending::None, "an event is the caller's business");
                    seen_event = true;
                }
                UnknownRoom::Unresolved => panic!("begin_node must resolve the room"),
            }
        }
        assert!(seen_treasure, "no seed produced a treasure ? room");
        assert!(seen_shop, "no seed produced a merchant ? room");
        assert!(seen_monster, "no seed produced a fight ? room");
        assert!(seen_event, "no seed produced an event ? room");
    }

    /// §272：换幕把三条概率（与 `tiny_chest` 的计数）归零 —— wiki："reset in between acts"。
    ///
    /// ⚠️ 这三条计数在 §272 之前**根本没有消费者**，所以"换幕归零"这条规则也一直没有实现。
    #[test]
    fn an_act_change_resets_the_unknown_room_odds() {
        let mut run = ironclad();
        run.unknown = [7, 5, 3];
        run.tiny_chest_rooms = 2;
        run.unknown_room = UnknownRoom::Monster;
        // 走到 Boss 并结算它：那是唯一会换幕的路径。
        run.node = i32::from(crate::map::BOSS_NODE);
        run.floor = crate::map::ROWS as i32 + 1;
        let act = run.act();
        run.mark_boss_beaten();
        assert_ne!(run.act(), act, "the boss advances the act");
        assert_eq!(run.unknown_odds(), [0, 0, 0], "the three counters reset");
        assert_eq!(run.tiny_chest_rooms(), 0, "the tiny chest counter resets too");
        assert_eq!(
            run.unknown_room(),
            UnknownRoom::Unresolved,
            "the resolved room is not carried into the next act"
        );
        assert_eq!(run.unknown_room_odds(), [10, 3, 2], "back to the base chances");
    }

'''


def main():
    src = io.open(P, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'the_unknown_room_odds_walk_the_wikis_base_values' not in src
    src = src.replace(ANCHOR, TESTS + ANCHOR)

    # 测试模块里的字符集：`unknown` 是私有字段，判据要在同一模块里（已经是了）。
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('§272 tests appended')


main()
