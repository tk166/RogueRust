// 把**同一份** wasm 产物同步进 `web-next/public/`，并记下 sha256。
//
// ## 为什么是"复制"而不是"再编译一次"
//
// 第十二轮 Review §2.5：`web-next/` 不应自己编译第二套来源不明的 WASM。内核产物只有一份
// （`kernel/` 编出来的 `web/rd_wasm.wasm`），`web-next` 只是**复制**它，并把 sha256 记进
// `public/wasm.json`，装载时比对。这样"两个二进制版本"在结构上不可能出现。
//
// 用法：`node scripts/sync-wasm.mjs`（`npm run wasm`）。闸门 28 会先跑这一步。
// `public/rd_wasm.wasm` 与 `public/wasm.json` 都**不入库**（一条 cargo 命令即可重建）。

import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const WEB_NEXT = join(HERE, "..");
const REPO = join(WEB_NEXT, "..");
const SOURCE = join(REPO, "web", "rd_wasm.wasm");
const PUBLIC = join(WEB_NEXT, "public");
const TARGET = join(PUBLIC, "rd_wasm.wasm");
const MANIFEST = join(PUBLIC, "wasm.json");

let bytes;
try {
  bytes = await readFile(SOURCE);
} catch {
  console.error(
    `SYNC_WASM FAIL: 找不到 ${SOURCE}\n` +
      "  先跑一次内核构建（验收里的 wasm-rebuild 闸门会做），或手动：\n" +
      "  cargo build -p rd-wasm --release --target wasm32-unknown-unknown"
  );
  process.exit(1);
}

const sha256 = createHash("sha256").update(bytes).digest("hex");
await mkdir(PUBLIC, { recursive: true });
await copyFile(SOURCE, TARGET);
// `dist/` 入库，但 wasm 不入库 ⇒ 已构建的产物目录也要放一份，否则闸门 28 打开页面时 404。
const DIST = join(WEB_NEXT, "dist");
try {
  await copyFile(SOURCE, join(DIST, "rd_wasm.wasm"));
} catch {
  /* 还没 build 过：build 时 vite 会把 public/ 拷进 dist/，这里只是提前一份 */
}
await writeFile(
  MANIFEST,
  JSON.stringify(
    {
      note: "复制自 web/rd_wasm.wasm（唯一构建产物）。装载时比对 sha256；不一致就拒绝启动。",
      source: "web/rd_wasm.wasm",
      bytes: bytes.length,
      sha256,
    },
    null,
    1
  ) + "\n",
  "utf8"
);
console.log(`SYNC_WASM PASS bytes=${bytes.length} sha256=${sha256.slice(0, 12)}`);
