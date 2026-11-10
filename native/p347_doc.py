"""§347 文档：场景表变成可执行 + §7b 更正（18 个 + 覆盖层规则）。"""

import io

DOC = 'docs/ui-state-model.md'
PLAN = 'docs/port-plan.md'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(DOC, encoding='utf-8').read()

# ── ① §1 表头：声明它是**可执行**的 ────────────────────────────────────────
t = sub(t, '''**排序原则**：**强状态优先** —— 越"不可协商"的事实越靠前（没有局 → 正在打 → 欠账 → 终局 →
具体的 `pending` → 预备战斗 → 兜底）。判定式尽量**互斥**；每条都必须只用内核事实（§341 之前
SC-03/SC-03b 做不到，因为"未开始"是页面自己记的标志）。''',
        '''**排序原则**：**强状态优先** —— 越"不可协商"的事实越靠前（没有局 → 正在打 → 欠账 → 终局 →
具体的 `pending` → 预备战斗 → 兜底）。每条都必须只用内核事实（§341 之前 SC-03/SC-03b 做不到，
因为"未开始"是页面自己记的标志）。

> **§347：这张表现在是代码。** `web/ui_panels.js` 的 `SCENES` 数组与它逐行对应，**数组顺序就是
> 优先级**；`classifyScene(snapshot)` 取第一条命中的，`describe()` 按它分派（不再有第二份顺序）。
> `web/ui_test.mjs` 有 **18 个夹具**，每个断言"命中预期的那一个"+"恰好命中一个"（覆盖层例外）。
> 下面每一行的判定式就是数组里那条 `test`。''',
        'section 1 executable note')

# ── ② §7b 更正：18 个 + 覆盖层规则 + 互斥由构造保证 ────────────────────────
t = sub(t, '''所以 §1 那张表还欠一份**可执行的**东西：19 个场景各一份 `snapshot` 夹具，断言
`classifyScene(snapshot)` **唯一命中**；多重命中或零命中都要**报错**，不是"取第一个"。
（`web/ui_panels.js` 的 `describe()` 已经是这张表的实现，`web/ui_test.mjs` 用字面量 snapshot
逐状态测 —— 但那是**页面**的版本，不是"这张表"的版本。3D 重写时应当先写 `classifyScene`，
再写渲染。）''',
        '''### 7b. 场景表已经是可执行的（§347）

`web/ui_panels.js` 的 `SCENES` 数组就是 §1 那张表：**数组顺序即优先级**，
`classifyScene()` 取第一条命中的，`describe()` 按它分派。`web/ui_test.mjs` 有 **18 个夹具**
（§1 是 18 行），每个断言三件事：

1. `classifyScene` 命中**预期的那一个**；
2. **恰好命中一个**（`scenesMatching` 的全部命中）—— **覆盖层例外**；
3. `SCENES` 的顺序被**字面量**钉住（顺序即语义，改一行就红）。

⚠️ 原文写的是"19 个场景"和"多重命中一律报错"，两处都错：

* 表里是 **18** 行（早先的草稿多算了一个）；
* **覆盖层**（SC-11a / SC-11b）按定义**叠在**别的屏上（§3.13：遗物欠账可以压着奖励屏），
  所以它们与底下那一屏**同时命中是正确的**。判据要求的是"**基础**场景唯一"。

### 7c. 为什么"手写否定式"这条路是错的

兜底场景（SC-02）的谓词手写过两次，两次都漏：

1. 只写 `pending === 0` ⇒ 它是上面所有 `pending === 0` 场景的**超集**；
2. 补上 `!preFight && !mapExhausted` 之后，`runOver` / `cleared` 的夹具又同时命中它。

两次的表现一样：**两个场景同时命中**，而 `classifyScene` 取第一条 ⇒ **顺序把错误藏起来**。
所以现在改成**构造即互斥**：`RAW` 里每条只写自己的条件，包装层给每个**基础**场景加上
"前面没有任何基础场景命中"（覆盖层不参与）。于是新增一个场景不需要回来改兜底。

⇒ 一般教训：**"优先级 + 兜底"这种结构，兜底不能手写否定式，要由构造保证。**''',
        'section 7b/7c')
io.open(DOC, 'w', encoding='utf-8', newline='\n').write(t)

