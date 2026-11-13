// 幕布的**纯逻辑**（`ui-state-model.md` §2.3）：判定与时长。
//
// 单独一个 `.ts`（不是 `.tsx`）是**为了可单测**：闸门 48 在 Node 里直接编译并导入它，
// 而 `.tsx` 会拖进 React（`ERR_MODULE_NOT_FOUND: react`）。同一份判定因此不需要浏览器就能钉住。

/** 自动淡出的时长（与旧页面 `#actCurtain` 一致：1600 ms）。 */
export const CURTAIN_MS = 1600;

/**
 * 该不该播幕布。
 *
 * 判据：**`act` 变大**。三条边界：
 * * `act` 变小（重开一局）⇒ 不播（标题屏已经说清了，再盖一层幕像"没退出去"）；
 * * `previous === 0`（第一次读到幕号）⇒ 不播（那不是换幕，是"刚开局"）；
 * * `motionOff` ⇒ 不播（关动画的人不该被强制看演出）。
 */
export function shouldShowCurtain(previous: number, act: number, motionOff: boolean): boolean {
  if (motionOff) return false;
  if (previous === 0) return false;
  return act > previous;
}
