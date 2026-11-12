"""RunStore：补 RunApp 需要的三个接口（hostForCombat / pending / 公开 note）。"""

import io

P = 'web-next/src/run/RunStore.ts'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''  readonly scene: SceneResolution;
  readonly seed: number;''',
    '''  readonly scene: SceneResolution;
  /** 当前相位（`rd_run_pending`）：0 = 没有待决屏。诊断与"未实现屏"都用它。 */
  readonly pending: number;
  readonly seed: number;''',
    'state pending field',
)

sub(
    '''      scene: { base: "SC-00", overlays: [], unknownPending: null },
      seed: 0,''',
    '''      scene: { base: "SC-00", overlays: [], unknownPending: null },
      pending: 0,
      seed: 0,''',
    'state init',
)

sub(
    '''      run,
      map,
      scene,
      seed: raw.seed,''',
    '''      run,
      map,
      scene,
      pending,
      seed: raw.seed,''',
    'state assign',
)

sub(
    '''  /** 战斗 store（P2 的那一套原样复用：手势、动作表版本号、拒绝证明都在里面）。 */
  get combat(): GameStore | null {
    return this.combatStore;
  }''',
    '''  /** 战斗 store（P2 的那一套原样复用：手势、动作表版本号、拒绝证明都在里面）。 */
  get combat(): GameStore | null {
    return this.combatStore;
  }

  /**
   * 战斗屏要的那个宿主（与运行层**同一个** wasm 实例）。
   *
   * 单独一个 getter 而不是把 `host` 变 public：组件不该顺手拿宿主去调别的导出，
   * 它只需要把它交给 `CombatScreen`（那一层再交给 `GameStore`）。
   */
  get hostForCombat(): WasmHost {
    return this.host;
  }''',
    'hostForCombat',
)

sub(
    '''  private note(text: string, kind: LogEntry["kind"] = "info"): void {''',
    '''  /** 记一行日志（公开：地图上点了一个到不了的节点，也值得留痕）。 */
  note(text: string, kind: LogEntry["kind"] = "info"): void {''',
    'note public',
)
io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('RunStore: 3 interfaces')
