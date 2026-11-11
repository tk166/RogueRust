"""闸门 25 加一条"包是不是当前源码构建的"。

## 为什么

`web-next/dist/` 入库，闸门才能不需要 npm。代价是"改了 `src/` 忘了 `npm run build`"时，
闸门会去测**旧包**并报绿 —— 和 §350b 里 `--check-fixtures` 只看内容指纹是同一个形状：
**度量报的是陈旧数字**。

## 做法

构建时把 `src/` 的 sha256 烘进 bundle（`vite.config.ts` 的 `__SRC_HASH__`），
闸门用**同一份** `scripts/src-hash.mjs` 现算一遍再比对。
"""

import io

PATH = 'native/ui_next_check.mjs'
t = io.open(PATH, encoding='utf-8').read()

old = '''import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";'''
new = '''import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";
import { sourceHash } from "../web-next/scripts/src-hash.mjs";'''
assert t.count(old) == 1, 'import 锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

old = '''// ── 0. 初始局面 ────────────────────────────────────────────────────────────'''
new = '''// ── 0a. 包是不是当前源码构建的（`dist/` 入库的代价）───────────────────────
// 不查这一条，改了 `src/` 忘了 `npm run build` 就会去测旧包并报绿 ——
// 与 §350b 的 `--check-fixtures` 只比内容指纹是同一个形状。
const live = await sourceHash(new URL("../web-next/", import.meta.url).pathname.replace(/^\\/([A-Za-z]:)/, "$1"));
const built = await evaluate("({ hash: window.__p1.srcHash, files: window.__p1.srcFiles })");
check(
  built.hash === live.hash,
  "跑的是当前源码构建出来的包（dist 不是陈旧的）",
  `built=${String(built.hash).slice(0, 12)} live=${live.hash.slice(0, 12)} -- 需要 cd web-next && npm run build`
);

// ── 0. 初始局面 ────────────────────────────────────────────────────────────'''
assert t.count(old) == 1, 'section 0 锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('staleness check added')
