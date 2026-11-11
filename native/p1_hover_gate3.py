"""给 hover 同源断言加"牙齿"：把指针放到**敌人轮廓外、触摸半径内**。

## 为什么中间点测不出来

在敌人正中心，R3F 射线与 `enemyAtScreen` 当然一致 —— 那条断言在**旧的双源实现**下也会绿。
真正能区分的点是**边缘**：`enemyAtScreen` 的接受半径是 `r + 14`（触摸友好），而 mesh 的轮廓
就是 `r`。把指针放在 `r + 10`：

* 旧的：R3F hover 打不到 mesh ⇒ `hoveredEnemy = -1`，但 `hoverSlot = 0`（hitTest 认）⇒ **矛盾**；
* 新的：两者都由 `enemyAtScreen` 算 ⇒ 都是 0。

这条断言的价值就在这 10 个像素上。
"""

import io

PATH = 'native/ui_next_check.mjs'
t = io.open(PATH, encoding='utf-8').read()

old = '''// 移到空白（**不松开**）：两者都清空'''
new = '''// ⚠️ 牙齿：把指针放到**敌人轮廓外、触摸半径内**（`r + 10`）。
// 旧的双源实现在这里必然矛盾：R3F 射线打不到 mesh（hover=-1），而 hitTest 的接受半径是
// `r + 14`（hoverSlot=0）。中间点测不出来 —— 那条断言在旧实现下也会绿。
const enemy0Edge = await evaluate(`(() => {
  const enemy = window.__p1.layout().enemies.find((e) => e.slot === 0);
  return enemy ? { x: Math.round(enemy.x + enemy.r + 10), y: Math.round(enemy.y), r: Math.round(enemy.r) } : null;
})()`);
check(Boolean(enemy0Edge), "拿到敌人 0 的轮廓外一点");
await page.send("Input.dispatchMouseEvent", {
  type: "mouseMoved",
  x: enemy0Edge.x,
  y: enemy0Edge.y,
  button: "left",
  buttons: 1,
});
await sleep(60);
const hoverEdge = await evaluate("({ s: window.__p1.state(), h: window.__p1.hovered() })");
check(
  hoverEdge.h.enemy === 0 && hoverEdge.s.hoverSlot === 0,
  "指针在敌人轮廓外、触摸半径内：hover 与合法目标**仍然一致**（单源，旧实现会矛盾）",
  JSON.stringify({ hover: hoverEdge.h.enemy, target: hoverEdge.s.hoverSlot, at: enemy0Edge })
);

// 移到空白（**不松开**）：两者都清空'''
assert t.count(old) == 1, '命中 %d 次' % t.count(old)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))
print('edge assertion added')
