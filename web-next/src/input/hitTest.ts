/**
 * 屏幕空间命中辅助：与 WebGL 的射线事件相互独立。
 *
 * 手指在触摸屏上松开的坐标可能不再落在 R3F mesh 上，导致 onPointerUp 丢失。
 * 使用 Stage 每帧投影生成的 ScreenLayout 作为全局 pointerup 的权威位置补偿。
 * 这里不判定游戏规则，合法性仍由 pointerMachine.options / WASM 决定。
 */
import type { CardScreen, EnemyScreen } from "../stage/layout";

export function enemyAtScreen(
  enemies: readonly EnemyScreen[], x: number, y: number,
  allowedSlots: ReadonlySet<number>, extraTouchRadius = 14
): number {
  let best = -1;
  let nearest = Number.POSITIVE_INFINITY;
  for (const enemy of enemies) {
    if (!allowedSlots.has(enemy.slot)) continue;
    const d = Math.hypot(x - enemy.x, y - enemy.y);
    if (d <= Math.max(24, enemy.r + extraTouchRadius) && d < nearest) {
      nearest = d;
      best = enemy.slot;
    }
  }
  return best;
}

/** 右压左的手牌，命中判定必须检查露出部分中心 hitX，不能用被遮住的 card.x。 */
export function cardAtScreen(cards: readonly CardScreen[], x: number, y: number): number {
  for (let i = cards.length - 1; i >= 0; i -= 1) {
    const c = cards[i];
    if (Math.abs(x - c.hitX) <= Math.max(12, c.visibleW / 2)
      && Math.abs(y - c.hitY) <= c.h / 2) return c.slot;
  }
  return -1;
}
