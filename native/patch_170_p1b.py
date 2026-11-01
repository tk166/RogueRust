"""P1-1 wiring: keep the deck borrow inside a block so the rollback can still touch the session.

`counts`/`entries` borrow the deck as `&'static str` (the ABI's `DeckEntry<'static>`), and `RunState`
lives inside the session -- so a `&mut session` for the rollback conflicts *only* while that borrow is
live. The fallible part therefore computes an `Option<String>` inside a block, and the rollback
happens after the block, where the borrow is dead.

That is not a workaround for a real conflict: "build, then commit" is the shape the review asked for,
and the block is what makes the borrow checker enforce it.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

OLD = """    match crate::build_session_at(
        fight_seed,
        encounters[pick],
        max_health,
        Some(entries),
        enemy_health_percent,
    ) {
        Ok(combat) => {
            crate::install_session(combat);
            // The fight is built at the hero's maximum; a run usually enters wounded.
            crate::set_combat_hero_health(session.state.health());
            // ... and then the relics get their turn. A failure here is a **content** problem
            // (a relic promising Block the kernel cannot write), so it is reported, not ignored.
            if let Err(message) = apply_combat_bonus(bonus) {
                // §170 `P1-1`: 这是唯一一条"装好战斗之后才失败"的路 —— 撤掉它，别留下一个
                // 没有遗物加成的半初始化战斗。
                crate::take_session();
                return fail_begin(session, before, &message);
            }
            // **提交点**：走到这里才是"这一场开始了"。
            session.elite_fight = kind == 2;
            session.boss_fight = kind == 7;
            session.in_fight = true;
            0
        }
        Err(message) => fail_begin(session, before, &message),
    }
}"""

NEW = """    // 可失败段收在一个块里：`entries` 借着 `state`（`DeckEntry<'static>` 的要求），块一结束借用就死，
    // 后面才允许拿整个 `session` 去回滚。这不是绕过借用检查，而是让借用检查器**替我**保证
    // "先建、后提交"。
    let failure: Option<std::string::String> = {
        match crate::build_session_at(
            fight_seed,
            encounters[pick],
            max_health,
            Some(entries),
            enemy_health_percent,
        ) {
            Ok(combat) => {
                crate::install_session(combat);
                // The fight is built at the hero's maximum; a run usually enters wounded.
                crate::set_combat_hero_health(session.state.health());
                // ... and then the relics get their turn. A failure here is a **content** problem
                // (a relic promising Block the kernel cannot write), so it is reported, not ignored.
                apply_combat_bonus(bonus).err()
            }
            Err(message) => Some(message),
        }
    };
    if let Some(message) = failure {
        // §170 `P1-1`: 失败的这一次必须**什么都没改** —— 连"装好了战斗之后才在遗物加成一环失败"
        // 的那半场也一起撤掉（`take_session` 在没有会话时是 no-op）。
        crate::take_session();
        return fail_begin(session, before, &message);
    }
    // **提交点**：走到这里才是"这一场开始了"。
    session.elite_fight = kind == 2;
    session.boss_fight = kind == 7;
    session.in_fight = true;
    0
}"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(OLD) == 1, text.count(OLD)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(OLD, NEW))
    print("P1-1: build inside a block, commit after it")


if __name__ == "__main__":
    main()
