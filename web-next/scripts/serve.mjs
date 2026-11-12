// 部署用的静态服务器（P7）：**正确的 MIME、正确的缓存、正确的版本一致性**。
//
// ## 为什么需要它（而不是随便 `python -m http.server`）
//
// 1. **`application/wasm`**：`WebAssembly.instantiateStreaming` 只认这个 MIME。用错 MIME 的服务器
//    （很多"一键静态服务器"把 `.wasm` 当 `application/octet-stream`）会让浏览器直接拒绝流式编译 ——
//    页面白屏，而控制台只给一句很难读的错。
// 2. **缓存**：Vite 产物的文件名带内容哈希 ⇒ `/assets/*` 可以 `immutable` 一年；
//    而 `*.html` / `wasm.json` / `rd_wasm.wasm` **不能**缓存（否则玩家拿旧 HTML 去要已经删掉的
//    hash 资源，或拿旧 wasm 配新 manifest）。
// 3. **版本一致**：`wasm.json` 里的 sha256 必须等于**这台服务器实际发出的** wasm 字节的 sha256。
//    否则"装了新 wasm 但 manifest 是旧的"这类错会一路走到玩家屏幕上。
//
// ## 两个入口
//
// * `/`            默认入口（`--entry` 决定是新的 `run.html` 还是旧的 `web/index.html`）
// * `/legacy/*`    旧入口（永远可访问：P7 要求"保留 `web/` 直到关键能力齐备"）
// * `/assets/*`    新入口的哈希资源
//
// 用法：
//   node web-next/scripts/serve.mjs --port 8080 --entry legacy   # 默认（切换前的行为）
//   node web-next/scripts/serve.mjs --port 8080 --entry run      # 切到新 UI
//
// ⚠️ 切换默认入口只是**一个参数**（默认值那行），所以回退是一次单行 revert。

import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const WEB_NEXT = join(HERE, "..");
const REPO = join(WEB_NEXT, "..");
const DIST = join(WEB_NEXT, "dist");
const WEB = join(REPO, "web");

/** 默认入口。**切换 P7 的默认入口就是改这一行**（独立 commit，单行可回退）。 */
export const DEFAULT_ENTRY = "run";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  // ⚠️ 这一行是整台服务器最重要的：`instantiateStreaming` 只认它。
  ".wasm": "application/wasm",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
};

/**
 * 缓存策略（**按"文件名里有没有内容哈希"分**，不是按扩展名猜）：
 * * `/assets/*`：Vite 的产物名带 8 位哈希 ⇒ `immutable` 一年；
 * * 其余（html / wasm / wasm.json）：`no-cache` + ETag，每次校验。
 */
export function cacheControlFor(urlPath) {
  if (urlPath.startsWith("/assets/")) return "public, max-age=31536000, immutable";
  return "no-cache";
}

export function mimeFor(urlPath) {
  return MIME[extname(urlPath).toLowerCase()] ?? "application/octet-stream";
}

/** 把 URL 路径解析成磁盘路径；越界（`..`）返回 `null`。 */
export function resolvePath(urlPath, entry = DEFAULT_ENTRY) {
  const clean = decodeURIComponent(urlPath.split("?")[0]);
  if (clean === "/" || clean === "/index.html") {
    return entry === "legacy" ? join(WEB, "index.html") : join(DIST, "run.html");
  }
  if (clean.startsWith("/legacy/")) {
    const rest = clean.slice("/legacy/".length);
    const file = normalize(join(WEB, rest));
    return file.startsWith(WEB) ? file : null;
  }
  const file = normalize(join(DIST, clean));
  return file.startsWith(DIST) ? file : null;
}

export function createStaticServer(entry = DEFAULT_ENTRY) {
  return createServer(async (req, res) => {
    const urlPath = req.url ?? "/";
    const file = resolvePath(urlPath, entry);
    if (!file) {
      res.writeHead(403).end("forbidden");
      return;
    }
    let info;
    try {
      info = await stat(file);
    } catch {
      res.writeHead(404, { "content-type": "text/plain; charset=utf-8" }).end("not found");
      return;
    }
    if (!info.isFile()) {
      res.writeHead(404).end("not found");
      return;
    }
    const headers = {
      "content-type": mimeFor(file),
      "cache-control": cacheControlFor(urlPath.split("?")[0]),
      "content-length": String(info.size),
    };
    // ETag：`no-cache` 的那些靠它做条件请求（省流量但不省一致性）。
    const etag = `"${info.size.toString(16)}-${Math.round(info.mtimeMs).toString(16)}"`;
    headers.etag = etag;
    if (req.headers["if-none-match"] === etag) {
      res.writeHead(304, headers).end();
      return;
    }
    res.writeHead(200, headers);
    createReadStream(file).pipe(res);
  });
}

/** 版本一致性：manifest 里的 sha256 必须等于**磁盘上** wasm 的 sha256。 */
export async function checkVersion() {
  const wasm = await readFile(join(DIST, "rd_wasm.wasm"));
  const actual = createHash("sha256").update(wasm).digest("hex");
  let declared = null;
  try {
    declared = JSON.parse(await readFile(join(DIST, "wasm.json"), "utf8")).sha256;
  } catch {
    declared = null;
  }
  return { actual, declared, ok: declared !== null && declared === actual, bytes: wasm.length };
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  const args = process.argv.slice(2);
  const read = (name, fallback) => {
    const index = args.indexOf(`--${name}`);
    return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
  };
  const entry = read("entry", DEFAULT_ENTRY);
  const port = Number(read("port", "8080"));
  const version = await checkVersion();
  if (!version.ok) {
    console.error(`SERVE FAIL: wasm.json 与实际 wasm 不一致（${version.declared} vs ${version.actual}）`);
    process.exit(1);
  }
  createStaticServer(entry).listen(port, () => {
    console.log(
      `serving ${entry === "legacy" ? "web/index.html（旧入口）" : "web-next/dist/run.html（新入口）"} ` +
        `on http://127.0.0.1:${port}/  ·  wasm ${version.bytes} B  ·  sha ${version.actual.slice(0, 12)}…`
    );
  });
}
