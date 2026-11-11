"""闸门 25 的三处硬化：
① 每条拖拽先断言"抓住了正确的那张牌"（负控要有牙：不然"没抓住"和"被拒绝"分不开）；
② 选中态改成**按住不放**再截图（第一版先释放，牌早就回位了）；
③ 可读性改成**不变量**：每张牌要么标题读得到，要么明确收起为紧凑态。
"""

import io

PATH = 'native/ui_next_check.mjs'
t = io.open(PATH, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''/** 鼠标：按下 → 移动 → 抬起（真实 `Input.dispatchMouseEvent`，浏览器会合成 pointer 事件）。 */
async function mouseDrag(from, to, { steps = 6 } = {}) {
  await page.send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: from.x,
    y: from.y,
    button: "left",
    buttons: 1,
    clickCount: 1,
  });
  for (let step = 1; step <= steps; step += 1) {''',
    '''/**
 * 鼠标：按下（返回**按下之后**的状态机快照）。
 *
 * 为什么要返回它：第一版闸门只看"提交数变没变"，于是"根本没抓住牌"与"抓住了但被拒绝"
 * 分不开 —— 一条本该红的检查因此假绿（§4.16 的老形状：负控没匹配上也报通过）。
 * 现在每条负控先断言"确实进入了 pressed 且 handSlot 是我要的那张"。
 */
async function mousePress(point) {
  await page.send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: point.x,
    y: point.y,
    button: "left",
    buttons: 1,
    clickCount: 1,
  });
  await sleep(60);
  return evaluate("window.__p1.state()");
}

async function mouseRelease(point) {
  await page.send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: point.x,
    y: point.y,
    button: "left",
    buttons: 0,
    clickCount: 1,
  });
  await sleep(80);
}

/** 按下 → 移动（**不抬起**）：用来停在"选中/拖拽"态观察可读性。 */
async function mouseHold(from, to, { steps = 6 } = {}) {
  const pressed = await mousePress(from);
  for (let step = 1; step <= steps; step += 1) {
    const ratio = step / steps;
    await page.send("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: from.x + (to.x - from.x) * ratio,
      y: from.y + (to.y - from.y) * ratio,
      button: "left",
      buttons: 1,
    });
    await sleep(16);
  }
  await sleep(120);
  return pressed;
}

/** 鼠标：按下 → 移动 → 抬起（真实 `Input.dispatchMouseEvent`，浏览器会合成 pointer 事件）。 */
async function mouseDrag(from, to, { steps = 6 } = {}) {
  const pressed = await mousePress(from);
  for (let step = 1; step <= steps; step += 1) {''',
    'mousePress/mouseHold',
)

sub(
    '''    await sleep(16);
  }
  await page.send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: to.x,
    y: to.y,
    button: "left",
    buttons: 0,
    clickCount: 1,
  });
  await sleep(60);
}''',
    '''    await sleep(16);
  }
  await mouseRelease(to);
  return pressed;
}''',
    'mouseDrag tail',
)

sub(
    '''const strikeAt = await cardPoint(0);
const enemy1At = await enemyPoint(1);
check(Boolean(strikeAt && enemy1At), "拿到第 0 张牌与敌人 1 的屏幕坐标");
await mouseDrag(strikeAt, enemy1At);''',
    '''const strikeAt = await cardPoint(0);
const enemy1At = await enemyPoint(1);
check(Boolean(strikeAt && enemy1At), "拿到第 0 张牌与敌人 1 的屏幕坐标");
const grabbed = await mouseDrag(strikeAt, enemy1At);
check(
  grabbed.phase === "pressed" && grabbed.handSlot === 0,
  "按下命中的是第 0 张牌",
  JSON.stringify(grabbed)
);''',
    'grab assert strike',
)

sub(
    '''const beforeIllegal = await evaluate("window.__p1.enemies()");
await mouseDrag(bashAt, empty);''',
    '''const beforeIllegal = await evaluate("window.__p1.enemies()");
const grabbedIllegal = await mouseDrag(bashAt, empty);
check(
  grabbedIllegal.phase === "pressed" && grabbedIllegal.handSlot === 2,
  "按下命中的是第 2 张牌（痛击）",
  JSON.stringify(grabbedIllegal)
);''',
    'grab assert bash',
)

sub(
    '''const blockBefore = (await evaluate("window.__p1.hero()")).block;
await mouseDrag(defendAt, empty);''',
    '''const blockBefore = (await evaluate("window.__p1.hero()")).block;
