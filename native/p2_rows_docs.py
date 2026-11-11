"""port-plan §360：横屏队形的退化修正（n≤4 一排）。"""

import io

PLAN = 'docs/port-plan.md'
DOC = 'docs/ui-p2-adapter.md'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


t = io.open(PLAN, encoding='utf-8').read()
anchor = '''### 残留

- **X 费扣能量**没有真夹具（见上）；'''
assert t.count(anchor) == 1

addition = '''---

## §360 横屏队形：`n ≤ 4` 只用一排（截图抓到的退化）

**现象**：`docs/ui-p2-real/1280x800-wasm.png` 是横屏（1280×800），但两个怪**上下叠在一条竖线**上，
看起来像竖屏。是不是 §353 的迁移腐坏了？

**不是腐坏**。参考包 `computeCombatFormation` 横屏写的是 `ceil(n/2)` / `floor(n/2)`：

* `n = 2` ⇒ 上行 1 名、下行 1 名；
* 而"每排只有一名"时 `rowX(index, count)` 直接返回同一个 `mid` ⇒ 两个怪 x 相同、y 不同
  ⇒ **竖着叠**。

也就是说这条公式在小数量下退化，横屏的"两排"语义只在 `n ≥ 5` 才成立（4 时是 2+2，
也是两排但每排两名 —— 视觉上还行，但用户指出 `n ≤ 4` 应该只有一排）。

**修法**：`upperCount = n ≤ 4 ? n : ceil(n/2)`，`lowerCount = n - upperCount`；
只有一排时**竖直居中**（`y = 0`，否则一排会贴在战场上半部）。

| n | 排布 |
|---|---|
| 1–4 | 一排（1 / 2 / 3 / 4） |
| 5 | 3 + 2 |
| 6 | 3 + 3 |

**闸门当时为什么没抓到**：`ui_pure_check.mjs` 断言的是 `upper === ceil(n/2) && lower === floor(n/2)`
—— 把**错的规则**验证了一遍。这正是"断言测的是我以为的规则，不是应该的规则"。

现在换成新规则，并加了四条退化守卫：
横屏 n=2 必须**同一排**（`row` 全 0）、x 明显分开（> 0.5）、y 相同；n=4 也只用一排；n=5 必须 3+2。
证据串加 `rows=4`。

### 数字

闸门 31 不变；`ui-pure` 证据 `rows=4`；截图 `docs/ui-p2-real/1280x800-wasm.png` 重新生成
（两个怪左右并排、竖直居中）；units 1233、导出 234、四条对拍不动。

### 残留

- **X 费扣能量**没有真夹具（见上）；'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))

edit(
    DOC,
    '''## 6. 还没做的''',
    '''## 5d. 横屏队形的退化（§360）

截图里横屏两个怪上下叠着，看着像竖屏。查下来**不是迁移腐坏**：参考包横屏用 `ceil(n/2)` /
`floor(n/2)`，`n = 2` 时"每排各一名"，而每排只有一名时 `rowX` 返回同一个 `mid` ⇒ x 相同、y 不同
⇒ 竖着叠。这条公式在小数量下退化。

改成 `n ≤ 4` 只用一排（`n > 4` 才 `ceil/floor`），只有一排时竖直居中。闸门 27 原来断言的正是
`ceil/floor` —— 等于把错的规则验证了一遍；现在换成新规则并加了四条退化守卫（n=2 同排、x 分开、
y 相同；n=4 一排；n=5 是 3+2），证据串加 `rows=4`。

## 6. 还没做的''',
    'doc 5d',
)
print('docs updated')
