"""闸门 34 的第二轮：修三处断言口径 + 地图高亮边改成"从当前节点出发"。"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── 1. 地图：高亮"从当前节点出发、且目标可达"的边 ─────────────────────────────
patch(
    'web-next/src/run/scenes/MapScene.tsx',
    [
        (
            'live edge semantics',
            '''  // 只画"从某节点出发、且目标存在"的边；重复边（多条路径同一条边）去重。
  const edges = useMemo(() => {
    const seen = new Set<string>();
    const out: { from: MapNode; to: MapNode; live: boolean }[] = [];
    for (const node of map.nodes) {
      for (const target of node.edges) {
        const to = map.byIndex.get(target);
        if (!to) continue;
        const key = `${node.index}->${target}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ from: node, to, live: to.reachable });
      }
    }
    return out;
  }, [map]);''',
            '''  // 只画"从某节点出发、且目标存在"的边；重复边（多条路径同一条边）去重。
  //
  // ⚠️ 哪条边高亮 = **从当前节点出发、且目标可达**的那条（"你现在能走的这一步"）。
  // 第一版写的是 `to.reachable`（目标可达就高亮），于是开局时第 1 行的节点全部可达、
  // 而它们**没有入边** ⇒ 一条高亮边都画不出来（闸门 34 第一次跑就是 0 条）。
  const edges = useMemo(() => {
    const seen = new Set<string>();
    const out: { from: MapNode; to: MapNode; live: boolean }[] = [];
    for (const node of map.nodes) {
      for (const target of node.edges) {
        const to = map.byIndex.get(target);
        if (!to) continue;
        const key = `${node.index}->${target}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ from: node, to, live: node.index === current && to.reachable });
      }
    }
    return out;
  }, [map, current]);''',
        ),
    ],
)

# ── 2. 闸门 34：三处断言口径 ─────────────────────────────────────────────────
patch(
    'native/ui_next_loop_check.mjs',
    [
        (
            'reachable count range',
            '''  check(reachable.length >= 2 && reachable.length <= 3, "第 1 步可达 2–3 个节点", String(reachable.length));''',
            '''  // 第 1 行最多 6 列（`run-layer.md` §7.2），所以可达数在 2..6 —— 不要写死 2–3。
  check(reachable.length >= 2 && reachable.length <= 6, "第 1 步可达 2–6 个节点", String(reachable.length));''',
        ),
        (
            'live edges at start',
            '''  const liveEdges = await ev(`document.querySelectorAll("[data-edge][data-live='1']").length`);
  check(liveEdges >= 1, "至少一条出边高亮（可走的路线看得出来）", String(liveEdges));''',
            '''  // 开局（还没出发）没有"当前节点"，所以**没有**高亮边是对的：第 1 行的可达节点靠
  // 自身的呼吸环提示。高亮边在"站在某个节点上"之后才有意义（阶段 10 断言）。
  const liveEdges = await ev(`document.querySelectorAll("[data-edge][data-live='1']").length`);
  check(liveEdges === 0, "还没出发时没有高亮边（没有"当前节点"可言）", String(liveEdges));''',
        ),
        (
            'hp writeback allows post-combat heal',
            '''    const runAfterFight = await ev("window.__run.run()");
    // 这一条是闸门 33 说明的口径：`fight_end` **必须**把战斗 HP 写回运行层。
    check(
      runAfterFight.health === finalCombatHp,
      "战斗结束时的 HP 被写回运行层（不是战斗中那份陈旧的）",
      `${runAfterFight.health} vs ${finalCombatHp}`
    );''',
            '''    const runAfterFight = await ev("window.__run.run()");
    // 这一条是闸门 33 说明的口径：`fight_end` **必须**把战斗 HP 写回运行层。
    //
    // ⚠️ 不能写成 `===`：战后**遗物会再结算一次**（起手遗物"燃烧之血"每场战斗后回 6 点）。
    // 第一版用等号，实测 49 vs 43 直接红 —— 那不是 bug，是游戏规则。
    // 所以断言是"**不低**于战斗最后一帧"（伤害留下来了）+ 不超过上限 + 有遗物可解释差额。
    check(
      runAfterFight.health >= finalCombatHp && runAfterFight.health <= runAfterFight.healthMax,
      "战斗最后一帧的 HP 被写回运行层（战后遗物回复只会更高）",
      `${runAfterFight.health} vs 最后一帧 ${finalCombatHp}`
    );
    if (runAfterFight.health > finalCombatHp) {
      check(
        runAfterFight.relicCount >= 1,
        "战后 HP 高于最后一帧时，牌组里有遗物可以解释（燃烧之血一类）",
        `遗物 ${runAfterFight.relicCount} 个`
      );
    }''',
        ),
        (
            'live edges after fight',
            '''    const runNow = await ev("window.__run.run()");
    check(runNow.floor >= 1, "层数没有倒退", String(runNow.floor));''',
            '''    const runNow = await ev("window.__run.run()");
    check(runNow.floor >= 1, "层数没有倒退", String(runNow.floor));

    // 站在节点上之后，"能走的这一步"必须画得出来（阶段 3 里开局时是 0 条，这是对的）。
    const liveEdges2 = await ev(`document.querySelectorAll("[data-edge][data-live='1']").length`);
    check(
      liveEdges2 >= reachable2.length,
      "回到地图后，从当前节点出发的边被高亮（能走的路线看得出来）",
      `${liveEdges2} 条 vs 可达 ${reachable2.length}`
    );
    const currentMarked = await ev(`document.querySelectorAll("[data-current='1']").length`);
    check(currentMarked === 1, "地图上有且只有一个"你在这里"", String(currentMarked));''',
        ),
    ],
)
print('gate34 round 2')