const grabbedDefend = await mouseDrag(defendAt, empty);
check(
  grabbedDefend.phase === "pressed" && grabbedDefend.handSlot === 1,
  "按下命中的是第 1 张牌（防御）",
  JSON.stringify(grabbedDefend)
);''',
    'grab assert defend',
)

sub(
    '''  const commitsBefore = (await evaluate("window.__p1.commits()")).length;
  await mouseDrag(loneAt, empty);
  commits = await evaluate("window.__p1.commits()");''',
    '''  const commitsBefore = (await evaluate("window.__p1.commits()")).length;
  const grabbedLone = await mouseDrag(loneAt, empty);
  check(
    grabbedLone.phase === "pressed" && grabbedLone.handSlot === 3,
    "按下命中的是第 3 张牌（铁斩）",
    JSON.stringify(grabbedLone)
  );
  commits = await evaluate("window.__p1.commits()");''',
    'grab assert lone',
)

# ── 可读性：改成不变量 ─────────────────────────────────────────────────────
old_read = '''const readability = await evaluate(`(() => {
  const inView = [];
  for (const card of window.__p1.layout().cards) {
    inView.push({ slot: card.slot, x: Math.round(card.x), y: Math.round(card.y) });
  }
  const titles = Array.from(document.querySelectorAll("[data-title]"));
  const fonts = titles.map((node) => parseFloat(getComputedStyle(node).fontSize));
  const clipped = titles
    .filter((node) => node.scrollWidth > node.clientWidth + 1)
    .map((node) => node.textContent);
  return {
    cards: inView.length,
    minTitle: Math.min(...fonts),
    clipped,
    offscreen: inView.filter((card) => card.x < 0 || card.x > 390 || card.y < 0 || card.y > 844).length,
  };
})()`);'''
new_read = '''const readability = await evaluate(`(() => {
  const cards = window.__p1.layout().cards;
  const inView = cards.map((card) => ({ slot: card.slot, x: Math.round(card.x), y: Math.round(card.y) }));
  const nodes = Array.from(document.querySelectorAll("[data-card]"));
  const per = nodes.map((node) => {
    const title = node.querySelector("[data-title]");
    const cost = node.querySelector(".card-text__cost");
    const compact = node.classList.contains("is-compact");
    const titleVisible = Boolean(title) && getComputedStyle(title).display !== "none";
    return {
      compact,
      titleVisible,
      titleFont: titleVisible ? parseFloat(getComputedStyle(title).fontSize) : 0,
      titleClipped: titleVisible ? title.scrollWidth > title.clientWidth + 1 : false,
      costFont: parseFloat(getComputedStyle(cost).fontSize),
      costClipped: cost.scrollWidth > cost.clientWidth + 1,
    };
  });
  const shown = per.filter((card) => card.titleVisible);
  return {
    cards: cards.length,
    minVisibleW: Math.min(...cards.map((card) => Math.round(card.visibleW))),
    compactCount: per.filter((card) => card.compact).length,
    badCards: per
      .map((card, index) => ({ index, ...card }))
      .filter((card) => card.titleVisible && (card.titleFont < 11 || card.titleClipped))
      .map((card) => card.index),
    minTitle: shown.length ? Math.min(...shown.map((card) => card.titleFont)) : 0,
    costOk: per.every((card) => card.costFont >= 11 && !card.costClipped),
    offscreen: inView.filter((card) => card.x < 0 || card.x > 390 || card.y < 0 || card.y > 844).length,
  };
})()`);'''
sub(old_read, new_read, 'readability probe')

sub(
    '''check(readability.cards === 10, "窄屏下 10 张牌都在", `got ${readability.cards}`);
check(readability.offscreen === 0, "没有卡牌跑到视口外", `${readability.offscreen} 张在视口外`);
check(readability.minTitle >= 11, "手牌态标题字号 >= 11px", `min=${readability.minTitle}px`);
check(readability.clipped.length === 0, "手牌态标题没有被裁切", JSON.stringify(readability.clipped));''',
    '''check(readability.cards === 10, "窄屏下 10 张牌都在", `got ${readability.cards}`);
check(readability.offscreen === 0, "没有卡牌跑到视口外", `${readability.offscreen} 张在视口外`);
check(
  readability.badCards.length === 0,
  "每张牌要么标题可读（>=11px 且不裁切），要么明确收起为紧凑态",
  JSON.stringify(readability.badCards)
);
check(readability.costOk, "每张牌的费用数字都读得到（>=11px 且不裁切）");
check(
  readability.compactCount >= 5,
  "窄屏下多数牌收起为紧凑态（390px 放不下 10 个中文标题的实测结论）",
  `compact=${readability.compactCount}/10, minVisibleW=${readability.minVisibleW}px`
);''',
    'readability asserts',
)

sub(
    '''const selectedAt = await cardPoint(5);
await mouseDrag(selectedAt, { x: selectedAt.x, y: selectedAt.y - 120 }, { steps: 4 });
await sleep(200);''',
    '''const selectedAt = await cardPoint(5);
const grabbedSelected = await mouseHold(selectedAt, { x: selectedAt.x, y: selectedAt.y - 120 }, { steps: 4 });
check(
  grabbedSelected.phase === "pressed" && grabbedSelected.handSlot === 5,
  "按下命中的是第 5 张牌（顺劈）",
  JSON.stringify(grabbedSelected)
);''',
    'selected hold',
)

sub(
    '''const shotSelected = await page.screenshotPng();
await writeFile(join(OUT_DIR, "390x844-selected.png"), shotSelected);''',
    '''const shotSelected = await page.screenshotPng();
await writeFile(join(OUT_DIR, "390x844-selected.png"), shotSelected);
// 观察完再释放（抬起在空白处 ⇒ 回弹，局面不变）
await mouseRelease({ x: selectedAt.x, y: selectedAt.y - 120 });''',
    'selected release after shot',
)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('gate hardened')