# ── ③ port-plan §347 ─────────────────────────────────────────────────────
SECTION = """
## §347 场景表变成可执行：`classifyScene` + 18 个夹具

`ui-state-model.md` §7b 的欠账。那张 18 行的表说"判定式按优先级从上到下，先成立的赢"，
但**没有任何东西执行它** —— 于是表里排错一行只有读文档的人能发现，`describe()` 里那串
`if/switch` 是**第二份**同样的顺序，两份会漂。

### 一份顺序：`SCENES` 数组

```js
const RAW = [
  { id: "SC-00",  overlay: false, test: (s) => !!s.noRun },
  { id: "SC-03b", overlay: false, test: (s) => !!s.inFight },
  { id: "SC-11a", overlay: true,  test: (s) => s.pickupPicks > 0 },
  ... 18 条，顺序即优先级
  { id: "SC-02",  overlay: false, test: () => true },   // 兜底：无条件
];
```

`describe()` 不再自己判顺序，它 `switch (classifyScene(s))`。于是"这一屏是什么"只有一处。

### ★ 兜底不能手写否定式（这条值一节）

SC-02 的谓词手写过两次，两次都漏：

1. 只写 `pending === 0` ⇒ 它是上面所有 `pending === 0` 场景的**超集**（`preFight` 的夹具同时命中
   SC-03 与 SC-02）；
2. 补上 `!preFight && !mapExhausted` ⇒ `runOver` / `cleared` 的夹具又同时命中它。

两次的表现一样：**两个场景同时命中**，而 `classifyScene` 取第一条 ⇒ **顺序把错误藏起来**。

现在的做法是**构造即互斥**：`RAW` 每条只写自己的条件，包装层给每个**基础**场景加上
"前面没有任何基础场景命中"（覆盖层不参与）。于是新增一个场景不需要回来改兜底，
而"第一条命中"与"唯一命中"是同一件事。

### 判据（`web/ui_test.mjs` 的 `scene table` 段）

18 个夹具，每个断言：命中预期的那一个、**恰好命中一个**（覆盖层例外）、`SCENES` 的顺序被
**字面量**钉住。外加"夹具覆盖了每一个 id"（少一个 = 那个场景从没被验证过）与
"`describe()` 对 18 个夹具都返回一份面板描述"（SC-02b 必须给 `end_act`、SC-03 必须给
`begin_fight`）。

负控 **4/4**（`native/p347_negative.py`）：

| # | 弄坏什么 | 谁红 |
|---|---|---|
| ① | SC-02（兜底）与 SC-02b 换位（旧文档表的错） | **顺序字面量**（比夹具更早） |
| ② | 去掉互斥包装层 | `base scenes must be unique` |
| ③ | SC-03b 与 SC-03 换位 | 顺序字面量 |
| ④ | SC-04 的条件放宽到 `pending === 5`（语义碰撞，顺序没变） | **面板测试**（`describe` 就按分类器分派） |

⚠️ 负控第一版有两条不合格，原因值得记：① 的变异太宽（兜底变无条件 ⇒ 吞掉了 SC-03 之后
**所有**场景，红在别的断言上）；③ **根本红不了** —— 互斥包装层已经保证"SC-03b 命中时 SC-03
不再命中"，所以 `!inFight` 现在是**冗余的守卫**（留着是文档价值，不是判据价值）。

### 两个新字段（都是内核事实）

`classifyScene` 要两个页面快照里原来没有的东西：

| 字段 | 来源 | 用途 |
|---|---|---|
| `noRun` | `rd_run_seed() === i32::MIN` | SC-00（原来靠 `pending === -1` 间接判断） |
| `inFight` | `rd_run_in_fight() === 1`（§341） | SC-03 与 SC-03b 的分界（原来靠页面的 `mode`） |

### 数字

JS 侧改动，Rust 测试数不变：`rd-core 819 / rd-run 225 / rd-wasm 189`、units **1233**；
`UI_RENDER PASS`（多一行 `scene table`）、`BROWSER_TEST PASS`；23/23 闸门。
"""

p = io.open(PLAN, encoding='utf-8').read()
assert '## §347' not in p
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(p.rstrip('\n') + '\n' + SECTION)
print('ui-state-model §1/§7b/§7c + port-plan §347')
