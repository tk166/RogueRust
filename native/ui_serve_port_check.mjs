// 闸门 53 `ui-serve-port`：**端口被占用时必须换端口，而且要说清**（§375）。
//
// ## 真实的坑（用户实测）
//
// `tools/play.ps1` 打印 `http://127.0.0.1:8080/` 并说 "serving … run.html"，
// 但浏览器打开 8080 看到的是 **Steam**（`Inspectable WebContents` / `欢迎来到 Steam`）。
//
// 原因是 Windows 的绑定语义：Node 的 `listen(8080)`（不给 host）绑 `::`（双栈全接口），
// Steam 的 CEF 调试端口绑在 `127.0.0.1:8080` —— **两者能同时绑成功**，而浏览器连
// `127.0.0.1` 时命中更具体的那个（Steam）。于是"启动成功"而用户看到别人的页面。
//
// ## 三道判据
//
// 1. **绑 127.0.0.1**（源码断言）：与打印出来的 URL 同一个地址，端口被占时 `EADDRINUSE`
//    才会真的发生；
// 2. **占用时自动换端口并明说**（行为断言）：先占住一个端口，再起服务器，它必须
//    ① 提示端口被占、② 换到**另一个**端口、③ 打印的是**真实**端口；
// 3. **自检"这个端口答的是不是我"**（行为断言）：抓它打印的 URL，GET 一次，必须含 `id="root"`。
//
// 第 3 条是关键：它让"别人的服务在这个端口上应答"永远不可能被当成成功。

import { execFileSync, spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

const GATE = "UI_SERVE_PORT";
let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { fallback: 0, port: 0 };

const serveSource = await readFile(join("web-next", "scripts", "serve.mjs"), "utf8");
const playSource = await readFile(join("tools", "play.ps1"), "utf8");

// ── 1. 源码：绑 127.0.0.1 + 有自检 + 有占用回退 ────────────────────────────
check(
  /host:\s*"127\.0\.0\.1"/.test(serveSource),
  "serve.mjs 绑 **127.0.0.1**（与打印的 URL 同一地址；绑 :: 会与 Steam 共存）",
  (serveSource.match(/host:\s*"[^"]+"/) ?? [""])[0]
);
check(
  /body\.includes\('id="root"'\)/.test(serveSource),
  "serve.mjs 起来之后**自检**自己的页面（`id=\"root\"`）"
);
check(/EADDRINUSE/.test(serveSource), "serve.mjs 认 EADDRINUSE 并回退端口");
check(
  !/Write-Host "▶ http:\/\/127\.0\.0\.1:\$Port\//.test(playSource),
  "play.ps1 **不预打印** URL（端口可能被换掉，预打印的地址会指向别人的服务）"
);

// ── 2. 行为：占住一个端口，再起服务器 ──────────────────────────────────────
const squatter = createServer((_request, response) => {
  response.writeHead(200, { "content-type": "text/html" }).end("<html><body>Steam-like squatter</body></html>");
});
await new Promise((resolve) => squatter.listen(0, "127.0.0.1", resolve));
const busyPort = squatter.address().port;

const child = spawn(process.execPath, [join("web-next", "scripts", "serve.mjs"), "--port", String(busyPort)], {
  cwd: process.cwd(),
  stdio: ["ignore", "pipe", "pipe"],
});
let output = "";
child.stdout.on("data", (chunk) => {
  output += String(chunk);
});
child.stderr.on("data", (chunk) => {
  output += String(chunk);
});

/** 等到输出里出现 `on http://127.0.0.1:<port>/`，或者超时。 */
const actualPort = await (async () => {
  const started = Date.now();
  while (Date.now() - started < 15000) {
    const match = /on http:\/\/127\.0\.0\.1:(\d+)\//.exec(output);
    if (match) return Number(match[1]);
    if (child.exitCode !== null) return null;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return null;
})();

try {
  check(actualPort !== null, "服务器起来了并打印了**真实**端口", String(actualPort));
  check(actualPort !== busyPort, "端口被占 ⇒ 换到了**另一个**端口", `${busyPort} → ${actualPort}`);
  check(
    output.includes("已被占用") || output.includes("EADDRINUSE"),
    "换端口**说清了原因**（不是静默换）",
    output.split("\n").find((line) => line.includes("占用")) ?? ""
  );
  check(
    /原定 \d+ 被占用/.test(output),
    "打印的那行还标出原定端口被占用",
    output.split("\n").find((line) => line.includes("serving")) ?? ""
  );
  summary.fallback = 1;
  summary.port = actualPort ?? 0;

  // ── 3. 自检：那个端口答的确实是我们的页面 ────────────────────────────────
  if (actualPort !== null) {
    const response = await fetch(`http://127.0.0.1:${actualPort}/`);
    const body = await response.text();
    check(response.status === 200, "新端口返回 200", String(response.status));
    check(body.includes('id="root"'), "新端口答的是**我们的**页面（有 #root）", `${body.length} 字节`);
    check(
      !body.includes("Steam"),
      "新端口答的**不是** Steam（用户遇到的那个现象）"
    );
    const wasm = await fetch(`http://127.0.0.1:${actualPort}/rd_wasm.wasm`);
    check(
      wasm.headers.get("content-type") === "application/wasm",
      "换端口之后 wasm 的 MIME 仍然正确",
      String(wasm.headers.get("content-type"))
    );
  }

  // ── 4. 占位者仍然在自己的端口上应答（我们没抢它）────────────────────────
  const squatterBody = await (await fetch(`http://127.0.0.1:${busyPort}/`)).text();
  check(squatterBody.includes("Steam-like squatter"), "被占的端口仍然由占位者应答（没抢）");
} finally {
  child.kill();
  await new Promise((resolve) => squatter.close(resolve));
}

console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(`UI_SERVE_PORT PASS fallback=${summary.fallback} port=${summary.port} selfcheck=ok`);
