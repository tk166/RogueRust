"""P1-1 + P1-2: `fight_begin` becomes a transaction, and refuses a second start.

P1-1 (found by external review, verified): the function set `elite_fight` / `boss_fight` / `in_fight`
**before** six fallible steps (the act's encounter pool, an empty pool, the encounter pick, the combat
seed draw, `build_session_at`, and `apply_combat_bonus`). On the last one it had *already* installed a
combat session, so it returned `-2` with a half-initialised fight in the slot and `in_fight` stuck
true. A stuck `in_fight` is not cosmetic: `rd_run_archive_fill` refuses while it is set, so the
player loses the ability to archive **with no fight to finish** -- the same class as §164.3.

P1-2: nothing rejected a second `fight_begin` while a fight was running. During a fight the node is
unresolved (`node_resolved()` only turns true at `fight_end`), so the "this node already paid" check
let it through: it re-rolled the encounter (burning a `Combat` draw), leaked another deck slice, and
`install_session` **overwrote** the slot -- silently discarding the fight in progress. That is also a
re-roll exploit: stand on a combat node and press 开打 until you like the encounter.

Fix:
  * the flags are written at the **commit** point, after everything that can fail;
  * `RunState` is `Copy`, so a guard takes a whole-state snapshot and restores it on any failure --
    "refused means not one byte changed", including the RNG counters the pick consumed;
  * a failure after `install_session` also drops that session;
  * the entry refuses when `in_fight` is already set.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

OLD_ENTRY = """    // `fight_begin` 会写 `last_encounter`（进指纹），所以它也必须被记录 —— 否则上一条记录的
    // "调用之后的哈希"会把它的效果算进去，而回放里没有人做这件事（§163 踩过：第 4 步就对不上）。
    session.log(K_FIGHT_BEGIN, -1, -1, "");"""

NEW_ENTRY = """    // `fight_begin` 会写 `last_encounter`（进指纹），所以它也必须被记录 —— 否则上一条记录的
    // "调用之后的哈希"会把它的效果算进去，而回放里没有人做这件事（§163 踩过：第 4 步就对不上）。
    session.log(K_FIGHT_BEGIN, -1, -1, "");
    // §170 `P1-2`: 一场没打完就不许再开一场。战斗中 `node_resolved()` 仍是 false（要到 `fight_end`
    // 才结算），所以下面那句"这个节点已经结算过了"**放行**重复调用 —— 而重复调用会重新选遭遇
    // （烧掉一个 `Combat` 随机数）、再 `Box::leak` 一份牌组、并且 `install_session` **覆盖**掉
    // 正在打的那一场。站在战斗节点上反复按"开打"就能重摇遭遇。
    if session.in_fight {
        return fail(session, "这一场已经开始了：先打完它，或者重开一局");
    }"""

OLD_FLAGS = """    session.elite_fight = kind == 2;
    session.boss_fight = kind == 7;
    session.in_fight = true;
    // **The act decides the pool**"""

NEW_FLAGS = """    // §170 `P1-1`: 三个标记**不在这里**写。下面每一步都可能失败（池子缺、池子空、选遭遇、摇种子、
    // 建战斗、遗物加成），而 `in_fight` 卡在 true 的后果不是审美问题：`rd_run_archive_fill` 会一直
    // 拒绝存档，而玩家**根本没有一场仗可以打完**。它们在**提交点**统一写，见函数尾部。
    //
    // 原子性的判据用 `RunState: Copy` 的整结构体快照：任何失败都回到进函数那一刻，
    // 连"选遭遇已经消耗的随机数"也一起还回去（`RunState` 的 `rng` 是字段）。
    let before = session.state;
    // **The act decides the pool**"""

OLD_TAIL = """    match crate::build_session_at(
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
                session.error.clear();
                session.error.push_str(&message);
                return -2;
            }
            0
        }
        Err(message) => {
            session.error.clear();
            session.error.push_str(&message);
            -2
        }
    }
}"""

NEW_TAIL = """    match crate::build_session_at(
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
}

/// §170 `P1-1`: 一次失败的 `fight_begin` 必须**什么都没改**。
///
/// 恢复整局（`RunState` 是 `Copy`，所以连随机流计数一起回去）、清掉三个战斗标记、丢弃可能已经装上的
/// 战斗会话，然后写错误。判据是"拒绝 ⇒ 一个字节都不改"，与 `archive::restore` 同一条纪律。
fn fail_begin(session: &mut RunSession, before: rd_run::state::RunState, message: &str) -> i32 {
    session.state = before;
    session.elite_fight = false;
    session.boss_fight = false;
    session.in_fight = false;
    session.error.clear();
    session.error.push_str(message);
    -2
}"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in [(OLD_ENTRY, NEW_ENTRY), (OLD_FLAGS, NEW_FLAGS), (OLD_TAIL, NEW_TAIL)]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("P1-1/P1-2: transactional begin + re-entry refusal")


if __name__ == "__main__":
    main()
