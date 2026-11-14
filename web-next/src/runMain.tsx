// `run.html` 的入口：P3 的运行层（真游戏路径）。
//
// 与 `main.tsx`（P1/P2 回归页）分开是**故意**的：
//   * `index.html` 是"装载内核 → 走到第一场战斗"的回归夹具，闸门 25–32 打它；
//   * `run.html` 是产品路径：标题 → 祝福 → 地图 → 战斗 → 奖励 → 地图。
// 混在一个页面里会让"闸门测的是回归夹具"和"玩家玩的是另一条路"同时成立 —— 那正是假绿。

import { createRoot } from "react-dom/client";
import { StrictMode } from "react";
import { RunApp } from "./run/RunApp";
// ⚠️ **必须**加载 `styles.css`：战斗屏（`CombatScreen`）的 DOM 覆盖层 —— 卡面文字、
// 卡牌详情、提示条、状态横幅 —— 全都靠它定位与上色。`run.css` 只管运行层外壳（顶栏/场景/地图）。
// 第一版漏了这一行，于是 `run.html` 里 `.text-layer` 是 `position: static`：
// 卡面文字飘在页面最下面（实测 y=1234，牌在 y=591）⇒ **看起来"卡面是空的"**。
import "./styles.css";

/**
 * `?safe=44,34`：把安全区变量覆盖成指定像素。
 *
 * 为什么需要它：CDP 改不了真机的 `env(safe-area-inset-*)`（那是设备/浏览器给的），
 * 而"内容有没有让开刘海"必须**能测**。所以闸门用这个参数把变量设成非零，再断言
 * 顶栏/日志的**实际位置**让开了那么多 —— 比"我写了 env() 所以应该没事"强。
 */
const safe = new URLSearchParams(window.location.search).get("safe");
if (safe) {
  const [top, bottom] = safe.split(",");
  const root = document.documentElement;
  if (top) root.style.setProperty("--safe-top", `${Number(top)}px`);
  if (bottom) root.style.setProperty("--safe-bottom", `${Number(bottom)}px`);
}

const container = document.getElementById("root");
if (!container) throw new Error("#root missing");

createRoot(container).render(
  <StrictMode>
    <RunApp />
  </StrictMode>
);
