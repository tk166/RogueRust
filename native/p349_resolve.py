"""§349 第二半：P2-A（`resolveScene`：基础场景 + 覆盖层**分开**）+ P2-B（快照保留 `bossId`）。

## P2-A：`classifyScene` 把两层合成一个 id

`SC-11a/11b` 是**模态覆盖层**，但 `classifyScene` 返回的是"第一个命中的 id" —— 于是
"奖励屏 + 遗物选牌欠账"只报 `SC-11a`，底下那一屏（`SC-04`）只能从别处重新推导。
DOM 面板"用覆盖层暂时替换正文"是合理权衡，但 3D 需要**复合**状态：

```ts
type SceneResolution = { baseScene, overlays[], unknownPending? }
```

⇒ 新增 `resolveScene(s)`，**保留** `classifyScene`（旧页面用它）。两者共用同一份 `RAW`，
所以判据不会漂。

## P2-B：`bossName` 过早变成显示名

`runSnapshot()` 直接把 Boss 的 **id** 交给 `displayName()`，于是下游只能拿到"格式化后的名字"，
不能按 id 绑定 3D 美术 / 音效 / 本地化。而 §0.5 那条原则是**内核给 id、显示层给名字** ——
快照本身应该两者都有。

⇒ 快照加 `bossId`（原样 id，没有就是空串），`bossName` 保留为**标签**（面板照旧）。
"""

import io

PANELS = 'web/ui_panels.js'
PAGE = 'web/index.html'
TEST = 'web/ui_test.mjs'


def sub(path, old, new, label, count=1):
    t = io.open(path, encoding='utf-8').read()
    n = t.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① resolveScene ─────────────────────────────────────────────────────────
sub(PANELS, '''  /// **所有**命中的场景 id（按优先级）。判据用它验"唯一命中"：多重命中会被顺序藏起来，
  /// 而那正是"表里排错一行"的形状。''',
    '''  /// **复合**状态：基础场景与覆盖层**分开**（§349，第十一轮 Review P2-A）。
  ///
  /// `classifyScene` 返回的是"第一个命中的 id"，所以"奖励屏 + 遗物选牌欠账"只报 `SC-11a`，
  /// 底下那一屏（`SC-04`）就丢了。DOM 面板"用覆盖层暂时替换正文"是合理权衡，但 3D 需要知道
  /// **两层都在**（覆盖层画在底屏之上）。
  ///
  /// | 字段 | 含义 |
  /// |---|---|
  /// | `base` | 第一个命中的**非覆盖层**场景；一条都没命中 ⇒ `"SC-??"` |
  /// | `overlays` | 命中的覆盖层（按优先级），可以为空、也可以是两个 |
  /// | `unknownPending` | 只在 `base === "SC-??"` 时有值：那个表外的 `pending` |
  function resolveScene(s) {
    const overlays = RAW.filter((entry) => entry.overlay && entry.test(s)).map((entry) => entry.id);
    const base = SCENES.find((entry) => !entry.overlay && entry.test(s));
    return {
      base: base ? base.id : "SC-??",
      overlays,
      unknownPending: base ? null : s.pending,
    };
  }

  /// **所有**命中的场景 id（按优先级）。判据用它验"唯一命中"：多重命中会被顺序藏起来，
  /// 而那正是"表里排错一行"的形状。''', 'resolveScene')

sub(PANELS, '''    SCENES, classifyScene, scenesMatching, isOverlay, preFight, mapExhausted,''',
    '''    SCENES, classifyScene, resolveScene, scenesMatching, isOverlay, preFight, mapExhausted,''',
    'export resolveScene')

# ── ② 快照：bossId + bossName（标签）──────────────────────────────────────
sub(PAGE, '''    // §345（缺口 G5）：本幕 Boss 的**敌人 id**（`slime_boss` / `the_guardian` / …）经显示层。
    // 原来是写死的 "Slime Boss" —— 第二、三幕会显示错的 Boss 名。
    bossName: RD_UI.displayName(
      readText(() => ex.rd_run_boss_id_len(), (ptr) => ex.rd_run_boss_id_into(ptr)),
      ""
    ),''',
    '''    // §345（缺口 G5）：本幕 Boss 的**敌人 id**（`slime_boss` / …）。
    // §349（P2-B）：快照**两个都留** —— `bossId` 给 3D/美术按身份绑定（图标、音效、本地化），
    // `bossName` 只是**标签**。只留名字的话，下游没法可靠地反查身份（§0.5 的原则）。
    bossId: readText(() => ex.rd_run_boss_id_len(), (ptr) => ex.rd_run_boss_id_into(ptr)),
    bossName: RD_UI.displayName(
      readText(() => ex.rd_run_boss_id_len(), (ptr) => ex.rd_run_boss_id_into(ptr)),
      ""
    ),''', 'bossId')

# ── ③ 判据：resolveScene 的两层 ────────────────────────────────────────────
sub(TEST, '''  // §348（P2-2）：**表外的 `pending` 必须显性化**，不能静默落地图。''',
    '''  // §349（P2-A）：`resolveScene` 把**基础场景**与**覆盖层**分开。
  // "奖励屏 + 遗物选牌欠账"必须同时表达两层 —— `classifyScene` 只报覆盖层，底屏就丢了。
  {
    const layered = { ...BASE, pending: 4, pickupPicks: 2,
      rewardCards: [{ slot: 0, id: "anger", title: "Anger", chip: "" }] };
    const resolved = P.resolveScene(layered);
    if (resolved.base !== "SC-04") fail(`layered base must be SC-04, got ${resolved.base}`);
    if (JSON.stringify(resolved.overlays) !== JSON.stringify(["SC-11a"])) {
      fail(`layered overlays must be ["SC-11a"], got ${JSON.stringify(resolved.overlays)}`);
    }
    if (resolved.unknownPending !== null) fail("a known base must not report unknownPending");
    // 而 `classifyScene`（旧页面用）仍然报覆盖层 —— 两者不矛盾，只是回答不同的问题。
    if (P.classifyScene(layered) !== "SC-11a") fail("classifyScene must keep returning the overlay");

    // 无覆盖层时：base 就是它自己，overlays 为空。
    const plain = P.resolveScene({ ...BASE, kind: 4, actionCount: 2 });
    if (plain.base !== "SC-02" || plain.overlays.length !== 0) {
      fail(`plain scene: ${JSON.stringify(plain)}`);
    }

    // 表外 pending：base 是 SC-??，并把那个值带出来。
    const unknown = P.resolveScene({ ...BASE, pending: 99 });
    if (unknown.base !== "SC-??" || unknown.unknownPending !== 99) {
      fail(`unknown pending: ${JSON.stringify(unknown)}`);
    }
  }

  // §348（P2-2）：**表外的 `pending` 必须显性化**，不能静默落地图。''',
    'resolveScene test')

sub(TEST, '''console.log(`  unknown pending   pending=99 => SC-?? with an explicit panel (not the map)`);''',
    '''console.log(`  unknown pending   pending=99 => SC-?? with an explicit panel (not the map)`);
console.log(`  resolveScene      base scene + overlays separately (reward screen + relic pick)`);''',
    'log line')
print('§349: resolveScene + bossId')
