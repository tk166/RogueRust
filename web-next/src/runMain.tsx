// `run.html` 的入口：P3 的运行层（真游戏路径）。
//
// 与 `main.tsx`（P1/P2 回归页）分开是**故意**的：
//   * `index.html` 是"装载内核 → 走到第一场战斗"的回归夹具，闸门 25–32 打它；
//   * `run.html` 是产品路径：标题 → 祝福 → 地图 → 战斗 → 奖励 → 地图。
// 混在一个页面里会让"闸门测的是回归夹具"和"玩家玩的是另一条路"同时成立 —— 那正是假绿。

import { createRoot } from "react-dom/client";
import { StrictMode } from "react";
import { RunApp } from "./run/RunApp";

const container = document.getElementById("root");
if (!container) throw new Error("#root missing");

createRoot(container).render(
  <StrictMode>
    <RunApp />
  </StrictMode>
);
