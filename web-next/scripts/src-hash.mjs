// 源码指纹：把 `src/`（+ 构建配置）的 sha256 烘进包里。
//
// ## 为什么需要
//
// `web-next/dist/` **入库**，为的是闸门 25 不需要 npm、不需要网络。代价是：改了 `src/` 却忘了
// `npm run build`，闸门会去测**旧包**并且报绿 —— 这正是"度量报陈旧数字"那一类假绿。
//
// 做法：构建时算一次指纹塞进 bundle，闸门用**同一份实现**现算一遍再比对。两边必须是同一个
// 函数（抄第二份必然漂）。

import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
export const PROJECT_ROOT = join(HERE, "..");

/** 参与指纹的文件：源码与构建配置（不含 `dist/`、`node_modules/`）。 */
const TRACKED = ["src", "index.html", "vite.config.ts", "package.json"];

async function walk(dir, out) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) await walk(full, out);
    else out.push(full);
  }
}

/** 源码树的 sha256（按相对路径排序后逐个喂进去，所以与文件系统顺序无关）。 */
export async function sourceHash(root = PROJECT_ROOT) {
  const files = [];
  for (const name of TRACKED) {
    const full = join(root, name);
    try {
      const stat = await readFile(full);
      files.push([name, stat]);
    } catch {
      const collected = [];
      await walk(full, collected);
      for (const file of collected) {
        files.push([relative(root, file).split("\\").join("/"), await readFile(file)]);
      }
    }
  }
  files.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  const hash = createHash("sha256");
  for (const [name, body] of files) {
    hash.update(name);
    hash.update("\u0000");
    hash.update(body);
    hash.update("\u0000");
  }
  return { hash: hash.digest("hex"), files: files.length };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const { hash, files } = await sourceHash();
  console.log(JSON.stringify({ srcHash: hash, files }));
}
