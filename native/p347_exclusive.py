"""§347 第二版：**构造即互斥** —— 每个基础场景的谓词都加上"前面没人命中"。

## 为什么要这样

手写否定式漏了两次：

1. `SC-02` 只写 `pending === 0` ⇒ 它是上面所有 `pending === 0` 场景的**超集**；
2. 补上 `!preFight && !mapExhausted` 之后，`runOver` / `cleared` 的夹具又同时命中 `SC-02`。

两次的表现一样：**两个场景同时命中**，而 `classifyScene` 取第一条 ⇒ 顺序把错误藏起来。
这正是 §7b 要抓的形状，也说明"手写否定式"这条路本身是错的。

## 正解

把 `SCENES` 分成两层：

* `RAW`：每个场景只写**自己的**条件（含兜底 `() => true`）；
* `SCENES`：包一层 —— 基础场景额外要求"**前面没有任何基础场景命中**"，覆盖层原样通过。

于是：

* 基础场景**按构造互斥**，新增一个场景不需要回来改兜底；
* 覆盖层（SC-11a / SC-11b）仍然与底屏共命中 —— 它们按定义就是叠着的；
* `classifyScene` 仍是"第一条命中"，但它与"唯一命中"现在是同一件事。
"""

import io

PANELS = 'web/ui_panels.js'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PANELS, encoding='utf-8').read()

OLD_HEAD = '''  /// 兜底场景的壳（`test` 在数组建好之后填 —— 它要问"上面有没有人命中"）。
  const FALLBACK = { id: "SC-02", overlay: false, test: () => true };

  const SCENES = ['''

NEW_HEAD = '''  /// 场景表：**数组顺序就是优先级**（与 `ui-state-model.md` §1 的表格逐行对应）。
  ///
  /// 每条只写**自己的**条件；"前面没人命中"由下面的 `SCENES` 统一加上（构造即互斥）。
  const RAW = ['''

t = sub(t, OLD_HEAD, NEW_HEAD, 'RAW head')

OLD_TAIL = '''    // 18 地图（兜底）。谓词在数组建好之后**算出来** —— 见下面 `FALLBACK.test`。
    FALLBACK,
  ];

  // 兜底 = **上面一条都不成立**。
  //
  // ⚠️ 为什么不是手写否定式：手写过两次，两次都漏（`pending === 0` 是超集；
  // 补上 `!preFight && !mapExhausted` 之后又漏了 `runOver`）。而"漏一个"的表现是
  // **两个场景同时命中**，顺序把这件事藏起来 —— 正是 §7b 要抓的形状。
  // 现在它由构造保证：新增一个场景不需要回来改兜底。
  FALLBACK.test = (s) => !SCENES.some((other) => other !== FALLBACK && other.test(s));'''

NEW_TAIL = '''    // 18 地图（兜底）：无条件 —— "前面一条都没命中"由包装层保证。
    { id: "SC-02", overlay: false, test: () => true },
  ];

  // 包装层：**构造即互斥**。
  //
  // 基础场景额外要求"**前面没有任何基础场景命中**"（覆盖层不参与这个判断，它们按定义叠着）。
  // 这样 `classifyScene` 的"第一条命中"与"唯一命中"是同一件事 —— 而手写否定式做不到：
  // 它漏过两次（`pending === 0` 是超集；补上之后又漏了 `runOver`），两次的表现都是
  // "两个场景同时命中"，而顺序把错误藏起来。
  const SCENES = RAW.map((entry, index) => {
    if (entry.overlay) return entry;
    return {
      ...entry,
      test: (s) =>
        !RAW.slice(0, index).some((earlier) => !earlier.overlay && earlier.test(s)) &&
        entry.test(s),
    };
  });'''

t = sub(t, OLD_TAIL, NEW_TAIL, 'SCENES wrapper')

# 顺手去掉兜底那条已经没用的手写否定注释里的 `preFight` 提法（保留函数本身，它还被别处用）
io.open(PANELS, 'w', encoding='utf-8', newline='\n').write(t)
print('§347: RAW + 构造即互斥的包装层')
