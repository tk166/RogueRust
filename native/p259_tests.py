"""§259 判据：篝火四选项 + 六件遗物 + `Lift` 的跨层传递 + 存档版本。

放在 `rd-run` 的 `state.rs` 测试模块里：这一层的全部语义都在运行层，不需要战斗。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
ANCHOR = '''    // ---- settling a node ---------------------------------------------------------------------'''

TESTS = r'''    // ================================================================ §259 篝火四选项

    /// 一个只有牌组的局，用来测篝火的选项集合（地图/战斗都不参与）。
    fn campfire_run() -> RunState {
        let mut run = ironclad();
        run.adjust_health(-20);
        run
    }

    /// `Pending::Rest` 需要一个真的篝火节点。
    fn at_campfire(run: &mut RunState) {
        run.pending = Pending::Rest;
    }

    /// §259：**六件遗物各自改变哪个选项**，以及"满血也能休息 / 全升完则不能打铁"。
    #[test]
    fn campfire_options_follow_the_relics_the_wiki_names() {
        let mut run = campfire_run();
        let base = run.campfire_options();
        assert!(base.rest && base.smith && base.recall, "defaults: Rest / Smith / Recall");
        assert!(!base.lift && !base.toke && !base.dig, "no relic ⇒ no relic option");

        // Girya 开 Lift；用过 3 次之后消失（wiki：up to 3 times）。
        run.push_relic("girya").expect("girya");
        assert!(run.campfire_options().lift, "Girya adds Lift");
        for expected in 1..=3u8 {
            at_campfire(&mut run);
            assert_eq!(run.lift(), Ok(expected), "Lift #{expected}");
        }
        assert!(!run.campfire_options().lift, "after three uses Lift is gone");
        at_campfire(&mut run);
        assert_eq!(run.lift(), Err(RunError::WrongPhase), "a fourth Lift is refused");

        // Peace Pipe 开 Toke（然后它还能删牌）；Shovel 开 Dig。
        let mut run = campfire_run();
        run.push_relic("peace_pipe").expect("peace pipe");
        run.push_relic("shovel").expect("shovel");
        let options = run.campfire_options();
        assert!(options.toke && options.dig, "Peace Pipe / Shovel add their options");

        // Coffee Dripper 与 Mark of the Bloom 关 Rest；Fusion Hammer 关 Smith。
        for relic in ["coffee_dripper", "mark_of_the_bloom"] {
            let mut run = campfire_run();
            run.push_relic(relic).expect(relic);
            assert!(!run.campfire_options().rest, "{relic} removes Rest");
            assert!(run.campfire_options().smith, "{relic} does not touch Smith");
        }
        let mut run = campfire_run();
        run.push_relic("fusion_hammer").expect("fusion hammer");
        assert!(!run.campfire_options().smith, "Fusion Hammer removes Smith");
        assert!(run.campfire_options().rest, "Fusion Hammer does not touch Rest");
    }

    /// §259：**满血也能休息**（wiki 明写），而"牌组全升完 ⇒ 打铁不可用"。
    ///
    /// 后半条是"选项是算出来的"的直接后果：`+` 行在内容里是另一张卡，所以判据只能是
    /// "牌组里还有没有不带 `+` 的 id"。
    #[test]
    fn resting_is_legal_at_full_health_and_smithing_is_not_legal_with_nothing_to_upgrade() {
        let mut run = campfire_run();
        run.health = run.health_max;
        at_campfire(&mut run);
        assert_eq!(run.rest(), Ok(0), "full health: Rest is still legal, it just heals 0");

        let mut run = campfire_run();
        assert!(run.campfire_options().smith, "an un-upgraded deck can Smith");
        for slot in 0..run.deck_len as usize {
            let upgraded = std::format!("{}+", run.deck[slot].as_str());
            run.deck[slot] = RunId::new(&upgraded).expect("an id");
        }
        assert!(
            !run.campfire_options().smith,
            "everything is upgraded ⇒ Smith is greyed out"
        );
    }

    /// §259：`Toke` 删牌**不收钱**，且与商店删牌共用同一段搬移（`marks` 跟着走）。
    #[test]
    fn toke_removes_a_card_without_charging_for_it() {
        let mut run = campfire_run();
        run.push_relic("peace_pipe").expect("peace pipe");
        let gold = run.gold();
        let before = run.deck_len;
        let second_mark = run.marks[1];
        at_campfire(&mut run);
        assert_eq!(run.toke(0), Ok(()), "Toke removes deck[0]");
        assert_eq!(run.deck_len, before - 1, "one card fewer");
        assert_eq!(run.gold(), gold, "Toke is free (unlike the shop's `remove_card`)");
        // §253 的那条纪律：mark 跟着牌走 —— 删掉第一张之后，第二张的 mark 必须还在它身上。
        assert_eq!(run.marks[0], second_mark, "the per-copy mark moves with its card");
        assert_eq!(run.removed_cards(), 0, "Toke is not a paid removal (no price step)");
    }

    /// §259：`Dig` 只抽 **Common/Uncommon/Rare**（wiki 原话），Boss/Shop/Event 一件都不许出。
    #[test]
    fn dig_only_rolls_common_uncommon_or_rare() {
        let mut run = campfire_run();
        run.push_relic("shovel").expect("shovel");
        let pool = [
            PoolRelic {
                id: "coffee_dripper",
                rarity: Rarity::Boss,
            },
            PoolRelic {
                id: "golden_idol",
                rarity: Rarity::Event,
            },
            PoolRelic {
                id: "anchor",
                rarity: Rarity::Common,
            },
            PoolRelic {
                id: "vajra",
                rarity: Rarity::Uncommon,
            },
            PoolRelic {
                id: "girya",
                rarity: Rarity::Rare,
            },
        ];
        for seed in 0..24 {
            let mut run = campfire_run();
            run.seed = seed;
            run.push_relic("shovel").expect("shovel");
            at_campfire(&mut run);
            let dug = run.dig(&pool).expect("dig");
            assert!(
                ["anchor", "vajra", "girya"].contains(&dug.as_str()),
                "seed {seed}: Dig produced {dug} -- only Common/Uncommon/Rare are allowed"
            );
        }
        let _ = pool;
    }

    /// §259：`Lift` 的力量**每场战斗都带**（不是"只下一场"），而且与 `Vajra` **相加**。
    #[test]
    fn lift_strength_applies_to_every_later_fight_and_stacks_with_vajra() {
        let mut run = campfire_run();
        run.push_relic("girya").expect("girya");
        for _ in 0..2 {
            at_campfire(&mut run);
            run.lift().expect("lift");
        }
        let bonus = run.combat_bonus();
        assert_eq!(bonus.status_count, 1, "strength is one merged entry");
        assert_eq!(bonus.statuses[0].map(|s| s.id), Some("standard.strength"));
        assert_eq!(bonus.statuses[0].map(|s| s.stacks), Some(2), "two Lifts ⇒ 2 Strength");

        // 第二场、第三场战斗都还是 2（它读的是 `girya_lifts`，不是"上一次的遗留"）。
        for _ in 0..2 {
            let again = run.combat_bonus();
            assert_eq!(again.statuses[0].map(|s| s.stacks), Some(2), "every fight carries it");
        }

        // 与 Vajra 相加，不是覆盖。
        run.push_relic("vajra").expect("vajra");
        let merged = run.combat_bonus();
        assert_eq!(merged.status_count, 1, "one merged Strength entry");
        assert_eq!(merged.statuses[0].map(|s| s.stacks), Some(3), "2 from Girya + 1 from Vajra");
    }

    /// §259：`Recall` 拿红钥匙，然后 Recall 就不再出现（wiki：一局只有一把）。
    #[test]
    fn recall_grants_the_ruby_key_once() {
        let mut run = campfire_run();
        assert!(run.campfire_options().recall, "Recall is offered by default");
        at_campfire(&mut run);
        assert_eq!(run.recall(), Ok(()));
        assert!(run.ruby_key(), "the key is in the run state");
        assert!(!run.campfire_options().recall, "a second Recall is not offered");
        at_campfire(&mut run);
        assert_eq!(run.recall(), Err(RunError::WrongPhase), "and it is refused");
    }

    /// §259：两个新字段**进存档与哈希**。
    ///
    /// 存档 `VERSION` 也跟着抬到 3 —— 这条判据不做"旧存档能不能读"的兼容（那是 `Version` 错误
    /// 该做的事），它钉的是"写出去、读回来，两个字段都在"。
    #[test]
    fn the_campfire_fields_survive_a_save_and_a_hash() {
        let mut run = campfire_run();
        run.push_relic("girya").expect("girya");
        run.push_relic("peace_pipe").expect("peace pipe");
        for _ in 0..3 {
            at_campfire(&mut run);
            run.lift().expect("lift");
        }
        at_campfire(&mut run);
        run.recall().expect("recall");
        let baseline = crate::hash::state_hash(&run);

        // 走**真实的公开入口**（`archive::write` / `restore`），不是测试专用包装 ——
        // 包装会绕过信封（MAGIC / base64 / RLE / CRC），而"字段进没进 payload"正是要测的东西。
        let mut buf = [0u8; crate::state::archive::MAX_ARCHIVE];
        let len = crate::state::archive::write(&run, 7, &mut buf).expect("write");
        let text = std::str::from_utf8(&buf[..len]).expect("ascii");
        let mut restored = RunState::new(0, 80);
        crate::state::archive::restore(text, 7, &mut restored).expect("read");
        assert_eq!(restored.girya_lifts(), 3, "girya_lifts round-trips");
        assert!(restored.ruby_key(), "ruby_key round-trips");
        assert_eq!(crate::hash::state_hash(&restored), baseline, "the hash round-trips too");

        // 反过来：只差一次 Lift 的两局，哈希必须不同（否则"忘了同步哈希"看不出来）。
        let mut other = restored.clone();
        other.girya_lifts = 2;
        assert_ne!(crate::hash::state_hash(&other), baseline, "girya_lifts is in the hash");
        let mut other = restored.clone();
        other.ruby_key = false;
        assert_ne!(crate::hash::state_hash(&other), baseline, "ruby_key is in the hash");
    }

'''

def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'campfire_options_follow_the_relics' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('rd-run: 7 campfire tests appended')


main()
