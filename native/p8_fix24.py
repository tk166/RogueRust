"""修 #2（删旧 fallback 覆盖层）与 #4（`SC-02b` 身份/继续抽成纯函数）。"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── #4a：scene.ts 加纯函数 endSceneFor（"哪一屏报哪个 data-scene、能不能继续"）──
patch(
    'web-next/src/run/scene.ts',
    [
        (
            'endSceneFor',
            '''/** 这一屏在 P3 里**实现了**吗（没实现的走 `UnsupportedScene`，见 `scenes/UnsupportedScene.tsx`）。 */''',
            '''/**
 * 终局类场景的**身份与能力**（纯函数）。
 *
 * ⚠️ 抽出来的理由（第十五轮 Review §4）：`EndScene` 以前自己把 `data-scene` 算成
 * `over ? "SC-12b" : "SC-12a"`，于是 `SC-02b`（幕尽头）**报成 `SC-12a`**，而且"继续"
 * 按钮只在 `SC-12a` 时给 ⇒ 一旦 `SC-02b` 真的可达，画面就是"这一幕打完了但没有下一步"。
 * 那是个**潜伏软锁**，而闸门 34/36 的 `domScene() == scene.base` 抓不到它
 * （`SC-02b` 在当前内容下不可达，那条断言从未被执行）。
 *
 * 所以：身份与能力放在这里，闸门 33 **纯函数**就能钉住，不依赖"某条路径真的走得到"。
 */
export interface EndSceneShape {
  /** 这一屏自己报的 `data-scene`（**必须**等于场景 id，不能借别的 id）。 */
  readonly sceneId: SceneId;
  /** `EndScene` 的两种语气：局终 / 幕。
   *
   * ⚠️ 两种语气共用一套布局，但**身份不同** —— 这正是以前被抹掉的东西。 */
  readonly kind: "over" | "actCleared";
  /**
   * 有没有"继续"。
   *
   * `SC-12a`（幕通关）与 `SC-02b`（幕尽头）都能继续：前者是"打赢了 Boss 进入下一幕"，
   * 后者是"地图走完了" —— 两者对应的内核动作都是 `rd_run_end_act`。
   * `SC-12b`（局终）没有继续，只有"再来一局"。
   */
  readonly canContinue: boolean;
}

/** 终局类场景 → 身份/能力。非终局类返回 `null`。 */
export function endSceneFor(scene: SceneId): EndSceneShape | null {
  switch (scene) {
    case SCENE.over:
      return { sceneId: SCENE.over, kind: "over", canContinue: false };
    case SCENE.actCleared:
      return { sceneId: SCENE.actCleared, kind: "actCleared", canContinue: true };
    case SCENE.actEnd:
      return { sceneId: SCENE.actEnd, kind: "actCleared", canContinue: true };
    default:
      return null;
  }
}

/** 这一屏在 P3 里**实现了**吗（没实现的走 `UnsupportedScene`，见 `scenes/UnsupportedScene.tsx`）。 */''',
        ),
    ],
)

# ── #4b：EndScene 接受 sceneId / canContinue，不再自己算 data-scene ──────────
patch(
    'web-next/src/run/scenes/EndScene.tsx',
    [
        (
            'props sceneId',
            '''export interface EndSceneProps {
  readonly kind: "over" | "actCleared";''',
            '''export interface EndSceneProps {
  /**
   * 这一屏**自己**的场景 id（`data-scene` 用它）。
   *
   * ⚠️ 以前这里从 `kind` 反推（`over ? SC-12b : SC-12a`），于是 `SC-02b` 会报成 `SC-12a`
   * —— 身份被抹掉，而闸门看不见（那条路径不可达）。现在由 `scene.ts::endSceneFor` 给。
   */
  readonly sceneId: string;
  readonly kind: "over" | "actCleared";''',
        ),
        (
            'signature sceneId',
            '''export function EndScene({
  kind,''',
            '''export function EndScene({
  sceneId,
  kind,''',
        ),
        (
            'data-scene uses sceneId',
            '''    <section className="scene scene-end" data-scene={over ? "SC-12b" : "SC-12a"}>''',
            '''    <section className="scene scene-end" data-scene={sceneId}>''',
        ),
    ],
)

# ── #4c：RunApp 用 endSceneFor，并把 onContinue 给"能继续"的两屏 ─────────────
patch(
    'web-next/src/run/RunApp.tsx',
    [
        (
            'import endSceneFor',
            '''import { isImplemented, sceneLabel, SCENE } from "./scene.js";''',
            '''import { endSceneFor, isImplemented, sceneLabel, SCENE } from "./scene.js";''',
        ),
        (
            'end scene block',
            '''        {(base === SCENE.over || base === SCENE.actCleared || base === SCENE.actEnd) && run && (
          <EndScene
            kind={base === SCENE.over ? "over" : "actCleared"}
            run={run}
            overWhy={state.overWhy}
            ascension={state.ascension}
            busy={blocked}
            onRestart={() => {
              store.startRun(last.seed, last.ascension);
            }}
            onContinue={base === SCENE.actCleared ? () => store.endAct() : undefined}
          />
        )}''',
            '''        {(() => {
          // 身份与能力都由**纯函数**给（`scene.ts::endSceneFor`），组件只负责画。
          const end = endSceneFor(base);
          if (!end || !run) return null;
          return (
            <EndScene
              sceneId={end.sceneId}
              kind={end.kind}
              run={run}
              overWhy={state.overWhy}
              ascension={state.ascension}
              busy={blocked}
              onRestart={() => {
                store.startRun(last.seed, last.ascension);
              }}
              onContinue={end.canContinue ? () => store.endAct() : undefined}
            />
          );
        })()}''',
        ),
    ],
)

# ── #2：删掉 P4 之前的通用 fallback 覆盖层（与 PickupOverlay 重复且文案过期）──
patch(
    'web-next/src/run/RunApp.tsx',
    [
        (
            'delete legacy overlay',
            '''      {/* ── 覆盖层（`SC-11a`/`SC-11b`：遗物欠账）─────────────────────────── */}
      {scene.overlays.length > 0 && (
        <div className="run-overlay" data-run-overlay={scene.overlays.join(",")}>
          <div className="run-overlay-card">
            <h3>{scene.overlays.map(sceneLabel).join(" / ")}</h3>
            <p className="muted">遗物要求你改牌/加牌 —— 牌组选择器在 P4。</p>
            <button type="button" className="primary" data-overlay-settle onClick={() => store.settleDefault()}>
              用内核的默认动作通过
            </button>
          </div>
        </div>
      )}

''',
            '''      {/*
        ⚠️ 这里曾经还有一个"通用覆盖层"（`data-run-overlay`），文案写着"牌组选择器在 P4"、
        带一个 `settleDefault()` 按钮。P4 做完之后它就成了**第二套**遗物模态：与下面的
        `PickupOverlay` 同时存在于 DOM，而且给了一条"用默认动作跳过欠账"的错路
        （第十五轮 Review §3）。已删除 —— 遗物欠账**只有** `PickupOverlay` 一条路。
      */}

''',
        ),
    ],
)
print('done')
