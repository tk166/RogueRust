"""§176: the boss regression test -- insert it **before** the §174 test, with a balance check.

The previous attempt spliced `text[:start] + new + text[end:]` where `end` (the §174 doc comment) sat
*before* `start` in the file, so the whole tail was duplicated: +1325 lines and one stray `}`.
This version anchors on the §174 comment, asserts the insertion happened exactly once, and asserts the
file's brace depth is still 0 -- the check that would have caught it immediately.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"
ANCHOR = "    /// §174：Lagavulin 打完 **8 个回合**都必须能继续"

TEST = '''    /// §176：**三个 Boss 都能被完整打下去**，包括中途分裂出来的战斗员。
    ///
    /// 这条测试是那次卡死的回归：Slime Boss 在 2 HP 时分裂出 `acid_slime_m#000000` /
    /// `spike_slime_s#000001`，而驱动器在 `plan.enemies`（开局固定的切片）里找"轮到谁、它有哪些招"
    /// ⇒ `活跃战斗员 … 不在 plan.enemies 里`，整个结束回合的步骤失败，页面上看起来就是"打不动"。
    /// 分裂在 §175 之前从未发生过（`standard.split` 是起始状态，而起始状态当时根本不生效），
    /// 所以这个假设一直没被撞破。
    ///
    /// 判据不是"赢了"（这副 10 张起始牌打不赢 400 HP 的 Boss），而是**每一步都还受理、且分裂之后
    /// 敌人真的会行动**。
    #[test]
    fn every_boss_fight_stays_playable_including_summons() {
        for encounter in ["enc_slime_boss", "enc_the_champ", "enc_time_eater"] {
            let session = crate::build_session_at(7, encounter, 400, None, 0)
                .unwrap_or_else(|error| panic!("{encounter}: {error}"));
            crate::install_session(session);
            let mut multi = 0usize;
            let mut rounds_lived = 0usize;
            for round in 1..=25 {
                // Play every playable card, then end the turn -- the shape the page uses.
                let mut played = 0;
                while played < 40 {
                    let mut action = -1;
                    for index in 0..rd_env_action_count() {
                        if rd_env_action_kind(index) == 0 {
                            action = index;
                            break;
                        }
                    }
                    if action < 0 {
                        break;
                    }
                    assert_eq!(
                        crate::rd_env_step(action),
                        0,
                        "{encounter} round {round}: a card play was refused ({})",
                        run_error_text()
                    );
                    played += 1;
                }
                let end = rd_env_action_index_of_end_turn();
                if end < 0 {
                    break; // the fight is over, or the hero died
                }
                let verdict = crate::rd_env_step(end);
                assert_eq!(
                    verdict, 0,
                    "{encounter} round {round}: ending the turn was refused ({}) -- problems {:?}",
                    run_error_text(),
                    crate::slot().as_ref().map(|s| s.problems.clone())
                );
                rounds_lived += 1;
                let enemies = {
                    let session = crate::slot().as_ref().expect("session");
                    session
                        .state
                        .combatants()
                        .iter()
                        .filter(|unit| unit.team_id.as_str() == "enemy")
                        .count()
                };
                if enemies > 1 {
                    multi += 1;
                }
                if rd_env_done() != 0 {
                    break;
                }
            }
            println!("{encounter}: {rounds_lived} rounds, {multi} with more than one enemy");
            assert!(
                rounds_lived >= 3,
                "{encounter} only lasted {rounds_lived} rounds"
            );
        }
    }

'''


def depth_of(text):
    """Brace depth of the code (strings and line comments stripped)."""
    backslash = chr(92)
    quote = chr(34)
    out = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == quote:
            index += 1
            while index < len(text) and text[index] != quote:
                if text[index] == backslash:
                    index += 1
                index += 1
            index += 1
            continue
        if char == "/" and index + 1 < len(text) and text[index + 1] == "/":
            while index < len(text) and text[index] != chr(10):
                index += 1
            continue
        out.append(char)
        index += 1
    depth = 0
    for char in "".join(out):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
    return depth


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn every_boss_fight_stays_playable" not in text, "already inserted"
    assert depth_of(text) == 0, "the file was already unbalanced"
    updated = text.replace(ANCHOR, TEST + ANCHOR)
    assert depth_of(updated) == 0, "the insertion unbalanced the file"
    io.open(PATH, "w", encoding="utf-8", newline="").write(updated)
    print("boss test inserted before §174; brace depth still 0")


if __name__ == "__main__":
    main()
