// 闸门 50 `ui-distributable`：**clone 下来就能玩**（§372）。
//
// 这一道守的是"陌生人第一步"。之前 `web-next/dist/rd_wasm.wasm` 被 `.gitignore` 排除 ⇒
// 新克隆的 `dist/` 有 HTML/JS 却没有 wasm ⇒ 页面直接"内核装载失败"，而且只有装了 Rust
// 才救得回来。这是最坏的一种缺口：**代码全在、玩不了**。
//
// 四件事：
//
// 1. **产物入库**：`web-next/dist/rd_wasm.wasm` 与 `dist/wasm.json` 必须被 **git 跟踪**
//    （判据是 `git ls-files --error-unmatch`，不是"磁盘上有这个文件"—— 磁盘上有但没跟踪，
//    clone 下来照样没有）；
// 2. **两者一致**：`wasm.json.sha256` == 实际字节的 sha256（否则装载会被拒绝启动）；
// 3. **页面引用完整**：`dist/run.html` 引用的每个 `/assets/*` 都在磁盘上；
// 4. **一条命令能起**：`tools/play.ps1` 存在、能 ParseFile、并且 `serve.mjs` 的默认入口是 run。

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";

const GATE = "UI_DISTRIBUTABLE";
let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { bytes: 0, assets: 0 };

const GIT = "C:\\Program Files\\Git\\cmd\\git.exe";

/** 这个路径**被 git 跟踪**吗（磁盘上有 ≠ clone 下来有）。 */
const tracked = (path) => {
  try {
    execFileSync(GIT, ["ls-files", "--error-unmatch", path], { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
};

// ── 1. 产物入库 ────────────────────────────────────────────────────────────
const wasmPath = join("web-next", "dist", "rd_wasm.wasm");
const manifestPath = join("web-next", "dist", "wasm.json");
check(existsSync(wasmPath), "磁盘上有 dist/rd_wasm.wasm", wasmPath);
check(tracked(wasmPath), "**dist/rd_wasm.wasm 被 git 跟踪**（否则 clone 下来跑不起来）", wasmPath);
check(tracked(manifestPath), "dist/wasm.json 被 git 跟踪", manifestPath);

// ── 2. 两者一致 ────────────────────────────────────────────────────────────
const wasm = await readFile(wasmPath);
const actual = createHash("sha256").update(wasm).digest("hex");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
summary.bytes = wasm.length;
check(manifest.sha256 === actual, "入库的 wasm.json 与实际字节一致（装载时比对的就是它）", `${manifest.sha256?.slice(0, 12)} vs ${actual.slice(0, 12)}`);
check(wasm.length > 500_000, "wasm 大小合理（> 500 KB）", `${wasm.length} B`);

// ── 3. 页面引用完整 ────────────────────────────────────────────────────────
const html = await readFile(join("web-next", "dist", "run.html"), "utf8");
const assets = Array.from(html.matchAll(/(?:src|href)="\.?\/?(assets\/[^"]+)"/g)).map((match) => match[1]);
summary.assets = new Set(assets).size;
const onDisk = new Set(await readdir(join("web-next", "dist", "assets")));
const missing = [...new Set(assets)].filter((asset) => !onDisk.has(asset.replace(/^assets\//, "")));
check(missing.length === 0, `run.html 引用的 ${summary.assets} 个资源都在 dist/assets 里`, JSON.stringify(missing.slice(0, 4)));
check(onDisk.size > 3, "dist/assets 有内容（不是空目录）", String(onDisk.size));

// ── 4. 一条命令能起 ────────────────────────────────────────────────────────
const playPath = join("tools", "play.ps1");
check(existsSync(playPath), "tools/play.ps1 存在（一条命令就能玩）", playPath);
const playRaw = await readFile(playPath);
check(
  playRaw[0] === 0xef && playRaw[1] === 0xbb && playRaw[2] === 0xbf,
  "play.ps1 带 UTF-8 BOM（PS5.1 无 BOM 会按 ANSI 解码 ⇒ 中文串把语法弄坏）",
  `${playRaw[0]?.toString(16)} ${playRaw[1]?.toString(16)} ${playRaw[2]?.toString(16)}`
);
try {
  execFileSync(
    "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
    [
      "-NoProfile",
      "-Command",
      `$e=$null; $null=[System.Management.Automation.Language.Parser]::ParseFile('${process.cwd()}\\tools\\play.ps1',[ref]$null,[ref]$e); if ($e) { exit 1 } else { exit 0 }`,
    ],
    { stdio: "pipe" }
  );
  check(true, "play.ps1 能 ParseFile（语法干净）");
} catch {
  check(false, "play.ps1 能 ParseFile（语法干净）");
}

const serveSource = await readFile(join("web-next", "scripts", "serve.mjs"), "utf8");
check(
  /export const DEFAULT_ENTRY = "run";/.test(serveSource),
  "serve.mjs 的默认入口是 run（新 UI）",
  (serveSource.match(/DEFAULT_ENTRY = "[a-z]+"/) ?? [""])[0]
);
check(
  /application\/wasm/.test(serveSource),
  "serve.mjs 给 .wasm 发 application/wasm（instantiateStreaming 的前提）"
);

console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(`UI_DISTRIBUTABLE PASS wasm=${summary.bytes} tracked=2 assets=${summary.assets} play=ok`);
