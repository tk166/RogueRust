"""§327 判据：`taskmaster.scouring_whip` 的升档（wiki：1 Wound；A2: 2；A18: 3 + 自身 1 Strength）。

为什么在 `rd-wasm`：这条要**跑**动作才看得见（伤害 + 弃牌堆里 Wound 张数 + 自身的 Strength），
而动作的升档选择是 `intent::execute_action` 按战斗状态里的 `ascension` 决定的。
三档各跑一次：**A1 / A2 / A18** —— 阈值两侧都测，这是"每条规则在阈值两侧各测一次"的规矩。
"""

import io

PATH = 'kernel/rd-wasm/src/lib.rs'

ANCHOR = """    #[test]
    fn slaver_red_scrape_applies_two_vulnerable_from_a17() {"""

TESTS = '''    /// §327：`taskmaster.scouring_whip` —— wiki "Adds (1 Wound; A2: 2; A18: 3 Wounds).
    /// (A18: Gains 1 Strength.)"
    ///
    /// 三档一起测（阈值两侧各一次）：A1 → 1 Wound 无 Strength；A2 → 2 Wounds；A18 → 3 Wounds
    /// **且自身 +1 Strength**。只测 A18 会漏掉"A2 那一档根本没写"（那正是修之前的样子）。
    #[test]
    fn taskmaster_scouring_whip_scales_wounds_and_strength_by_ascension() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        // (等级, 弃牌堆 Wound 张数, Taskmaster 自己的 Strength)
        for (ascension, wounds, strength) in [(1u8, 1, 0), (2u8, 2, 0), (17u8, 2, 0), (18u8, 3, 1)] {
            let session = build_session_at(22, "enc_slavers", 300, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            {
                let session = slot().as_mut().expect("session");
                let row = u32::from(
                    content
                        .lookup_in("taskmaster.scouring_whip", rd_core::content::EK_EACTION)
                        .expect("scouring whip")
                        .index,
                );
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("taskmaster"),
                    row,
                    Some(cid_in("hero")),
                )
                .expect("scouring whip");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let session = slot().as_ref().expect("session");
            let pile = session
                .state
                .card_zones(&cid_in("hero"))
                .map(|z| z.slots(rd_core::state::CardZone::DiscardPile).len())
                .unwrap_or(0);
            assert_eq!(pile, wounds, "A{ascension}: Wounds into the discard pile");
            let own_strength = session
                .state
                .combatant(&cid_in("taskmaster"))
                .map_or(0, |c| {
                    c.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == "standard.strength")
                        .map(|s| s.stacks)
                        .sum::<i32>()
                });
            assert_eq!(
                own_strength, strength,
                "A{ascension}: Scouring Whip's own Strength (A18 only)"
            );
            take_session();
        }
    }

    #[test]
    fn slaver_red_scrape_applies_two_vulnerable_from_a17() {'''


t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
assert 'fn taskmaster_scouring_whip_scales_wounds_and_strength_by_ascension' not in t, 'patched'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS))
print('wasm: taskmaster whip test inserted')
