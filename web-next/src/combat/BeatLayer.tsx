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
import { recipeFor } from "../presentation/registry.js";
import type { ScreenLayout } from "../stage/layout";

export interface BeatLayerProps {
  readonly director: DirectorState;
  readonly layout: ScreenLayout;
  /** 英雄在屏幕上的位置（`layout` 只投敌人，英雄固定在左侧）。 */
  readonly hero: { x: number; y: number };
  readonly onSkip: () => void;
  /**
   * §399：槽位 → 当前外观 id。用来校验"冻结锚点是否还指向同一个对象"。
   * 缺省返回空串 = 不校验（夹具/旧路径保持原行为）。
   */
  readonly appearanceOf?: (slot: number) => string;
}

/**
 * 墙位槽 → 屏幕坐标。`-2`（不在场上）落在屏幕中间上方，让玩家至少看得见。
 *
 * §399：这里多了一个**身份校验**。`layout.enemies` 是**当前**的投影，而槽位会被重用
 * （Boss 分裂出两只小史莱姆、召唤、死亡之后同一个 `slot` 换了主人）。于是队列里较早的 Beat
 * 会被画在**新**对象头顶 —— 玩家看到"我打的明明是老大，飘字飘在小史莱姆身上"。
 *
 * 判据：Cue 里冻结的 `appearanceId` 必须与当前槽位的外观一致；不一致就退回**冻结的槽位**
 * （`anchorSlot` 与 `at` 通常相同，但语义上这是"按事件发生时的身份定位"），再不行才用屏幕中上。
 */
function anchorOf(
  at: number,
  layout: ScreenLayout,
  hero: { x: number; y: number },
  frozen: { anchorSlot: number; appearanceId: string },
  appearanceOf: (slot: number) => string
): { x: number; y: number } {
  if (at === -1) return hero;
  const enemy = layout.enemies.find((candidate) => candidate.slot === at);
  if (enemy) {
    const now = appearanceOf(at);
    // 空串 = 调用方没给身份（夹具/旧路径）⇒ 不做校验，保持老行为。
    const sameIdentity = frozen.appearanceId === "" || now === "" || now === frozen.appearanceId;
    if (sameIdentity) return { x: enemy.x, y: enemy.y };
  }
  return { x: layout.width / 2, y: layout.height * 0.35 };
}

export function BeatLayer({ director, layout, hero, onSkip, appearanceOf = () => "" }: BeatLayerProps) {
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

  // §399：配方决定颜色/形状/震屏（`data-cue-*` 供闸门断言），文案仍是中文。
  const { recipe, fallback } = recipeFor(playing.effectKey);
  const point = anchorOf(playing.at, layout, hero, playing, appearanceOf);
  return (
    // ⚠️ 演出层本身 `pointer-events: none`（绝不拦截拖拽/点击），只有"跳过"那块可点。
    <div
      className={`beat-layer${recipe.shake ? " is-shake" : ""}`}
      data-beat-layer={playing.kind}
      data-cue-key={playing.effectKey}
      data-cue-shape={recipe.shape}
      data-cue-origin={playing.origin.kind}
      data-cue-def={playing.origin.kind === "system" ? "" : playing.origin.defId}
      data-cue-fallback={fallback ? "1" : "0"}
    >
      <span
        key={playing.id}
        className={`beat-float is-${playing.tone} is-shape-${recipe.shape}`}
        data-beat-kind={playing.kind}
        data-beat-at={playing.at}
        data-beat-text={playing.text}
        style={{ left: `${point.x}px`, top: `${point.y}px`, color: recipe.color }}
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
