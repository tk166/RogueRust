"""P3 的第一轮实测修正：三个返回码/判据 bug + 战斗屏的 data-scene + 奖励标题。"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── 1. scene.ts：SC-03 必须要求"这一格还没结算" ────────────────────────────────
patch(
    'web-next/src/run/scene.ts',
    [
        (
            'input nodeResolved',
            '''  readonly nodeKind: number;
  readonly unknownRoom: UnknownRoom;''',
            '''  readonly nodeKind: number;
  /**
   * `rd_run_node_resolved() == 1`：这一格**已经结算过**（打完/开完/离开）。
   *
   * ⚠️ 这是 `SC-03` 与 `SC-02` 的分界线，第一版漏了它：领完奖励后 `pending` 回到 0，
   * 而脚下那格的 `kind` 仍然是 `Combat` ⇒ 判成"战斗前"，界面把**已经打完的格子**又画成
   * "进入战斗"，点下去内核拒绝。判据必须是"这一格还在等我"而不是"这一格是战斗"。
   */
  readonly nodeResolved: boolean;
  readonly unknownRoom: UnknownRoom;''',
        ),
        (
            'preCombat requires unresolved',
            '''  // 14. 站在战斗节点上但还没开打（`?` 房只有掷出"怪物"才算）。
  const fightHere =
    input.nodeKind === NODE_KIND.combat ||''',
            '''  // 14. 站在战斗节点上但还没开打（`?` 房只有掷出"怪物"才算）。
  //     ⚠️ `nodeResolved === false` 是判据的一半：打完的格子 `kind` 仍然是 `Combat`，
  //     少了这一条，领完奖励会回到"战斗前"（点下去被内核拒绝）。
  const fightHere =
    !input.nodeResolved &&
    (input.nodeKind === NODE_KIND.combat ||''',
        ),
        (
            'fightHere closing paren',
            '''    (input.nodeKind === NODE_KIND.unknown && input.unknownRoom === UNKNOWN_ROOM.monster) ||
    input.eventFight > 0;''',
            '''      (input.nodeKind === NODE_KIND.unknown && input.unknownRoom === UNKNOWN_ROOM.monster) ||
      input.eventFight > 0);''',
        ),
    ],
)

# ── 2. RunStore：fight_end / begin_node 的返回码 + nodeResolved + 对账口径 ───────
patch(
    'web-next/src/run/RunStore.ts',
    [
        (
            'scene input nodeResolved',
            '''      nodeKind: rawExtra.nodeKind,
      unknownRoom: (run?.unknownRoom ?? 0) as SceneInput["unknownRoom"],''',
            '''      nodeKind: rawExtra.nodeKind,
      nodeResolved: rawExtra.nodeResolved === 1,
      unknownRoom: (run?.unknownRoom ?? 0) as SceneInput["unknownRoom"],''',
        ),
        (
            'fightEnd return code',
            '''  /** 战斗结束 → 让运行层生成奖励屏（**这一步才会**有 `pending 4`）。 */
  fightEnd(): number {
    const code = this.host.fightEnd();
    this.note(code === 0 ? "战斗结束" : `战斗结算失败（code ${code}）`, code === 0 ? "good" : "bad");
    this.refresh();
    return code;
  }''',
            '''  /**
   * 战斗结束 → 让运行层生成奖励屏（**这一步才会**有 `pending 4`）。
   *
   * ⚠️ `rd_run_fight_end()` 返回的是**战斗结果**（`1` 胜利 / `2` 战败 …），**不是** `0 = 成功`。
   * 第一版拿 `code === 0` 判成功，于是每一场胜利都被记成"战斗结算失败（code 1）"。
   */
  fightEnd(): number {
    const code = this.host.fightEnd();
    const ok = code >= 1;
    this.note(
      ok ? `战斗结束：${code === 1 ? "胜利" : code === 2 ? "战败" : `结果 ${code}`}` : `战斗结算失败（code ${code}）`,
      ok ? "good" : "bad"
    );
    this.refresh();
    return code;
  }''',
        ),
        (
            'beginNode return code',
            '''  /** 结算脚下这个节点（篝火/宝箱/商店/事件会进各自的待决屏；战斗节点什么也不做）。 */
  beginNode(): number {
    const kind = this.host.beginNode();
    this.note(`进入节点：${nodeKindLabel(kind)}`, "info");
    this.refresh();
    return kind;
  }''',
            '''  /**
   * 结算脚下这个节点（篝火/宝箱/商店/事件会进各自的待决屏；战斗节点什么也不做）。
   *
   * ⚠️ `rd_run_begin_node()` 返回 **`0` = 已结算 / `-2` = 拒绝**，**不是**节点 kind。
   * 第一版把它当 kind 打日志，于是每一格都写成"进入节点：未分配"。
   */
  beginNode(): number {
    const code = this.host.beginNode();
    this.note(code === 0 ? "这一格已结算" : `这一格结算被拒绝（code ${code}）`, code === 0 ? "info" : "bad");
    this.refresh();
    return code;
  }''',
        ),
        (
            'enterNode begin log',
            '''      const kind = this.host.beginNode();
      if (kind < 0) this.note(`这一格结算失败（kind ${kind}）`, "bad");
      else this.note(`进入节点：${nodeKindLabel(kind)}`, "info");''',
            '''      const code = this.host.beginNode();
      if (code !== 0) this.note(`这一格结算失败（code ${code}）`, "bad");''',
        ),
        (
            'reconcile hp only outside fight',
            '''    if (combat) {
      if (combat.hero.hp !== run.health) {
        bad.push(`战斗 HP ${combat.hero.hp} ≠ 运行层 HP ${run.health}`);
      }
      if (combat.hero.hpMax !== run.healthMax) {
        bad.push(`战斗上限 ${combat.hero.hpMax} ≠ 运行层上限 ${run.healthMax}`);
      }
    }''',
            '''    if (combat) {
      // ⚠️ **战斗内**运行层的 HP 是**故意**不跟的：战斗结算（`end_of_combat`）才写回，
      // 所以战斗中拿两边比会把每一场战斗都判成违约（第一版就是这么红的：
      // "战斗 HP 43 ≠ 运行层 HP 66"）。战斗中只比上限（它不会因为受伤而变）。
      // 战斗后的"写回正确"由闸门 34 用"最后一帧战斗 HP == 战后运行层 HP"钉住。
      if (input.inFight) {
        if (combat.hero.hpMax !== run.healthMax) {
          bad.push(`战斗上限 ${combat.hero.hpMax} ≠ 运行层上限 ${run.healthMax}`);
        }
      } else if (combat.hero.hp !== run.health) {
        bad.push(`战斗 HP ${combat.hero.hp} ≠ 运行层 HP ${run.health}`);
      }
    }''',
        ),
    ],
)

# ── 3. CombatScreen：给战斗屏一个 data-scene 根（闸门用它证明"画出来的==算出来的"）──
patch(
    'web-next/src/combat/CombatScreen.tsx',
    [
        (
            'data-scene wrapper',
            '''  return (
    <div className="app">
      <Canvas''',
            '''  return (
    // `data-scene="SC-03b"`：闸门 34 用它断言"画出来的那一屏 == 算出来的那一屏"。
    // 战斗屏是唯一一个**不**由 `run/scenes/*` 画的场景（3D 那套在 P1/P2 已经建好），
    // 所以这个标记必须由它自己打。
    <div className="app" data-scene="SC-03b">
      <Canvas''',
        ),
    ],
)

# ── 4. RewardScene：中文名优先 + 修正"候选表不变"的注释 ─────────────────────────
patch(
    'web-next/src/run/scenes/RewardScene.tsx',
    [
        (
            'reward comment',
            '''// ⚠️ 实测：拿一张之后**候选表不变**（内核允许继续拿同屏其他牌），所以"拿完就关屏"是错的 ——
// 关屏只能由 `skip_reward` 做（它的语义就是"我领完了"）。这条是闸门 34 的断言之一。''',
            '''// ⚠️ 实测：拿一张之后**候选表清空**（内核把整排牌都收走了，与 StS 一致）。所以界面不能
// 自己"标记拿过的那张"，只能重读；关屏仍然由 `skip_reward` 做（它的语义是"我领完了"，
// 药水/遗物还能继续拿）。这条是闸门 34 的断言之一。''',
        ),
        (
            'reward card title i18n first',
            '''            <span className="reward-card-title">{card.title || displayName("cards", card.id)}</span>''',
            '''            {/*
              ⚠️ 中文名**优先用 i18n**：内核的 `reward_card_title` 是 `CARD.NameKey`（英文
              `Spot Weakness`），直接显示会让中文界面里混进英文牌名。
            */}
            <span className="reward-card-title">{displayName("cards", card.id) || card.title}</span>''',
        ),
    ],
)
print('all patches applied')
