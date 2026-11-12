"""P4 修正 2：Boss 哨兵（`BOSS_NODE = 100`）要能点 —— 第一版软锁在第 15 层。"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── 1. observe.ts：哨兵常量 ─────────────────────────────────────────────────
patch(
    'web-next/src/run/observe.ts',
    [
        (
            'boss sentinel',
            '''/** `?` 房掷出来的东西（`env-abi.md` §11.3 第 18 格，§272）。 */''',
            '''/**
 * Boss 的**哨兵下标**（`rd_run::map::BOSS_NODE = 100`）。
 *
 * ⚠️ 第 16 层的 Boss **不在地图上**（`inv:§7.2`：floor 16 在地图之外），它是以"哨兵"的形式
 * 出现在**动作表**里的。第一版只从 `map.nodes` 里找 Boss（`kind == 7`），于是：
 * 第 15 层站定之后 `map.nodes` 里一个可达节点都没有，而内核其实给了一条合法动作
 * （`enter_node(100)`）—— 界面看起来"没有下一步"，玩家软锁（闸门 36 实测）。
 */
export const BOSS_SENTINEL = 100;

/** `?` 房掷出来的东西（`env-abi.md` §11.3 第 18 格，§272）。 */''',
        ),
    ],
)

# ── 2. RunStore：bossReachable ──────────────────────────────────────────────
patch(
    'web-next/src/run/RunStore.ts',
    [
        (
            'import sentinel',
            '''import {
  buildMap,
  decodeRun,
  opensFight,''',
            '''import {
  BOSS_SENTINEL,
  buildMap,
  decodeRun,
  opensFight,''',
        ),
        (
            'state bossReachable',
            '''  readonly scene: SceneResolution;
  /** 当前相位（`rd_run_pending`）：0 = 没有待决屏。诊断与"未实现屏"都用它。 */
  readonly pending: number;''',
            '''  readonly scene: SceneResolution;
  /**
   * Boss 哨兵这一步能不能进。
   *
   * 它**不在** `map.nodes` 里（第 16 层在地图之外），所以地图屏要单独问这一句；
   * 少了它，第 15 层之后就没有可点的格子（软锁）。
   */
  readonly bossReachable: boolean;
  /** 当前相位（`rd_run_pending`）：0 = 没有待决屏。诊断与"未实现屏"都用它。 */
  readonly pending: number;''',
        ),
        (
            'state bossReachable init',
            '''      pending: 0,
      seed: 0,''',
            '''      bossReachable: false,
      pending: 0,
      seed: 0,''',
        ),
        (
            'compute bossReachable',
            '''      actionCount: this.host.runActions().length,''',
            '''      actionCount: actions.length,''',
        ),
        (
            'actions var',
            '''    const input: SceneInput = {''',
            '''    const actions = raw.exists ? this.host.runActions() : [];
    const input: SceneInput = {''',
        ),
        (
            'assign bossReachable',
            '''      pending,
      seed: raw.seed,''',
            '''      bossReachable: actions.some((action) => action.target === BOSS_SENTINEL),
      pending,
      seed: raw.seed,''',
        ),
    ],
)

# ── 3. MapScene：Boss 哨兵变成可点按钮 ──────────────────────────────────────
patch(
    'web-next/src/run/scenes/MapScene.tsx',
    [
        (
            'props boss',
            '''  readonly onEnter: (index: number) => void;
  readonly onBlocked: (index: number) => void;''',
            '''  readonly onEnter: (index: number) => void;
  readonly onBlocked: (index: number) => void;
  /**
   * Boss 哨兵这一步能不能进（`rd_run_action_arg` 里有 `BOSS_NODE`）。
   *
   * ⚠️ 它**不在** `map.nodes` 里 —— 第 16 层在地图之外。所以这个徽章不是"装饰"，
   * 它是第 15 层之后**唯一**的下一步。
   */
  readonly bossReachable: boolean;
  readonly bossIndex: number;''',
        ),
        (
            'destructure boss',
            '''export function MapScene({ run, map, onEnter, onBlocked, inert = false }: MapSceneProps) {''',
            '''export function MapScene({
  run,
  map,
  onEnter,
  onBlocked,
  bossReachable,
  bossIndex,
  inert = false,
}: MapSceneProps) {''',
        ),
        (
            'boss badge',
            '''      {boss && (
        <div className="map-boss" data-boss-sentinel={boss.index}>
          <span aria-hidden>{nodeKindGlyph(boss.kind)}</span>
          <span>{nodeKindLabel(boss.kind)}</span>
        </div>
      )}''',
            '''      {/* Boss 哨兵：可点时是**按钮**（第 15 层之后唯一的下一步），不可点时只是徽章。 */}
      {bossReachable && !inert ? (
        <button
          type="button"
          className="map-boss is-reachable"
          data-boss-sentinel={bossIndex}
          data-boss-reachable="1"
          onClick={() => onEnter(bossIndex)}
        >
          <span aria-hidden>{nodeKindGlyph(NODE_KIND.boss)}</span>
          <span>{nodeKindLabel(NODE_KIND.boss)}（可前往）</span>
        </button>
      ) : (
        <div className="map-boss" data-boss-sentinel={boss ? boss.index : -1}>
          <span aria-hidden>{nodeKindGlyph(NODE_KIND.boss)}</span>
          <span>{nodeKindLabel(NODE_KIND.boss)}</span>
        </div>
      )}''',
        ),
    ],
)

# ── 4. RunApp：传 boss 字段 ────────────────────────────────────────────────
patch(
    'web-next/src/run/RunApp.tsx',
    [
        (
            'pass boss props',
            '''          <MapScene
            run={run}
            map={map}
            inert={blocked || scene.overlays.length > 0}
            onEnter={onEnter}
            onBlocked={onBlocked}
          />''',
            '''          <MapScene
            run={run}
            map={map}
            inert={blocked || scene.overlays.length > 0}
            bossReachable={state.bossReachable}
            bossIndex={BOSS_SENTINEL}
            onEnter={onEnter}
            onBlocked={onBlocked}
          />''',
        ),
        (
            'import sentinel',
            '''import { nodeKindLabel } from "./observe.js";''',
            '''import { BOSS_SENTINEL, nodeKindLabel } from "./observe.js";''',
        ),
    ],
)
print('done')
