// Beat 演出的**渲染层**：把导演当前那一条画成飘字（DOM，不碰 3D）。
//
// ## 为什么用 DOM 而不是 3D 文本
//
// * 飘字要**清晰可读**（P1 的可读性要求）；3D 文本在斜视角下会被压扁，还要付字体的账。
// * 位置来自 `layout`（每帧投影的真值），所以 DOM 与 3D 用的是**同一套坐标**，
//   不会出现"飘字和敌人在两个地方"。
// * `pointer-events: none`：演出层绝不拦截拖拽/点击（否则玩家会觉得"点了没反应"）。
//
// ## 降级
//
// * `reducedMotion`（`?motion=off` 或系统 `prefers-reduced-motion`）：一条都不播；
// * 未知 kind：画成中性灰的 `?N`（并且 `dropped`/`unknown` 会在顶栏显示一行诊断）。

import type { BeatEffect, DirectorState } from "./beats.js";
import type { ScreenLayout } from "../stage/layout";

export interface BeatLayerProps {
  readonly director: DirectorState;
  readonly layout: ScreenLayout;
  /** 英雄在屏幕上的位置（`layout` 只投敌人，英雄固定在左侧）。 */
  readonly hero: { x: number; y: number };
  readonly onSkip: () => void;
}

/** 墙位槽 → 屏幕坐标。`-2`（不在场上）落在屏幕中间上方，让玩家至少看得见。 */
function anchorOf(at: number, layout: ScreenLayout, hero: { x: number; y: number }): { x: number; y: number } {
  if (at === -1) return hero;
  const enemy = layout.enemies.find((candidate) => candidate.slot === at);
  if (enemy) return { x: enemy.x, y: enemy.y };
  return { x: layout.width / 2, y: layout.height * 0.35 };
}

export function BeatLayer({ director, layout, hero, onSkip }: BeatLayerProps) {
  const playing: BeatEffect | null = director.playing;
  if (!playing) {
    // 队列空时也要把"动画不全"的账挂出来（它不会自己消失，玩家得知道）。
    if (director.dropped === 0 && director.unknownKinds.length === 0) return null;
    return (
      <div className="beat-note" data-beat-note>
        {director.dropped > 0 && <span data-beat-dropped={director.dropped}>动画不全（内核丢了 {director.dropped} 条）</span>}
        {director.unknownKinds.length > 0 && (
          <span data-beat-unknown={director.unknownKinds.join(",")}>
            未知演出种类 {director.unknownKinds.join(",")}
          </span>
        )}
      </div>
    );
  }

  const point = anchorOf(playing.at, layout, hero);
  return (
    // ⚠️ 演出层本身 `pointer-events: none`（绝不拦截拖拽/点击），只有"跳过"那块可点。
    <div className="beat-layer" data-beat-layer={playing.kind}>
      <span
        key={playing.id}
        className={`beat-float is-${playing.tone}`}
        data-beat-kind={playing.kind}
        data-beat-at={playing.at}
        data-beat-text={playing.text}
        style={{ left: `${point.x}px`, top: `${point.y}px` }}
      >
        {playing.text}
      </span>
      {director.queue.length > 0 && (
        <button
          type="button"
          className="beat-queue"
          data-beat-queue={director.queue.length}
          onClick={onSkip}
        >
          +{director.queue.length} · 跳过（Esc）
        </button>
      )}
    </div>
  );
}
