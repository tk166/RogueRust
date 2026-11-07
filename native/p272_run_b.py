"""§272 第二批：指纹、存档 v6、wasm（放行 `?` 战斗 + 观测保留位）、页面一行、内容两件。"""
import io

HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'
ARCH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
PANELS = 'D:/Vibe/sts-tui/web/ui_panels.js'
INDEX = 'D:/Vibe/sts-tui/web/index.html'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


HASH_OLD = r'''    writer
        .str("tea_set=")
        .u32(u32::from(state.tea_set_pending()))
        .str("\n");'''

HASH_NEW = r'''    writer
        .str("tea_set=")
        .u32(u32::from(state.tea_set_pending()))
        .str("\n");
    // §272：`?` 房的分流结果与 `tiny_chest` 的计数。
    // 结果**必须**进指纹：它决定"这一格开事件还是开一场战斗"，是两局之间真实的行为差异。
    writer
        .str("unknown_room=")
        .u32(u32::from(state.unknown_room() as u8))
        .str("\n");
    writer
        .str("tiny_chest=")
        .u32(u32::from(state.tiny_chest_rooms()))
        .str("\n");'''


def main():
    # ---- ① hash
    h = io.open(HASH, encoding='utf-8').read()
    h = patch(h, HASH_OLD, HASH_NEW, 'hash fields')
    io.open(HASH, 'w', encoding='utf-8', newline='\n').write(h)

    # ---- ② archive v6
    a = io.open(ARCH, encoding='utf-8').read()
    a = patch(a, '/// §271：4 → 5（`tea_set_pending`）。',
              '/// §272：5 → 6（`unknown_room` + `tiny_chest_rooms`）。\n'
              '/// §271：4 → 5（`tea_set_pending`）。', 'version doc')
    a = patch(a, 'const VERSION: u8 = 5;', 'const VERSION: u8 = 6;', 'version')
    a = patch(a, '''    let tea_set_pending = reader.byte()?;''',
              '''    let tea_set_pending = reader.byte()?;
    // §272
    let unknown_room = reader.byte()?;
    let tiny_chest_rooms = reader.byte()?;''', 'read')
    a = patch(a, '''    writer.byte(u8::from(state.tea_set_pending))?;''',
              '''    writer.byte(u8::from(state.tea_set_pending))?;
    // §272
    writer.byte(state.unknown_room as u8)?;
    writer.byte(state.tiny_chest_rooms)?;''', 'write')
    a = patch(a, '    restored.tea_set_pending = tea_set_pending != 0;',
              '''    restored.tea_set_pending = tea_set_pending != 0;
    // §272：容量是语义 —— 读到 5 种之外的值是**存档坏了**。
    restored.unknown_room = match unknown_room {
        0 => crate::state::UnknownRoom::Unresolved,
        1 => crate::state::UnknownRoom::Event,
        2 => crate::state::UnknownRoom::Monster,
        3 => crate::state::UnknownRoom::Shop,
        4 => crate::state::UnknownRoom::Treasure,
        _ => return Err(ArchiveError::BadField("unknown_room")),
    };
    if tiny_chest_rooms >= crate::state::TINY_CHEST_ROOMS {
        return Err(ArchiveError::BadField("tiny_chest_rooms"));
    }
    restored.tiny_chest_rooms = tiny_chest_rooms;''', 'restore')
    io.open(ARCH, 'w', encoding='utf-8', newline='\n').write(a)

    # ---- ③ wasm：`?` 房可以开一场战斗
    w = io.open(WASM, encoding='utf-8').read()
    w = patch(w, '''    // 1 = Combat, 2 = Elite, 7 = Boss (`run-layer.md` §7.2; the boss is floor 16, off the map).
    if kind != 1 && kind != 2 && kind != 7 {
        let message = std::format!("当前节点不是战斗（kind {kind}）");
        return fail(session, &message);
    }''',
              '''    // §272：`?` 房（kind 5）掷出 Monster 时也是一场**普通**战斗（这个项目里唯一会变成战斗的
    // 非战斗节点）。判据是 `unknown_room()` —— 不是"kind 是 5 就行"：事件、宝箱、商人都还是 5。
    let unknown_fight =
        kind == i32::from(rd_run::map::NodeKind::Unknown as u8)
            && session.state.unknown_room() == rd_run::state::UnknownRoom::Monster;
    // 1 = Combat, 2 = Elite, 7 = Boss (`run-layer.md` §7.2; the boss is floor 16, off the map).
    if kind != 1 && kind != 2 && kind != 7 && !unknown_fight {
        let message = std::format!("当前节点不是战斗（kind {kind}）");
        return fail(session, &message);
    }''', 'fight_begin kind gate')

    w = patch(w, '''    let base = match kind {
        2 => "Elite",
        7 => "Boss",
        _ => "Weak",
    };''',
              '''    // §272：`?` 房的战斗用本幕的**普通**池（wiki：`?` 房的怪物是普通遭遇）—— 也就是 `_` 那一支。
    let base = match kind {
        2 => "Elite",
        7 => "Boss",
        _ => "Weak",
    };''', 'fight_begin pool comment')

    # `rd_run_begin_node`：`?` 房只在**事件**时才去开事件
    w = patch(w, '''    if kind == rd_run::map::NodeKind::Unknown {''',
              '''    // §272：`?` 房先看它掷出了什么。只有 `Event` 才开事件；`Monster` 什么都不做（页面会显示
    // "开始战斗"，`fight_begin` 认这个组合）；`Shop` / `Treasure` 的 `pending` 已经由 `begin_node`
    // 摆好了（与商店/宝藏节点同一条路）。
    if kind == rd_run::map::NodeKind::Unknown
        && session.state.unknown_room() == rd_run::state::UnknownRoom::Event
    {''', 'begin_node event gate')

    # 观测：保留位 18 = `?` 房结果
    w = patch(w, '''        18 => 0, // reserved (`env-abi.md` §11.3)''',
              '''        // §272：`?` 房掷出了什么（`UnknownRoom` 的判别值；0 = 还没掷 / 不是 `?` 房）。
        // 这一格原来是保留位 —— 长度不变，所以页面索引不用动。
        18 => i32::from(state.unknown_room() as u8),''', 'observation 18')
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(w)

    # ---- ④ 页面：`?` 房里的战斗
    p = io.open(PANELS, encoding='utf-8').read()
    p = patch(p, '''    const name =
      s.kind === 7 ? `Boss · ${s.bossName}` : s.kind === 2 ? "精英节点（3 × Sentry）" : "战斗节点";''',
              '''    // §272：`?` 房掷出怪物时也是一场普通战斗（kind 仍是 5，靠 `unknownRoom === 2` 认出来）。
    const name =
      s.kind === 7
        ? `Boss · ${s.bossName}`
        : s.kind === 2
          ? "精英节点（3 × Sentry）"
          : s.kind === 5
            ? "? 房 · 普通战斗"
            : "战斗节点";''', 'panel name')
    p = patch(p, '''        if (s.kind === 1 || s.kind === 2 || s.kind === 7) return describeFight(s);''',
              '''        // §272：`?` 房（5）掷出怪物（`unknownRoom === 2`）时是战斗。
        if (s.kind === 1 || s.kind === 2 || s.kind === 7) return describeFight(s);
        if (s.kind === 5 && s.unknownRoom === 2) return describeFight(s);''', 'panel dispatch')
    io.open(PANELS, 'w', encoding='utf-8', newline='\n').write(p)
    print('hash + archive v6 + wasm + page')


main()
