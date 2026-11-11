"""闸门 27 补 `computeCombatLayout` 的纯函数测试（UX-3 的区域模型）。

## 断言什么

区域**严格有序**（HUD < 战场 < 手牌 < 操作栏），安全区会把上下两块推进来，
手牌 1..12 张时最外侧那张的外缘仍在视口内、stride 不小于紧凑态阈值，非法视口抛 `RangeError`。

这些是"版面"能作为**纯函数**被穷举的部分 —— 浏览器闸门只覆盖两种视口与三种手牌数。
"""

import io

PATH = 'native/ui_pure_check.mjs'
t = io.open(PATH, encoding='utf-8').read()

old = '''      "src/stage/formation.ts",
      "src/stage/layout.ts",'''
new = '''      "src/stage/formation.ts",
      "src/stage/combatLayout.ts",
      "src/stage/layout.ts",'''
assert t.count(old) == 1, 'compile list 锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

old = '''  const formation = await import(pathToFileURL(join(out, "stage/formation.js")).href);'''
new = '''  const formation = await import(pathToFileURL(join(out, "stage/formation.js")).href);
  const combat = await import(pathToFileURL(join(out, "stage/combatLayout.js")).href);'''
assert t.count(old) == 1, 'import 锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

old = '''  // ── 屏幕命中 ────────────────────────────────────────────────────────────'''
new = '''  // ── 版面区域模型（UX-3）────────────────────────────────────────────────
  const portraitView = { width: 390, height: 844 };
  const wideView = { width: 1280, height: 800 };
  let ordered = true;
  let outerInside = true;
  let strideOk = true;
  let finite = true;
  for (const view of [portraitView, wideView]) {
    for (const n of [1, 2, 3, 5, 10, 12]) {
      const L = combat.computeCombatLayout(view, n);
      const r = L.regions;
      if (!(r.hudTop <= r.hudBottom && r.hudBottom < r.combatTop && r.combatTop < r.combatBottom
        && r.combatBottom <= r.handBottom && r.handBottom < r.actionsTop && r.actionsTop < view.height)) {
        ordered = false;
      }
      // 最外侧那张牌的外缘必须留在视口内
      const outerEdge = L.fanSpread + combat.CARD_W / 2;
      if (outerEdge > L.halfW + 1e-6) outerInside = false;
      if (!Number.isFinite(L.fanCenterY) || !Number.isFinite(L.fanSpread)) finite = false;
      if (n > 1) {
        const pxPerWorld = combat.pxPerWorldAt(L.cameraDistance, combat.FAN_Z, view.height);
        const stridePx = ((2 * L.fanSpread) / (n - 1)) * pxPerWorld;
        // 至少露出 20px（紧凑态阈值），除非"装得下"与"露出够宽"不可兼得
        const maxStridePx = ((2 * (L.halfW * 0.98 - combat.CARD_W / 2)) / (n - 1)) * pxPerWorld;
        if (stridePx < Math.min(20, maxStridePx) - 0.5) strideOk = false;
      }
    }
  }
  check(ordered, "版面区域严格有序（HUD < 战场 < 手牌 < 操作栏），1–12 张手牌 × 两种视口");
  check(outerInside, "手牌 1–12 张时最外侧那张的外缘仍在视口内");
  check(strideOk, "手牌 1–12 张时牌与牌之间至少露出 20px（或已到可用的上限）");
  check(finite, "手牌 1 张时不除零（fanSpread / fanCenterY 都是有限值）");

  const safe = combat.computeCombatLayout({ width: 390, height: 844, safeTop: 44, safeBottom: 34 }, 10);
  check(
    safe.regions.hudBottom === 44 + 86 && safe.regions.actionsTop === 844 - 34 - 56,
    "安全区把 HUD 往下推、把操作栏往上推",
    JSON.stringify(safe.regions)
  );

  let threwViewport = false;
  try {
    combat.computeCombatLayout({ width: 0, height: 844 }, 10);
  } catch (error) {
    threwViewport = error instanceof RangeError;
  }
  check(threwViewport, "非法视口（宽 0）⇒ RangeError");

  // ── 屏幕命中 ────────────────────────────────────────────────────────────'''
assert t.count(old) == 1, 'screen-hit 锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

old = '''  console.log(`UI_PURE PASS formation=0..6 hit=5 machine=4`);'''
new = '''  console.log(`UI_PURE PASS formation=0..6 hit=5 machine=4 layout=6`);'''
assert t.count(old) == 1, 'evidence 锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('layout pure tests added')
