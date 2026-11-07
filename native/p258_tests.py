"""§258 判据：A 数据三条 + 虱子一族（红/绿曾经装反）。

每条都两面测，理由与之前一样：只测"新行为出现"的话，"永远这样"也会绿。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
ANCHOR = '''    /// §209：Curl Up —— **首次**掉血时按掷骰加格挡，之后自我摘除；被完全格挡的一击**不**消耗它。'''

TESTS = r'''    /// §258：虱子的 Bite 是**开局掷的**（`roll.bite` 5-7，A2 起 6-8），而绿虱子曾经写死成 6。
    ///
    /// 三段判据：
    /// 1. 掷出来的值落在 A0 的 5-7 / A2 的 6-8 里（**且真的会变**：40 个种子不止一个值）；
    /// 2. 绿虱子的 Bite **打出的伤害就是那个掷值**（写死 6 的话第 1 段仍然绿，第 2 段才红）；
    /// 3. 绿虱子在遭遇里真的存在（`enc_two_louses`）—— 它以前是"有名册行、没有任何遭遇"的死内容。
    #[test]
    fn louse_bites_are_rolled_at_spawn_and_the_green_one_reads_its_roll() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let roll_of = |state: &rd_core::state::CombatState, who: &str| -> i32 {
            state
                .combatant(&cid_in(who))
                .map_or(-1, |c| {
                    c.counters()
                        .iter()
                        .find(|e| e.key.as_str() == "roll.bite")
                        .map_or(-1, |e| e.value)
                })
        };

        for (ascension, low, high) in [(0u8, 5, 7), (2u8, 6, 8)] {
            let mut seen = std::collections::BTreeSet::new();
            for seed in 0..40 {
                let session = build_session_at(seed, "enc_two_louses", 200, None, 0, ascension)
                    .unwrap_or_else(|e| panic!("A{ascension} seed {seed}: {e}"));
                install_session(session);
                let session = slot().as_ref().expect("session");
                let green = roll_of(&session.state, "louse_green");
                assert!(
                    (low..=high).contains(&green),
                    "A{ascension} seed {seed}: roll.bite = {green}, wiki says {low}-{high}"
                );
                seen.insert(green);
                take_session();
            }
            assert!(seen.len() > 1, "A{ascension}: the roll never varied ({seen:?})");
        }

        // 绿虱子打出的伤害 == 它自己的掷值。
        for seed in 0..8 {
            let session = build_session_at(seed, "enc_two_louses", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            install_session(session);
            let (rolled, before) = {
                let session = slot().as_ref().expect("session");
                (
                    roll_of(&session.state, "louse_green"),
                    session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current),
                )
            };
            {
                let session = slot().as_mut().expect("session");
                let row = u32::from(
                    content
                        .lookup_in("louse_green.bite", rd_core::content::EK_EACTION)
                        .expect("the green bite")
                        .index,
                );
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("louse_green"),
                    row,
                    Some(cid_in("hero")),
                )
                .expect("bite");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let after = {
                let session = slot().as_ref().expect("session");
                session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current)
            };
            assert_eq!(before - after, rolled, "seed {seed}: green Bite deals its roll");
            take_session();
        }
    }

    /// §258：`time_eater.head_slam` 的 **A4**（26 → 32）原来整档是缺的。
    ///
    /// A19 那一档本来就在（它加 2 张 Slimed），但它的伤害也停在 26 —— 也就是说从 A4 起
    /// 一直少 6 点。判据在**边界两侧**：A3 是 26，A4 是 32。
    #[test]
    fn time_eater_head_slam_reaches_32_at_a4() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        for (ascension, expected) in [(3u8, 26), (4u8, 32), (19u8, 32)] {
            let session = build_session_at(21, "enc_time_eater", 400, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            let before = {
                let session = slot().as_ref().expect("session");
                session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current)
            };
            {
                let session = slot().as_mut().expect("session");
                let row = u32::from(
                    content
                        .lookup_in("time_eater.head_slam", rd_core::content::EK_EACTION)
                        .expect("head slam")
                        .index,
                );
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("time_eater"),
                    row,
                    Some(cid_in("hero")),
                )
                .expect("head slam");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let after = {
                let session = slot().as_ref().expect("session");
                session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current)
            };
            assert_eq!(before - after, expected, "A{ascension}: Head Slam damage");
            take_session();
        }
    }

    /// §258：`slaver_red.scrape` 的 **A17**（Vulnerable 1 → 2）原来整档是缺的。
    #[test]
    fn slaver_red_scrape_applies_two_vulnerable_from_a17() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        for (ascension, expected) in [(16u8, 1), (17u8, 2)] {
            let session = build_session_at(22, "enc_slavers", 300, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            {
                let session = slot().as_mut().expect("session");
                let row = u32::from(
                    content
                        .lookup_in("slaver_red.scrape", rd_core::content::EK_EACTION)
                        .expect("scrape")
                        .index,
                );
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("slaver_red"),
                    row,
                    Some(cid_in("hero")),
                )
                .expect("scrape");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let stacks = {
                let session = slot().as_ref().expect("session");
                session
                    .state
                    .combatant(&cid_in("hero"))
                    .map_or(0, |c| {
                        c.statuses()
                            .iter()
                            .filter(|s| s.definition_id.as_str() == "standard.vulnerable")
                            .map(|s| s.stacks)
                            .sum::<i32>()
                    })
            };
            assert_eq!(stacks, expected, "A{ascension}: Vulnerable from Scrape");
            take_session();
        }
    }

    /// §258：两只虱子的**招式表**（wiki：红 = Bite + Grow，绿 = Bite + Spit Web）。
    ///
    /// 之前是反的：红虱子身上挂着 Spit Web，绿虱子有 Grow 而没有 Spit Web。这条判据直接读镜像的
    /// `ENCT.Enemies[].Actions`，所以"只改名册、没改遭遇"也会红（两者必须一致，内容门也查）。
    #[test]
    fn the_two_louses_have_the_moves_the_wiki_gives_them() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let entry = content
            .lookup_in("enc_two_louses", rd_core::content::EK_ENCOUNTER)
            .expect("the 2-louse encounter");
        let list = content
            .encounter_enemies(u32::from(entry.index))
            .expect("enemies");
        let mut red = std::vec::Vec::new();
        let mut green = std::vec::Vec::new();
        for index in 0..list.len() {
            let spec = list.get(index).expect("a record");
            let mut actions = std::vec::Vec::new();
            for action in spec.actions().expect("an actions cell") {
                actions.push(std::string::String::from(action));
            }
            match spec.id().expect("an id") {
                "louse_red" => red = actions,
                "louse_green" => green = actions,
                other => panic!("unexpected enemy {other}"),
            }
        }
        assert_eq!(red, ["louse_red.bite", "louse_red.grow"], "wiki: Red Louse = Bite + Grow");
        assert_eq!(
            green,
            ["louse_green.bite", "louse_green.spit_web"],
            "wiki: Green Louse = Bite + Spit Web"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'louse_bites_are_rolled_at_spawn' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('rd-wasm: 4 tests appended')


main()
