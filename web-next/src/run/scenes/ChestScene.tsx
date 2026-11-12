// 宝箱（`SC-07`，`pending == 3`）。
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
