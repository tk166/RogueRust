// 性能相关的**纯常量与规则**（P6）。抽出来的理由：同一条规则如果界面与探针各写一份，
// 闸门测到的就可能是"另一份"（`dprCap` 第一版就是这么分裂的）。
//
// ## DPR 上限为什么分窄屏/宽屏
//
// 390×700 的画布：dpr 2 ⇒ 780×1400 ≈ **1.09M** 像素；dpr 1.5 ⇒ 585×1050 ≈ **0.61M**（-44%）。
// 手机 GPU 上这是最直接的一刀，而肉眼看不出差别（390 CSS px 宽、1.5 倍已经比 1080p 的横向
// 采样更密）。桌面字要更锐，所以宽屏保持 2。

/** 窄屏（手机竖屏）的 DPR 上限。 */
export const NARROW_MAX_DPR = 1.5;
/** 宽屏的 DPR 上限。 */
export const WIDE_MAX_DPR = 2;
/** 窄屏阈值（CSS 像素）。与 CSS 的 `@media (max-width: 600px)` 是**同一条线**。 */
export const NARROW_WIDTH = 600;

export function dprCapFor(width: number): number {
  return width < NARROW_WIDTH ? NARROW_MAX_DPR : WIDE_MAX_DPR;
}

/** 画布后备像素（用于"优化前后"的记录）。 */
export function backingPixels(cssWidth: number, cssHeight: number, dpr: number): number {
  return Math.round(cssWidth * dpr) * Math.round(cssHeight * dpr);
}
