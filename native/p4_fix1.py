"""P4 修正 1：宝箱"打开即结束"（改战利品横幅）+ 旅程策略避开精英。"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── 1. RunStore：lastLoot + openChest 记增量 ────────────────────────────────
patch(
    'web-next/src/run/RunStore.ts',
    [
        (
            'state lastLoot',
            '''  /** 宝箱（`pending == 3`）：打开前后的增量。 */''',
            '''  /**
   * 刚刚拿到的东西（宝箱/挖宝）。
   *
   * ⚠️ 为什么需要它：`rd_run_open_chest()` 的语义是**打开即结束**（相位直接归 0），
   * 所以"已打开的宝箱"不是一个可停留的屏。第一版按"打开 → 看战利品 → 离开"设计，
   * 结果点完打开相位就没了，界面还在等一个永远不会来的"离开"按钮。
   * 现在把增量记在这里，由外壳画一条横幅（可关），比编一个假屏诚实。
   */
  readonly lastLoot: { readonly gold: number; readonly relic: string; readonly source: string } | null;
  /** 宝箱（`pending == 3`）：打开前后的增量。 */''',
        ),
        (
            'state lastLoot init',
            '''      chest: { opened: false, goldGained: 0, relicGained: "" },''',
            '''      chest: { opened: false, goldGained: 0, relicGained: "" },
      lastLoot: null,''',
        ),
        (
            'keep lastLoot in refresh',
            '''      chest: this.readChest(pending, raw.exists),''',
            '''      chest: this.readChest(pending, raw.exists),
      // `lastLoot` 由动作写入、由玩家关掉；`refresh()` 不碰它（否则下一帧就消失了）。
      lastLoot: this.state.lastLoot,''',
        ),
        (
            'openChest captures delta',
            '''  openChest(): number {
    const code = this.host.openChest();
    if (code === 0) this.chestOpened = true;
    this.note(code === 0 ? "打开宝箱" : `打开宝箱失败（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }''',
            '''  /**
   * 打开宝箱。**打开即结束**（相位归 0），所以这里把增量记进 `lastLoot`。
   */
  openChest(): number {
    const before = decodeRun(this.host.runObservation());
    const relicsBefore = this.host.relicIds();
    const code = this.host.openChest();
    if (code === 0) {
      const after = decodeRun(this.host.runObservation());
      const relicsAfter = this.host.relicIds();
      const fresh = relicsAfter.filter((id) => !relicsBefore.includes(id));
      this.lastLoot = {
        gold: Math.max(0, after.gold - before.gold),
        relic: fresh[0] ?? "",
        source: "宝箱",
      };
      this.note(
        `打开宝箱：金币 +${this.lastLoot.gold}${this.lastLoot.relic ? ` · 遗物 ${this.lastLoot.relic}` : ""}`,
        "good"
      );
    } else {
      this.note(`打开宝箱失败（code ${code}）`, "warn");
    }
    this.refresh();
    return code;
  }

  /** 关掉战利品横幅。 */
  dismissLoot(): void {
    this.lastLoot = null;
    this.refresh();
  }''',
        ),
        (
            'lastLoot field decl',
            '''  private chestBaseline: { gold: number; relicCount: number; relics: string[] } | null = null;''',
            '''  private chestBaseline: { gold: number; relicCount: number; relics: string[] } | null = null;
  /** 见 `RunState.lastLoot`。 */
  private lastLoot: RunState["lastLoot"] = null;''',
        ),
    ],
)

# ── 2. ChestScene：只有"打开"和"不打开就走" ─────────────────────────────────
io.open('web-next/src/run/scenes/ChestScene.tsx', 'w', encoding='utf-8', newline='\n').write(
    '''// 宝箱（`SC-07`，`pending == 3`）。
//
// ## 这一屏只有两个按钮，因为内核就是这么设计的
//
// `rd_run_open_chest()` 的语义是**打开即结束**（相位直接归 0），所以"已打开的宝箱"不是一个
// 可停留的屏。第一版按"打开 → 看战利品 → 离开"画了三个状态，结果点完打开相位就没了，
// 界面还在等一个永远不会来的"离开"按钮（闸门 36 第一次跑就是这条红）。
//
// 现在：**打开**（然后由外壳用战利品横幅告诉玩家拿到了什么）或**不打开就走**。
// 战利品横幅在 `RunApp` 里，`RunStore.lastLoot` 提供数据。

export interface ChestSceneProps {
  readonly onOpen: () => void;
  readonly onLeave: () => void;
  readonly busy?: boolean;
}

export function ChestScene({ onOpen, onLeave, busy = false }: ChestSceneProps) {
  return (
    <section className="scene scene-chest" data-scene="SC-07">
      <header className="scene-head">
        <h2>宝箱</h2>
        <p className="scene-sub">打开之后才知道里面有什么</p>
      </header>

      <div className="chest-body">
        <div className="chest-glyph" aria-hidden>
          ▣
        </div>
        <p className="muted">一个还没打开的箱子。</p>
      </div>

      <button type="button" className="primary" data-chest-open onClick={onOpen} disabled={busy}>
        打开宝箱
      </button>
      <button type="button" data-chest-leave onClick={onLeave} disabled={busy}>
        不打开，离开
      </button>
    </section>
  );
}
''',
)

# ── 3. RunApp：宝箱 props + 战利品横幅 ──────────────────────────────────────
patch(
    'web-next/src/run/RunApp.tsx',
    [
        (
            'chest props',
            '''        {base === SCENE.chest && (
          <ChestScene
            opened={state.chest.opened}
            goldGained={state.chest.goldGained}
            relicGained={state.chest.relicGained}
            busy={blocked}
            onOpen={() => store.openChest()}
            onLeave={() => store.leave()}
          />
        )}''',
            '''        {base === SCENE.chest && (
          <ChestScene busy={blocked} onOpen={() => store.openChest()} onLeave={() => store.leave()} />
        )}''',
        ),
        (
            'loot banner',
            '''      {/* ── 对账失败：**响亮**失败，并冻结推进 ─────────────────────────────── */}''',
            '''      {/* ── 战利品横幅：宝箱"打开即结束"，所以战利品要在这里说 ──────────────── */}
      {state.lastLoot && (
        <div className="run-loot" data-run-loot={state.lastLoot.source}>
          <span>
            {state.lastLoot.source}：金币 +{state.lastLoot.gold}
            {state.lastLoot.relic ? ` · 遗物 ${state.lastLoot.relic}` : ""}
          </span>
          <button type="button" data-loot-dismiss onClick={() => store.dismissLoot()}>
            知道了
          </button>
        </div>
      )}

      {/* ── 对账失败：**响亮**失败，并冻结推进 ─────────────────────────────── */}''',
        ),
    ],
)
print('done')
