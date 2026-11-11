"""修正 3c：用**定向牌**验"同源"，用**无目标牌**验"两个不同问题"，并用 Esc 验取消。

## 上一版错在哪

我拿"耸肩"（**无目标牌**）去断言 `hoveredEnemy === hoverSlot`，于是红了。但那不是 bug：
无目标牌的合法集合本来就是空的 ⇒ `hoverSlot` 必须是 -1，而指针确实压在敌人 0 上 ⇒
`hoveredEnemy` 是 0。**这正是"两个不同问题、由同一个命中函数回答"的正确表现**：
* `hoveredEnemy`：指针下是谁（任意敌人，视觉用）
* `hoverSlot`：指针下是不是**合法目标**（提交与绿环用）

所以断言要分两种牌来写，否则测的是我自己的误解。

顺带把 `Escape` 取消也测上（Review P1-D 要求"取消不提交"）。
"""

import io

PATH = 'native/ui_next_check.mjs'
t = io.open(PATH, encoding='utf-8').read()

start = t.index('// ── 3c. hover 与合法目标同源')
end = t.index('// ── 3d. 点选路径')

replacement = '''// ── 3c. hover 与合法目标同源（本轮修的"两个来源"）────────────────────────
// 以前 hover 来自 R3F 射线、提交来自 hitTest，几何不同（真 mesh vs 半径 +14px）⇒ 边缘自相矛盾。
// 现在两者都由 `enemyAtScreen` 回答，只是喂的**允许集合**不同（任意 vs 合法）。
const hoverCardAt = await cardPoint(8); // 柄击：**定向**牌
const grabbedHover = await mouseHold(hoverCardAt, enemy0At, { steps: 4 });
check(
  grabbedHover.phase === "pressed" && grabbedHover.handSlot === 8,
  "按下命中的是第 8 张牌（柄击）",
  JSON.stringify(grabbedHover)
);
const hoverState = await evaluate("({ s: window.__p1.state(), h: window.__p1.hovered() })");
check(
  hoverState.h.enemy === 0 && hoverState.s.hoverSlot === 0,
  "定向牌拖到敌人 0 上方：视觉 hover 与合法目标是**同一个**敌人",
  JSON.stringify(hoverState)
);

// 移到空白（**不松开**）：两者都清空
await page.send("Input.dispatchMouseEvent", {
  type: "mouseMoved",
  x: empty.x,
  y: empty.y,
  button: "left",
  buttons: 1,
});
await sleep(60);
const hoverEmpty = await evaluate("({ s: window.__p1.state(), h: window.__p1.hovered() })");
check(
  hoverEmpty.h.enemy === -1 && hoverEmpty.s.hoverSlot === -1,
  "移到空白处：hover 与合法目标都清空",
  JSON.stringify(hoverEmpty)
);
await mouseRelease(empty); // 定向牌在空白处 ⇒ 回弹，不提交

// 无目标牌压在敌人上：**hover 命中、但不是合法目标** —— 两个不同的问题，同一个函数回答。
const shrugAt = await cardPoint(7); // 耸肩：**无目标**牌
const grabbedShrug = await mouseHold(shrugAt, enemy0At, { steps: 4 });
check(
  grabbedShrug.phase === "pressed" && grabbedShrug.handSlot === 7,
  "按下命中的是第 7 张牌（耸肩）",
  JSON.stringify(grabbedShrug)
);
const shrugHover = await evaluate("({ s: window.__p1.state(), h: window.__p1.hovered() })");
check(
  shrugHover.h.enemy === 0 && shrugHover.s.hoverSlot === -1,
  "无目标牌压在敌人上：hover 命中，但它不是合法目标（不是两个来源）",
  JSON.stringify(shrugHover)
);

// Esc 取消：不提交、清空 hover（Review P1-D 的"取消不提交"）
const commitsBeforeEsc = (await evaluate("window.__p1.commits()")).length;
await page.send("Input.dispatchKeyEvent", {
  type: "keyDown",
  key: "Escape",
  code: "Escape",
  windowsVirtualKeyCode: 27,
  nativeVirtualKeyCode: 27,
});
await page.send("Input.dispatchKeyEvent", {
  type: "keyUp",
  key: "Escape",
  code: "Escape",
  windowsVirtualKeyCode: 27,
  nativeVirtualKeyCode: 27,
});
await sleep(80);
const afterEsc = await evaluate("({ s: window.__p1.state(), h: window.__p1.hovered(), c: window.__p1.commits() })");
check(
  afterEsc.s.phase === "idle" && afterEsc.c.length === commitsBeforeEsc,
  "Esc 取消：回到 idle 且不提交",
  JSON.stringify({ phase: afterEsc.s.phase, commits: afterEsc.c.length })
);
check(afterEsc.h.enemy === -1, "Esc 取消：hover 也清空", JSON.stringify(afterEsc.h));

'''

t = t[:start] + replacement + t[end:]
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('3c rewritten')
