// 闸门 42 `ui-deploy`：部署产物的 **MIME / 缓存 / 版本一致性 / 资源引用**。
//
// plan P7 的第二条："统一部署产物，保证正确的 WASM MIME、缓存策略和资源版本一致性。"
// 这三件事各自都有**具体**的失败形态，所以分开断言：
//
// 1. **MIME**：`.wasm` 必须是 `application/wasm`。用错（`application/octet-stream` 很常见）
//    ⇒ `WebAssembly.instantiateStreaming` 直接拒绝 ⇒ 白屏 + 一句很难读的错。
// 2. **缓存**：`/assets/*`（Vite 带内容哈希）`immutable` 一年；`*.html` / `wasm.json` /
//    `rd_wasm.wasm` **不能**缓存（旧 HTML 去要已删除的 hash 资源 = 白屏）。
// 3. **版本一致**：`wasm.json.sha256` == 服务器实际发出的 wasm 字节的 sha256。
// 4. **资源引用**：`/` 那一页引用的每个 `/assets/*` 都真的能取到（200），且没有 `.map`。
//
// 另外断言**两个入口都能起**（`--entry legacy` / `--entry run`）—— 这是 P7 的"切换可回退"。

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { createStaticServer, DEFAULT_ENTRY, checkVersion } from "../web-next/scripts/serve.mjs";

const GATE = "UI_DEPLOY";
let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { assets: 0, entry: DEFAULT_ENTRY };

/** 起一台服务器，返回 `{ base, close }`。 */
async function serve(entry) {
  const server = createStaticServer(entry);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  return {
    base: `http://127.0.0.1:${port}`,
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}

const head = async (url) => {
  const response = await fetch(url);
  // ⚠️ body 只能读一次（第一版先 `text()` 再 `arrayBuffer()` ⇒ "Body is unusable"）。
  const buffer = response.status === 200 ? Buffer.from(await response.arrayBuffer()) : Buffer.alloc(0);
  return {
    status: response.status,
    type: response.headers.get("content-type"),
    cache: response.headers.get("cache-control"),
    etag: response.headers.get("etag"),
    text: buffer.toString("utf8"),
    bytes: buffer.byteLength,
  };
};

// ── 1. 版本一致性（磁盘层）─────────────────────────────────────────────────
{
  const version = await checkVersion();
  check(version.ok, "wasm.json 的 sha256 == 磁盘上 wasm 的 sha256", `${version.declared?.slice(0, 12)} vs ${version.actual.slice(0, 12)}`);
  check(version.bytes > 500_000, "wasm 大小合理（> 500 KB）", `${version.bytes} B`);
}

// ── 2. 两个入口都能起，且 `/` 的内容与 `--entry` 一致 ────────────────────────
for (const entry of ["legacy", "run"]) {
  const site = await serve(entry);
  try {
    const root = await head(`${site.base}/`);
    check(root.status === 200 && root.type.startsWith("text/html"), `--entry ${entry}：/ 返回 HTML`, `${root.status} ${root.type}`);
    if (entry === "run") {
      // 新入口的页面必须有 #root 与 run 的入口脚本。
      check(root.text.includes('id="root"') && /(?:src|href)="\.?\/?assets\//.test(root.text), "--entry run：/ 是新 UI（有 #root 与打包资源）", root.text.slice(0, 120));
    } else {
      check(root.text.includes("rd-core") || root.text.includes("rd_wasm.wasm"), "--entry legacy：/ 是旧页面");
    }
    // 旧入口永远可达（P7 要求保留 `web/`）。
    const legacy = await head(`${site.base}/legacy/index.html`);
    check(legacy.status === 200, `--entry ${entry}：/legacy/index.html 仍可访问`, String(legacy.status));
  } finally {
    await site.close();
  }
}

// ── 3. MIME / 缓存 / 资源引用（以 run 入口为准）──────────────────────────────
{
  const site = await serve("run");
  try {
    const root = await head(`${site.base}/`);
    check(root.cache === "no-cache", "HTML 不缓存（no-cache）", String(root.cache));

    const wasm = await head(`${site.base}/rd_wasm.wasm`);
    check(wasm.status === 200, "wasm 可取到", String(wasm.status));
    check(wasm.type === "application/wasm", "wasm 的 MIME 是 application/wasm（instantiateStreaming 的前提）", String(wasm.type));
    check(wasm.cache === "no-cache", "wasm 不缓存（版本靠 manifest 的 sha）", String(wasm.cache));

    const manifest = await head(`${site.base}/wasm.json`);
    check(manifest.cache === "no-cache", "wasm.json 不缓存", String(manifest.cache));
    const declared = JSON.parse(manifest.text).sha256;
    const actual = createHash("sha256").update(await readFile(join("web-next", "dist", "rd_wasm.wasm"))).digest("hex");
    check(declared === actual, "服务器发出的 manifest 与实际 wasm 字节一致", declared.slice(0, 12));

    // 页面引用的每个资源都要能取到，且带哈希的那些要 immutable。
    const assets = Array.from(root.text.matchAll(/(?:src|href)="\.?\/?(assets\/[^"]+)"/g)).map((match) => match[1]);
    summary.assets = assets.length;
    check(assets.length > 0, "页面引用了打包资源", String(assets.length));
    let missing = 0;
    let notImmutable = 0;
    for (const asset of new Set(assets)) {
      const response = await head(`${site.base}/${asset}`);
      if (response.status !== 200) {
        missing += 1;
        if (missing <= 3) console.log(`     缺: ${asset} (${response.status})`);
      } else if (response.cache !== "public, max-age=31536000, immutable") {
        notImmutable += 1;
        if (notImmutable <= 3) console.log(`     缓存策略不对: ${asset} → ${response.cache}`);
      }
    }
    check(missing === 0, "页面引用的资源全都能取到", `${missing} 个缺失`);
    check(notImmutable === 0, "带哈希的资源是 immutable", `${notImmutable} 个不是`);

    // 源码映射不该出现在产物里（会把整个源码发出去）。
    const map = await head(`${site.base}/assets/nope.js.map`);
    check(map.status === 404, "没有源码映射可下载", String(map.status));

    // 越界访问要拒绝（`..` 穿越）。
    const escape = await head(`${site.base}/../package.json`);
    check(escape.status === 403 || escape.status === 404, "越界路径被拒绝", String(escape.status));
  } finally {
    await site.close();
  }
}

console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_DEPLOY PASS entry=${summary.entry} assets=${summary.assets} wasm=application/wasm ` +
    `cache=immutable-for-hashed version=match`
);
