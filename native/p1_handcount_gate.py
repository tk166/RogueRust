"""UX-6：手牌数量夹具（1 / 3 / 12）。

## 为什么必须测

手牌数量直接改变扇形宽度与紧凑态判定：
* **1 张**：`t` 恒为 0，扇形退化成一个点（除以 `(count-1)/2` 会变成 0/0 —— 要确认没除零）；
* **12 张**：stride 掉到约 28px，全部进入紧凑态，**最右那张必须仍然点得到**；
* 3 张：中间值，确认没有"只有 10 张才对"的隐含假设。

12 张是 P1 的上限（`?debug&hand` 只接受 1..12）。正式玩法允许更多时要先扩这条规则与夹具。
"""

import io

PATH = 'native/ui_next_check.mjs'
t = io.open(PATH, encoding='utf-8').read()

old = '''await page.close();

console.log(notes.join("\\n"));'''

new = '''// ── 10. 手牌数量夹具：1 / 3 / 12（Review UX-6）──────────────────────────────
// 手牌数量改变扇形宽度与紧凑态判定；只测 10 张等于把边界全漏掉。
const handCases = [
  { count: 1, label: "1 张（扇形退化成一个点，不能除零）" },
  { count: 3, label: "3 张" },
  { count: 12, label: "12 张（上限，最右那张仍要点得到）" },
];
for (const handCase of handCases) {
  await page.send("Page.navigate", {
    url: `http://127.0.0.1:${page.port}/web-next/dist/index.html?debug&still&hand=${handCase.count}`,
  });
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    ready = await evaluate("Boolean(window.__p1 && window.__p1.ready)");
    if (ready) break;
    await sleep(100);
  }
  check(ready, `hand=${handCase.count}：页面重新就绪`);
  await waitStable(20);
  const info = await evaluate(`(() => {
    const l = window.__p1.layout();
    const hand = window.__p1.hand();
    return {
      handCount: hand.length,
      cards: l.cards.map((c) => ({
        slot: c.slot,
        x: Math.round(c.x), y: Math.round(c.y),
        top: Math.round(c.y - c.h / 2), bottom: Math.round(c.y + c.h / 2),
        hitX: Math.round(c.hitX),
        visibleW: Math.round(c.visibleW),
      })),
      regions: l.regions,
      width: l.width, height: l.height,
    };
  })()`);
  check(info.handCount === handCase.count, `${handCase.label}：手牌数量正确`, `got ${info.handCount}`);
  check(
    info.cards.length === handCase.count && Number.isFinite(info.cards[0]?.x) && Number.isFinite(info.cards[0]?.y),
    `${handCase.label}：每张牌都有有限的投影坐标（没有 NaN / 除零）`,
    JSON.stringify(info.cards.slice(0, 2))
  );
  const outside = info.cards.filter(
    (card) => card.x < 0 || card.x > info.width || card.top < 0 || card.bottom > info.height - 6
  );
  check(outside.length === 0, `${handCase.label}：每张牌的整个矩形都在视口内`, JSON.stringify(outside));
  const hitOutside = info.cards.filter((card) => card.hitX < 0 || card.hitX > info.width);
  check(hitOutside.length === 0, `${handCase.label}：每张牌的命中点都在视口内`, JSON.stringify(hitOutside));

  // 最右那张必须点得到（叠放是右压左，它本来就该在最上面）。
  const lastSlot = handCase.count - 1;
  const lastPoint = await evaluate(`(() => {
    const card = window.__p1.layout().cards.find((c) => c.slot === ${lastSlot});
    return card ? { x: card.hitX, y: card.hitY } : null;
  })()`);
  const pressedLast = await mousePress(lastPoint);
  check(
    pressedLast.phase === "pressed" && pressedLast.handSlot === lastSlot,
    `${handCase.label}：最右那张（slot ${lastSlot}）点得到`,
    JSON.stringify(pressedLast)
  );
  await mouseRelease(lastPoint);
}

// 回到默认局面，别把后续状态带走（这一段之后没有别的断言，但保持干净）。
await page.send("Page.navigate", {
  url: `http://127.0.0.1:${page.port}/web-next/dist/index.html?debug&still`,
});
await sleep(300);

await page.close();

console.log(notes.join("\\n"));'''

assert t.count(old) == 1, '锚点命中 %d 次' % t.count(old)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))
print('hand-count fixtures added')
