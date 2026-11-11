"""README：闸门数 27→28，加入 P2 适配器文档。"""

import io

README = 'README.md'
t = io.open(README, encoding='utf-8').read()

old = '**聚合验收**：27 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next` 与 `ui-pointer`），一道红就整体红'
new = '**聚合验收**：28 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure` 与 `ui-wasm`），一道红就整体红'
assert t.count(old) == 1, '闸门数锚点 %d' % t.count(old)
t = t.replace(old, new)

old2 = '**`ui-next-p1.md`**'
new2 = (
    '**`ui-p2-adapter.md`**（**P2 第一步：WASM 适配器**：`WasmHost`/`SnapshotReader`/'
    '`ActionDispatcher`/`GameStore` 的职责边界、148 格观察向量布局、"空槽 -1 vs 计数 0"两条坑、'
    '`_into` 参数顺序不统一等三个坑、闸门 28 的 10 条断言；单一构建产物由 '
    '`scripts/sync-wasm.mjs` 复制并记 sha256）、**`ui-next-p1.md`**'
)
assert t.count(old2) == 1, 'ui-next-p1 锚点 %d' % t.count(old2)
t = t.replace(old2, new2)

io.open(README, 'w', encoding='utf-8', newline='\n').write(t)
print('README updated')
