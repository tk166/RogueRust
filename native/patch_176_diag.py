"""§176: find the `StepThrew(Script)` that appears once enemy starting statuses are live.

`StepCause::Script` is `BattleError::Deck(_) | BattleError::Play(_)` -- a deck/play error, not a
program error. It shows up on the **end-turn** step of a Slime Boss fight (the boss now actually
splits, because `standard.split` / `standard.phase_split` are applied for the first time).

This adds a temporary diagnostic that plays every playable card and then ends the turn, printing the
outcome of each round: verdict, hero HP, the step's problems and the kernel's error text. Whatever
that prints names the bug.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// §174：Lagavulin 打完 **8 个回合**都必须能继续"""

TEST = '''    /// §176 诊断：Slime Boss 逐回合打，打印每一步的 problems 与内核错误码。
    ///
    /// 用来定位"起始状态生效之后、回合结束那一步抛 `StepThrew(Script)`"。`Script` 是
    /// `BattleError::Deck(_) | BattleError::Play(_)` —— **不是**程序错误，所以它不是敌人动作。
    #[test]
    fn diag_slime_boss_rounds() {
        let session = crate::build_session_at(7, "enc_slime_boss", 400, None, 0)
            .expect("the slime boss encounter");
        crate::install_session(session);
        for round in 1..=12 {
            let end = rd_env_action_index_of_end_turn();
            if end < 0 {
                println!(
                    "round {round}: NO ACTION · active {:?} phase {:?}",
                    crate::slot().as_ref().and_then(|s| s.state.active_combatant_id),
                    crate::slot().as_ref().map(|s| s.state.turn_phase)
                );
                break;
            }
            loop {
                let mut action = -1;
                for i in 0..rd_env_action_count() {
                    if rd_env_action_kind(i) == 0 {
                        action = i;
                        break;
                    }
                }
                if action < 0 {
                    break;
                }
                if crate::rd_env_step(action) != 0 {
                    break;
                }
            }
            // The end-turn index is only valid **now** -- playing cards rebuilt the table, and the
            // index captured before the loop is stale (`rd_env_step` then answers -1, which looks
            // exactly like a kernel refusal).
            let verdict = match rd_env_action_index_of_end_turn() {
                end if end >= 0 => crate::rd_env_step(end),
                _ => {
                    println!("round {round}: NO END TURN after playing");
                    break;
                }
            };
            let (problems, err, hp, enemies) = {
                let session = crate::slot().as_ref().expect("session");
                let enemies = session
                    .state
                    .combatants()
                    .iter()
                    .filter(|c| c.team_id.as_str() == "enemy")
                    .map(|c| std::format!("{}={}", c.id.as_str(), c.health_current))
                    .collect::<Vec<_>>();
                (
                    session.problems.join(","),
                    session.error.clone(),
                    session
                        .state
                        .combatant(&rd_core::state::CombatantId::new("hero").unwrap())
                        .map_or(0, |c| c.health_current),
                    enemies,
                )
            };
            println!(
                "round {round}: verdict {verdict} hp {hp} problems [{problems}] err [{err}] \\
                 enemies {enemies:?}"
            );
            if verdict != 0 {
                break;
            }
        }
    }

''' + ANCHOR


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn diag_slime_boss_rounds" not in text
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, TEST))
    print("boss diagnostic added")


if __name__ == "__main__":
    main()
