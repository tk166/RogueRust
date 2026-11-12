// 局终（`SC-12b`）与幕通关（`SC-12a`）。
//
// ## 为什么两个放一个文件
//
// 它们是同一件事的两个出口："这一局结束了（战败/通关/地图走完）" 与 "这一幕打完了但还有下一幕"。
// 文案与按钮不同，布局一样。分开两个文件会让"改一处忘另一处"变成必然。
//
// ## 交互
//
// * 局终：说清**为什么**（`rd_run_over_why` 的判别值，不是猜），给"再来一局"（回标题，种子回填）；
// * 幕通关：说清"这一幕到此为止"，给"继续"（内核的 `end_act`；P3 里它还没接，所以按钮
//   只在地图能继续时出现 —— 见 `RunApp` 的注释）。

import type { RunSnapshot } from "../observe.js";

export interface EndSceneProps {
  readonly kind: "over" | "actCleared";
  readonly run: RunSnapshot;
  /** `RunEnd` 判别值：0 进行中 / 1 战败 / 2 通关 / 3 地图走完了。 */
  readonly overWhy: number;
  readonly ascension: number;
  readonly onRestart: () => void;
  readonly onContinue?: () => void;
}

/** `RunEnd` 判别值 → 一句话。**数字是 ABI**（`rd_run_over_why` 的注释里写明不要重排）。 */
export function overReasonLabel(overWhy: number): string {
  switch (overWhy) {
    case 1:
      return "倒在了半路上";
    case 2:
      return "通关了";
    case 3:
      return "这座塔到此为止（地图走完了）";
    default:
      return "这一局结束了";
  }
}

export function EndScene({ kind, run, overWhy, ascension, onRestart, onContinue }: EndSceneProps) {
  const over = kind === "over";
  return (
    <section className="scene scene-end" data-scene={over ? "SC-12b" : "SC-12a"}>
      <header className="scene-head">
        <h2>{over ? (overWhy === 2 ? "通关" : "这一局结束") : "这一幕打完了"}</h2>
        <p className="scene-sub">
          {over ? overReasonLabel(overWhy) : "往上还有更多"}
          {ascension > 0 ? ` · 进阶 ${ascension}` : ""}
        </p>
      </header>

      <dl className="end-stats">
        <div>
          <dt>到达</dt>
          <dd>第 {run.floor} 层</dd>
        </div>
        <div>
          <dt>生命</dt>
          <dd>
            {run.health} / {run.healthMax}
          </dd>
        </div>
        <div>
          <dt>金币</dt>
          <dd>{run.gold}</dd>
        </div>
        <div>
          <dt>牌组</dt>
          <dd>{run.deckSize} 张</dd>
        </div>
        <div>
          <dt>遗物</dt>
          <dd>{run.relicCount} 个</dd>
        </div>
      </dl>

      {over ? (
        <button type="button" className="primary" data-restart onClick={onRestart}>
          再来一局
        </button>
      ) : (
        onContinue && (
          <button type="button" className="primary" data-act-continue onClick={onContinue}>
            继续
          </button>
        )
      )}
    </section>
  );
}
