"""§344 页面侧：把三个"页面自己算/自己记"的东西换成内核导出。

| 现在 | 换成 | 缺口 |
|---|---|---|
| `let runOver = false;` + 5 处赋值 | `runOver()` / `runEndWhy()`（读 `rd_run_over()` / `rd_run_over_why()`） | G1 |
| `end_act: () => { runOver = true; … }` | `act(() => ex.rd_run_end_act(), "结束")` | G2 |
| `restHeal = Math.floor(hpMax * 30 / 100)` | `ex.rd_run_rest_heal()` | G9 |

## 为什么 `runOver` 要变成函数

它是**派生值**（R1："派生值读取时从状态派生，不缓存"）。缓存它的代价在这一轮之前是"5 处赋值
都要记得改"，之后是"存档回档、回放、3D 重写各自重新发明一遍"。改成函数之后，**只有一处**能回答
"这一局结束了吗"，而那一处是内核。

`runOver` 与 `runOverWhy` 原来是两个变量，两个写者（`endFight` 与 `end_act`）—— 与 `#nodePanel`
两个写者（§89/§90）同一个形状。

## 一处**行为**变化（不是纯重构）

`endFight` 原来在"战斗结果 == 2 或 血量 <= 0"时置位。现在内核说：`health <= 0` ⇒ `Defeat`。
判据一致，但**回档/回放之后**也一样成立 —— 这就是把历史换成状态的收益。
"""

import io

PAGE = 'web/index.html'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PAGE, encoding='utf-8').read()

# ── ① 变量 → 函数 ───────────────────────────────────────────────────────────
t = sub(t, '''/// The run is finished. Two ways to get here, and only one of them exists yet: **defeat** (the
/// hero's health reached 0). There is no boss encounter in this content, so a run cannot be won --
/// the end of the act says so instead of pretending.
let runOver = false;
/// Why it ended, for the summary.
let runOverWhy = "";''',
        '''/// §344（缺口 G1）：**这一局结束了吗** —— 只问内核。
///
/// 这里原来是两个模块级变量（`runOver` / `runOverWhy`），由 `endFight`（战败）与 `end_act`
/// （幕尽）两处赋值。两个变量、两个写者，与 `#nodePanel` 两个写者（`port-plan.md` §89/§90）
/// 同一个形状；而代价是"局终"成了**历史**的函数 —— 回档之后、回放里、以及任何新写的渲染层
/// 都得重新发明它。
///
/// 现在它是**派生值**：读取时问内核（R1）。`rd_run_over_why()` 的数值是 `RunEnd` 的判别值
/// （`0` 进行中 / `1` 战败 / `2` 通关 / `3` 地图走完了），**不要重排**。
const runOver = () => ex.rd_run_over() === 1;
/// 为什么结束，给摘要面板用。
function runEndWhy() {
  const why = ex.rd_run_over_why();
  if (why === 1) return `第 ${ex.rd_run_observe(0)} 层战败`;
  if (why === 2) return "通关：最后一幕的 Boss 已击败";
  if (why === 3) return `第 ${ex.rd_run_act()} 幕到此为止（地图走完了）`;
  return "";
}''', 'runOver functions')

# ── ② 快照：用函数 ──────────────────────────────────────────────────────────
t = sub(t, '''    runOver,
    runOverWhy,''',
        '''    runOver: runOver(),
    runOverWhy: runEndWhy(),''', 'snapshot')

# ── ③ 幕尽：内核动作 ────────────────────────────────────────────────────────
t = sub(t, '''  end_act: () => {
    runOver = true;
    runOverWhy = "走到第一幕尽头";
    renderNode();
  },''',
        '''  // §344（缺口 G2）：幕尽现在是一个**内核动作**（`RunState::end_act`）。它只在
  // "真的没事可做"时接受（没有待决问句 / 脚下节点已结算 / `reachable()` 为空），
  // 否则响亮拒绝 —— 于是"幕尽"进了存档、进了指纹、也进了回放脚本。
  end_act: () => act(() => ex.rd_run_end_act(), "结束这一幕"),''', 'end_act action')

# ── ④ 去掉 4 处赋值（startRun / endFight / 回档 / 回放）─────────────────────
t = sub(t, '''function startRun() {
  runOver = false;
  runOverWhy = "";
''', '''function startRun() {
  // §344：`runOver` 不再是一个要重置的变量 —— 它每次从内核读。
''', 'startRun')

t = sub(t, '''  // Defeat is the end of the run, not a return to the map: the health came back as 0 and there is
  // nothing to walk with.
  if (result === 2 || ex.rd_run_observe(2) <= 0) {
    runOver = true;
    runOverWhy = `第 ${ex.rd_run_observe(0)} 层战败`;
  }
''', '''  // §344：**不用在这里置位** —— 战败时内核的血量已经是 0，`rd_run_over()` 会给出答案。
  // （原来这里是两个写者之一：`endFight` 置"战败"、`end_act` 置"幕尽"。）
''', 'endFight')

t = sub(t, '''    // 回档换了整局：先把战斗视图收起来，再让页面按新状态重画。
    setMode("run");
    runOver = false;
    renderMap();''',
        '''    // 回档换了整局：先把战斗视图收起来，再让页面按新状态重画。
    // §344：`runOver` 从内核读，所以回档之后它自动是对的（原来要手动清 —— 而"手动清"
    // 正是"历史"的来源）。
    setMode("run");
    renderMap();''', 'archive restore')

t = sub(t, '''    setMode("run");
    runOver = false;
    renderMap();
    renderNode();
    renderTopBar();''',
        '''    setMode("run");
    renderMap();
    renderNode();
    renderTopBar();''', 'replay')

# ── ⑤ 地图点击的守卫：调用函数 ──────────────────────────────────────────────
t = sub(t, '''    if (here && mode === "run" && !runOver) {''',
        '''    if (here && mode === "run" && !runOver()) {''', 'map click here')
t = sub(t, '''    if (!group || mode !== "run" || runOver) {''',
        '''    if (!group || mode !== "run" || runOver()) {''', 'map click reachable')
t = sub(t, '''      if (node && mode === "run" && !runOver) {''',
        '''      if (node && mode === "run" && !runOver()) {''', 'map click say')

# ── ⑥ 篝火回复量：内核给数 ──────────────────────────────────────────────────
t = sub(t, '''    case 1:
      snapshot.restHeal = Math.floor((snapshot.hpMax * 30) / 100);''',
        '''    case 1:
      // §344（缺口 G9）：回复量**必须**问内核 —— `rest_heal()` 已经算上了 `regal_pillow`（+15）
      // 与 `eternal_feather`（每 5 张牌 +3），而这里原来自己写 `Math.floor(hpMax * 30 / 100)`，
      // 于是持那两件遗物时**显示的数字是错的**（显示 +24、实际 +39）。
      snapshot.restHeal = ex.rd_run_rest_heal();''', 'restHeal')
io.open(PAGE, 'w', encoding='utf-8', newline='\n').write(t)
print('§344 page: runOver()/runEndWhy(), kernel end_act, kernel rest_heal')
