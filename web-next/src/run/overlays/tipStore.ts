// 悬浮详情的**唯一一个**宿主（§389）：模块级 store + 一个面板，挂在"药水栏下方、战场上方"。
//
// ## 为什么是模块级 store 而不是 props
//
// 需要"指一下就显示详情"的地方有六处，分属两棵组件树：
//   * 运行层外壳：遗物条、药水腰带、奖励屏、商店、牌组选择器；
//   * 战斗屏：手牌（3D + `TextOverlay`）、敌人/英雄的状态 chip。
//
// 把 setter 一路 props 传下去要穿过 `RunApp → CombatScreen → Stage/TextOverlay`，
// 而面板只应该有一个（两个面板会同时出现）。所以：**谁想显示就 `showTip()`**，
// 外壳里那一个 `<CardTipHost/>` 负责画。
//
// ## 纪律
//
// * 面板**永远只有一个**（同一个 store、同一个 host）；
// * `position: fixed`（脱离文档流）—— §381 的教训：在流内会把容器宽度顶来顶去，
//   卡牌一列/两列来回跳；
// * 鼠标 `pointerenter` / 触摸 `pointerdown` / 键盘 `focus` 三条路都调 `showTip`。

import { useSyncExternalStore } from "react";
import { describeTip, type TipRequest } from "../../view/cardTipText.js";

let current: TipRequest | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** 显示一条详情（`null` = 收起）。 */
export function showTip(request: TipRequest | null): void {
  // 同一件东西重复触发（鼠标在 chip 里移动）不重渲染。
  if (current?.kind === request?.kind && current?.id === request?.id) return;
  current = request;
  emit();
}

/** 收起（离开元素时用）。 */
export function hideTip(): void {
  if (current === null) return;
  current = null;
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): TipRequest | null {
  return current;
}

/** 组件里读当前请求（`useSyncExternalStore` 保证外部 store 的读取是安全的）。 */
export function useTipRequest(): TipRequest | null {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** 一个元素"指一下就显示"的三个处理器（鼠标 / 触摸 / 键盘各一条路）。 */
export function tipHandlers(request: TipRequest): {
  onPointerEnter: () => void;
  onPointerDown: () => void;
  onFocus: () => void;
  onPointerLeave: () => void;
  onBlur: () => void;
} {
  return {
    onPointerEnter: () => showTip(request),
    onPointerDown: () => showTip(request),
    onFocus: () => showTip(request),
    onPointerLeave: () => hideTip(),
    onBlur: () => hideTip(),
  };
}

export { describeTip };
export type { TipKind, TipRequest } from "../../view/cardTipText.js";
