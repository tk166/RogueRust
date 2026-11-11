"""修装载校验：`memory` 是对象，不是函数。

`REQUIRED_EXPORTS` 一律按 `typeof === "function"` 检查，而 `memory` 是 `WebAssembly.Memory`
实例 —— 于是"导出齐全"这条对**每一份** wasm 都报缺 `memory`（闸门 28 第一次跑就撞上）。

修法：函数导出与 `memory` 分开检查（`memory` 要有 `buffer`，否则读不了观察向量）。
"""

import io

PATH = 'web-next/src/wasm/host.ts'
t = io.open(PATH, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''/** 本文件真的会调用的导出。少一个就没法工作，所以算"必须存在"。 */
const REQUIRED_EXPORTS = [
  "memory",
  "rd_content_fingerprint",''',
    '''/**
 * 本文件真的会调用的**函数**导出。少一个就没法工作，所以算"必须存在"。
 *
 * ⚠️ `memory` 不在这张表里：它是 `WebAssembly.Memory` **对象**，按"必须是函数"检查会
 * 对每一份 wasm 都报缺 `memory`。单独检查（见 `validate`）。
 */
const REQUIRED_EXPORTS = [
  "rd_content_fingerprint",''',
    'required list',
)

sub(
    '''  const missing = REQUIRED_EXPORTS.filter((name) => typeof ex[name] !== "function");
  if (missing.length) problems.push(`缺少导出：${missing.join(", ")}`);''',
    '''  const missing = REQUIRED_EXPORTS.filter((name) => typeof ex[name] !== "function");
  if (missing.length) problems.push(`缺少函数导出：${missing.join(", ")}`);
  // `memory` 是对象：没有它就读不到观察向量（页面唯一的读法）。
  const memory = ex.memory as WebAssembly.Memory | undefined;
  if (!memory || !(memory.buffer instanceof ArrayBuffer)) {
    problems.push("缺少导出：memory（或者它不是 WebAssembly.Memory）");
  }''',
    'memory check',
)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('memory check fixed')
