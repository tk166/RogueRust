// `assets.html` 的入口：素材库预览页（P8 的流水线）。
//
// 与 `run.html` 分开是**故意**的：素材页不进产品路径，但它必须有闸门看得见的探针
// （`window.__assets`），否则"素材有没有覆盖全"就只能靠人翻。

import { createRoot } from "react-dom/client";
import { StrictMode } from "react";
import { AssetsApp, installAssetProbe } from "./assets/AssetsApp";

installAssetProbe();

const container = document.getElementById("root");
if (!container) throw new Error("#root missing");

createRoot(container).render(
  <StrictMode>
    <AssetsApp />
  </StrictMode>
);
