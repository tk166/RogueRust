// `index.html` 的入口：P1/P2 的**回归页**。
//
// 真正的游戏外壳是 `run/RunApp.tsx`（`run.html`，P3）。这个文件只剩一件事：
// 用 P2 的行为装载内核并走到第一场战斗，好让闸门 25–32 继续打同一个组件。
//
// ⚠️ 这里**故意**不实现地图/奖励 —— 它是回归页，不是产品页。产品路径在 `run.html`。

import { CombatScreen } from "./combat/CombatScreen";

const MOCK = new URLSearchParams(window.location.search).has("mock");

export function App() {
  return <CombatScreen mode={MOCK ? "mock" : "auto"} />;
}
