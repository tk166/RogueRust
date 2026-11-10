"""§321 wasm：三个接线。

1. `RunFacts.floor` 填**真值**（`rd-core` 那边已经加了字段与 `floor` 原子）。
2. 事件的战斗档位新增 `3` = Boss（`mind_bloom` 的 `[I am War]`）：池子与 `FightKind` 都要认。
3. `EventEffect::UpgradeAll` 的效果码（页面不需要它 → `-1`；数量 0）。
"""

import io

WASM = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(WASM, encoding='utf-8').read()

# ── 1. facts：floor ──────────────────────────────────────────────────────────────
t = sub(t, """    rd_core::run_expr::RunFacts {
        gold: session.state.gold(),""",
        """    rd_core::run_expr::RunFacts {
        // §321：本幕内的层号（`mind_bloom` 的第三个选项按它换）。
        floor: session.state.floor(),
        gold: session.state.gold(),""",
        'facts floor')

# ── 2. 事件战斗的 boss 档位 ──────────────────────────────────────────────────────
t = sub(t, """    let base = match (kind, event_fight) {
        // §286：事件的伏击是**精英**，即使节点本身是 `?`。
        (_, 2) => "Elite",
        (2, _) => "Elite",
        (7, _) => "Boss",
        _ => "Weak",
    };""",
        """    let base = match (kind, event_fight) {
        // §286：事件的伏击是**精英**，即使节点本身是 `?`。
        (_, 2) => "Elite",
        // §321：`mind_bloom` 的 `[I am War]` 是"打一场**第 1 幕 Boss**" —— 事件的 Boss 档位。
        // ⚠️ 这一支必须**排在** `(2, _)`/`(_, 2)` 之后、`_` 之前：`event_fight` 比节点更具体。
        (_, 3) => "Boss",
        (2, _) => "Elite",
        (7, _) => "Boss",
        _ => "Weak",
    };""",
        'boss pool base')

t = sub(t, """    let fight_kind = match kind {
        2 => rd_run::state::FightKind::Elite,
        7 => rd_run::state::FightKind::Boss,
        _ => rd_run::state::FightKind::Normal,
    };""",
        """    // §321：事件的 Boss 档位（`event_fight == 3`）同样要报 Boss —— 否则
    // `pantograph` / `slavers_collar` 在 Mind Bloom 的 `[I am War]` 里不生效，而 wiki 明说
    // "Pantograph and Slaver's Collar will work as if it is another Boss encounter"。
    let fight_kind = match (kind, event_fight) {
        (_, 3) => rd_run::state::FightKind::Boss,
        (2, _) => rd_run::state::FightKind::Elite,
        (7, _) => rd_run::state::FightKind::Boss,
        _ => rd_run::state::FightKind::Normal,
    };""",
        'fight kind boss')

# ── 3. 效果码 ───────────────────────────────────────────────────────────────────
t = sub(t, """        | EventEffect::OfferCards(_, _) => -1,""",
        """        | EventEffect::OfferCards(_, _)
        // §321：`upgrade_all` 的落点是**牌组每一张**，页面上没有效果码能画它（与 `card:<id>`
        // 同一条规矩：真正的信息在内容字符串里）。
        | EventEffect::UpgradeAll => -1,""",
        'effect code upgrade_all')

t = sub(t, """        // §319：类型不是"数量"。
        | EventEffect::RemoveCardRandom(_)""",
        """        // §319：类型不是"数量"。
        | EventEffect::UpgradeAll
        | EventEffect::RemoveCardRandom(_)""",
        'effect amount upgrade_all')

io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-wasm patched')
