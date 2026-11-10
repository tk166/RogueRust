"""§328 行为判据：三条 A17 档真的在战斗里生效（阈值两侧各一次）。

* `cultist.incantation` —— Ritual 4 → **A17: 5**
* `fungi_beast.grow`    —— Strength 4 → **A17: 5**
* `fat_gremlin.smash`   —— 5 伤害 + 1 Weak → **A17: 再加 1 Frail**

判据读的是**战斗状态里的层数**（不是内容 JSON）：内容写对了但 `intent::execute_action`
没选到那一档的话，这一条会红，而内容侧的闸门不会。
"""

import io

PATH = 'kernel/rd-wasm/src/lib.rs'

ANCHOR = """    /// §327：`taskmaster.scouring_whip`"""

TESTS = '''    /// §328：三条 A17 招式表（Ritual / Strength / Frail）在**战斗里**生效。
    ///
    /// 阈值两侧各一次（A16 / A17）：只测 A17 会漏掉"这一档根本没被选中"的实现
    /// （内容里有 `ProgramAsc`、而 `intent::execute_action` 读的是别的字段时就是那样）。
    #[test]
    fn the_three_a17_move_rows_take_effect_in_the_fight() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        // (遭遇, 敌人, 动作, 状态, A16 层数, A17 层数)
        let cases: &[(&str, &str, &str, &str, i32, i32)] = &[
            ("enc_cultist", "cultist", "cultist.incantation", "ritual", 4, 5),
            ("enc_fungi_beast", "fungi_beast", "fungi_beast.grow", "standard.strength", 4, 5),
        ];
        for (encounter, enemy, action_id, status, low, high) in cases {
            for (ascension, expected) in [(16u8, *low), (17u8, *high)] {
                let session = build_session_at(22, encounter, 300, None, 0, ascension)
                    .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
                install_session(session);
                {
                    let session = slot().as_mut().expect("session");
                    let row = u32::from(
                        content
                            .lookup_in(action_id, rd_core::content::EK_EACTION)
                            .unwrap_or_else(|| panic!("{action_id}"))
                            .index,
                    );
                    rd_core::intent::execute_action(
                        &mut session.state,
                        &content,
                        &cid_in(enemy),
                        row,
                        Some(cid_in("hero")),
                    )
                    .unwrap_or_else(|e| panic!("{action_id}: {e}"));
                    rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
                }
                let stacks = {
                    let session = slot().as_ref().expect("session");
                    session
                        .state
                        .combatant(&cid_in(enemy))
                        .map_or(0, |c| {
                            c.statuses()
                                .iter()
                                .filter(|s| s.definition_id.as_str() == *status)
                                .map(|s| s.stacks)
                                .sum::<i32>()
                        })
                };
                assert_eq!(stacks, expected, "A{ascension}: {action_id} -> {status}");
                take_session();
            }
        }

        // Fat Gremlin：A17 在 5 伤害 + 1 Weak 之外**再加** 1 Frail。
        for (ascension, frail) in [(16u8, 0), (17u8, 1)] {
            let session = build_session_at(22, "enc_gremlin_gang", 300, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            {
                let session = slot().as_mut().expect("session");
                let row = u32::from(
                    content
                        .lookup_in("fat_gremlin.smash", rd_core::content::EK_EACTION)
                        .expect("smash")
                        .index,
                );
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("fat_gremlin"),
                    row,
                    Some(cid_in("hero")),
                )
                .expect("smash");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let (weak, got_frail) = {
                let session = slot().as_ref().expect("session");
                let hero = session.state.combatant(&cid_in("hero")).expect("hero");
                let count = |name: &str| {
                    hero.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == name)
                        .map(|s| s.stacks)
                        .sum::<i32>()
                };
                (count("standard.weak"), count("standard.frail"))
            };
            assert_eq!(weak, 1, "A{ascension}: Smash always applies 1 Weak");
            assert_eq!(got_frail, frail, "A{ascension}: Frail only from A17");
            take_session();
        }
    }

    /// §327：`taskmaster.scouring_whip`'''


t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
assert 'fn the_three_a17_move_rows_take_effect_in_the_fight' not in t, 'patched'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS))
print('wasm: A17 rows test inserted')
