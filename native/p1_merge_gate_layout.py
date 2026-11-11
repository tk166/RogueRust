"""闸门 25 加"版面"断言（第十三轮 Review 的 UX-3）。

## 为什么必须进闸门

审阅说"1280×800 手牌底部伸出屏幕、390px 下被底边和操作栏遮挡"。我第一版闸门只查
**卡牌中心**在视口内 —— 牌心确实在，牌身被裁掉一半它也报通过（这就是"看得见的"与
"测得到的"错位）。

现在断言三件事，全部用运行时投影出来的矩形，不写死坐标：

1. 每张牌的**整个矩形**都在视口内（不是只看中心）；
2. 竖屏下相邻敌人中心的间距 >= 两倍半径 + 8px（否则"名字+HP+意图"三行标签会压在一起）；
3. 窄屏下提示气泡的顶边在 HUD 下方（HUD 是 uikit 画的 3D，DOM 量不到，所以用
   "气泡 top >= 96" 这个布局常量 + 截图人工复核；这条是唯一带常量的断言，注释写明原因）。
"""

import io

PATH = 'native/ui_next_check.mjs'
t = io.open(PATH, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''const shotWide = await page.screenshotPng();
await writeFile(join(OUT_DIR, "1280x800-desktop.png"), shotWide);''',
    '''const shotWide = await page.screenshotPng();
await writeFile(join(OUT_DIR, "1280x800-desktop.png"), shotWide);

// ── 9. 版面：整张牌都在视口内、敌人标签不互压、气泡不压 HUD（Review UX-3）──────
// ⚠️ 只查"牌心在视口内"是不够的：牌心在、牌身被裁掉一半，第一版就是这么报绿的。
const wideLayout = await evaluate(`(() => {
  const l = window.__p1.layout();
  return {
    width: l.width, height: l.height,
    cards: l.cards.map((c) => ({ slot: c.slot, top: Math.round(c.y - c.h / 2), bottom: Math.round(c.y + c.h / 2) })),
    enemies: l.enemies.map((e) => ({ slot: e.slot, x: Math.round(e.x), y: Math.round(e.y), r: Math.round(e.r) })),
  };
})()`);
const wideOverflow = wideLayout.cards.filter(
  (card) => card.top < 0 || card.bottom > wideLayout.height - 6
);
check(
  wideOverflow.length === 0,
  `1280×800 每张牌的整个矩形都在视口内（底部留 6px）`,
  JSON.stringify(wideOverflow)
);

// 竖屏：敌人纵向单列，间距要放得下三行标签
await page.send("Emulation.setDeviceMetricsOverride", {
  width: 390,
  height: 844,
  deviceScaleFactor: 1,
  mobile: true,
});
await sleep(400);
const portraitLayout = await evaluate(`(() => {
  const l = window.__p1.layout();
  const hint = document.querySelector(".gesture-hint");
  const rect = hint ? hint.getBoundingClientRect() : null;
  return {
    width: l.width, height: l.height,
    cards: l.cards.map((c) => ({ slot: c.slot, top: Math.round(c.y - c.h / 2), bottom: Math.round(c.y + c.h / 2) })),
    enemies: l.enemies.map((e) => ({ slot: e.slot, x: Math.round(e.x), y: Math.round(e.y), r: Math.round(e.r) })),
    hintTop: rect ? Math.round(rect.top) : null,
  };
})()`);
const portraitOverflow = portraitLayout.cards.filter(
  (card) => card.top < 0 || card.bottom > portraitLayout.height - 6
);
check(
  portraitOverflow.length === 0,
  "390×844 每张牌的整个矩形都在视口内（底部留 6px）",
  JSON.stringify(portraitOverflow)
);
const sorted = portraitLayout.enemies.slice().sort((a, b) => a.y - b.y);
let tooClose = null;
for (let i = 1; i < sorted.length; i += 1) {
  const gap = Math.abs(sorted[i].y - sorted[i - 1].y);
  const need = sorted[i].r + sorted[i - 1].r + 8;
  if (gap < need) tooClose = { upper: sorted[i - 1].slot, lower: sorted[i].slot, gap, need };
}
check(tooClose === null, "竖屏相邻敌人间距放得下三行标签", JSON.stringify(tooClose));
check(
  (portraitLayout.hintTop ?? 0) >= 96,
  "窄屏提示气泡在 HUD 下方（HUD 是 uikit 的 3D 层，DOM 量不到 ⇒ 这条用布局常量）",
  `hintTop=${portraitLayout.hintTop}`
);''',
    'layout section',
)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('gate 25: layout assertions added')
