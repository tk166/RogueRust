import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { sourceHash } from "./scripts/src-hash.mjs";

// `base: "./"` 让 `dist/index.html` 用相对路径引用资源：闸门 25 用一个静态服务器把
// `web-next/dist/` 挂在仓库根下（`/web-next/dist/index.html`），相对路径才不会 404。
//
// ⚠️ `__SRC_HASH__`：把源码指纹烘进包里。`dist/` 入库（闸门不需要 npm），代价是
// "改了 src 忘了 build ⇒ 闸门测旧包还报绿"。闸门用 `scripts/src-hash.mjs` 现算一遍再比对。
const { hash: srcHash, files } = await sourceHash();

export default defineConfig({
  base: "./",
  plugins: [react()],
  define: {
    __SRC_HASH__: JSON.stringify(srcHash),
    __SRC_FILES__: JSON.stringify(files),
  },
  build: {
    target: "es2022",
    outDir: "dist",
    rollupOptions: {
      // 两个入口：主页面（3D UI）与 P2 的 ABI 接线探针页。
      input: {
        main: "index.html",
        p2: "p2.html",
      },
    },
    // 不内联：把每个 chunk 的字节数留在产物里，好让"压缩传输体积"是个**量出来的**数字。
    assetsInlineLimit: 0,
    sourcemap: false,
  },
});
