// 闸门 25 `ui-next`：P1 的 R3F PoC 必须证明的事。
//
// 为什么用真浏览器 + 真指针事件，而不是"调一下状态机函数"：
// P1 的退出条件写的是"**选中具体卡牌 → 指向正确敌人 → 释放**；取消/非法释放回弹；移动端触摸
// 完成同样操作"。这三条都**只有**在"射线命中 → 状态机 → 权威动作"整条链真的通了才成立。
// 直接调 `reduce()` 会绕开射线、绕开 R3F 的事件派发、绕开 DOM 覆盖层 —— 那三处恰恰是
// 3D UI 最容易坏的地方（第十二轮 Review P1-C 的同一条教训：别把"局部单测"当"整链证明"）。
//
// 判据一律是**探针读到的语义**（`window.__p1`），不是 DOM 结构：牌是 mesh，没有 DOM 可点。
// 位置来自 3D 侧每帧投影出来的 `layout`，所以闸门"用渲染器自己的坐标系按下去"。
//
// 证据串（`acceptance.ps1` 抓的就是它）：
//   UI_NEXT PASS cards=10 enemies=2 commit=N rebound=M touch=T modal=1 ...

import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";
import { sourceHash } from "../web-next/scripts/src-hash.mjs";

const GATE = "UI_NEXT";
const OUT_DIR = "docs/ui-next-p1";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const notes = [];
function check(ok, label, detail = "") {
  if (ok) {
    notes.push(`  ok   ${label}`);
  } else {
    failures += 1;
    notes.push(`  FAIL ${label}${detail ? ` -- ${detail}` : ""}`);
  }
  return ok;
}

const page = await openPage({
  page: "web-next/dist/index.html",
  query: "debug&still",
  gate: GATE,
  waitFor: "Boolean(window.__p1 && window.__p1.ready)",
});

const evaluate = (expression) => page.evaluate(expression);

/** 等布局稳定：投影帧数够多、且 10 张牌都离开了入场起点。 */
async function waitStable(minFrames = 30) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const state = await evaluate(`(() => {
      const p = window.__p1;
      const l = p.layout();
      return { frames: l.frames, cards: l.cards.length, enemies: l.enemies.length,
               ys: l.cards.map((c) => Math.round(c.y)), w: l.width, h: l.height };
    })()`);
    if (state.frames >= minFrames && state.cards === 10 && state.enemies === 2 && state.ys.every((y) => y > -100)) {
      return state;
    }
    await sleep(50);
  }
  throw new Error("layout never stabilised");
}

/**
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
  for (let step = 1; step <= steps; step += 1) {
    const t = step / steps;
    await page.send("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: from.x + (to.x - from.x) * t,
      y: from.y + (to.y - from.y) * t,
      button: "left",
      buttons: 1,
    });
    await sleep(16);
  }
  await mouseRelease(to);
  return pressed;
}

/** 触摸：`Input.dispatchTouchEvent`（同一套状态机，不同的事件源）。 */
async function touchDrag(from, to, { steps = 6 } = {}) {
  await page.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: from.x, y: from.y, id: 1 }],
  });
  for (let step = 1; step <= steps; step += 1) {
    const t = step / steps;
    await page.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t, id: 1 }],
    });
    await sleep(16);
  }
  await page.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  await sleep(80);
}

/**
 * 一张牌的**命中点**（`hitX/hitY`，不是牌心）。
 *
 * 叠放顺序单调时牌心可能被右邻盖住 —— 按牌心会命中隔壁那张（第一版就这么错了，
 * 而且因为只看"提交数变没变"而**假绿**过一轮）。命中点由布局给出。
 */
async function cardPoint(slot) {
  return evaluate(`(() => {
    const card = window.__p1.layout().cards.find((c) => c.slot === ${slot});
    return card ? { x: card.hitX, y: card.hitY } : null;
  })()`);
}

async function enemyPoint(slot) {
  return evaluate(`(() => {
    const enemy = window.__p1.layout().enemies.find((e) => e.slot === ${slot});
    return enemy ? { x: enemy.x, y: enemy.y } : null;
  })()`);
}

/** 一个"肯定在空白处"的点：视口顶部 12%（HUD 下面、敌人上面）。 */
async function emptyPoint() {
  const layout = await evaluate("window.__p1.layout()");
  return { x: Math.round(layout.width / 2), y: Math.round(layout.height * 0.13) };
}

// ── 0a. 包是不是当前源码构建的（`dist/` 入库的代价）───────────────────────
// 不查这一条，改了 `src/` 忘了 `npm run build` 就会去测旧包并报绿 ——
// 与 §350b 的 `--check-fixtures` 只比内容指纹是同一个形状。
const live = await sourceHash(new URL("../web-next/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const built = await evaluate("({ hash: window.__p1.srcHash, files: window.__p1.srcFiles })");
check(
  built.hash === live.hash,
  "跑的是当前源码构建出来的包（dist 不是陈旧的）",
  `built=${String(built.hash).slice(0, 12)} live=${live.hash.slice(0, 12)} -- 需要 cd web-next && npm run build`
);

// ── 0. 初始局面 ────────────────────────────────────────────────────────────
const first = await waitStable();
check(first.cards === 10, "10 张手牌", `got ${first.cards}`);
check(first.enemies === 2, "2 个敌人", `got ${first.enemies}`);
const hand = await evaluate("window.__p1.hand()");
check(hand.length === 10 && hand.every((card) => card.name && card.rules), "每张牌都有中文名与规则文本");
const initialHero = await evaluate("window.__p1.hero()");
check(initialHero.energy === 3, "初始能量 3", `got ${initialHero.energy}`);

// ── 1. 鼠标：定向牌 → 正确敌人 → 提交 ──────────────────────────────────────
const strikeAt = await cardPoint(0);
const enemy1At = await enemyPoint(1);
check(Boolean(strikeAt && enemy1At), "拿到第 0 张牌与敌人 1 的屏幕坐标");
const grabbed = await mouseDrag(strikeAt, enemy1At);
check(
  grabbed.phase === "pressed" && grabbed.handSlot === 0,
  "按下命中的是第 0 张牌",
  JSON.stringify(grabbed)
);
let commits = await evaluate("window.__p1.commits()");
check(commits.length === 1, "拖动并释放后恰好 1 次提交", `got ${commits.length}`);
check(commits[0]?.targetSlot === 1, "打的是**敌人 1**（不是就近的那个）", JSON.stringify(commits[0]));
check(commits[0]?.card === "strike", "打的是 strike", JSON.stringify(commits[0]));
const afterStrike = await evaluate("window.__p1.enemies()");
check(afterStrike[1].hp === 38 && afterStrike[0].hp === 32, "只有敌人 1 掉血（44 → 38）", JSON.stringify(afterStrike));

// ── 2. 鼠标：非法释放（空白处）必须回弹，且不改局面 ─────────────────────────
const bashAt = await cardPoint(2);
const empty = await emptyPoint();
const beforeIllegal = await evaluate("window.__p1.enemies()");
const grabbedIllegal = await mouseDrag(bashAt, empty);
check(
  grabbedIllegal.phase === "pressed" && grabbedIllegal.handSlot === 2,
  "按下命中的是第 2 张牌（痛击）",
  JSON.stringify(grabbedIllegal)
);
commits = await evaluate("window.__p1.commits()");
const rebounds = await evaluate("window.__p1.rebounds()");
check(commits.length === 1, "非法释放没有产生提交", `commits=${commits.length}`);
check(rebounds.includes("illegal-target"), "回弹理由是 illegal-target", JSON.stringify(rebounds));
const afterIllegal = await evaluate("window.__p1.enemies()");
check(JSON.stringify(beforeIllegal) === JSON.stringify(afterIllegal), "回弹后局面一个字节都没变");

// ── 3. 无目标牌：释放到空白处 = 出牌 ───────────────────────────────────────
const defendAt = await cardPoint(1);
const blockBefore = (await evaluate("window.__p1.hero()")).block;
const grabbedDefend = await mouseDrag(defendAt, empty);
check(
  grabbedDefend.phase === "pressed" && grabbedDefend.handSlot === 1,
  "按下命中的是第 1 张牌（防御）",
  JSON.stringify(grabbedDefend)
);
commits = await evaluate("window.__p1.commits()");
check(commits.length === 2, "无目标牌在空白处释放也提交", `commits=${commits.length}`);
check(commits[1]?.targetSlot === -1, "无目标牌的 targetSlot 是 -1", JSON.stringify(commits[1]));
const blockAfter = (await evaluate("window.__p1.hero()")).block;
check(blockAfter === blockBefore + 5, "防御牌真的加了 5 点格挡", `${blockBefore} -> ${blockAfter}`);

// ── 4. 只剩一个敌人时，定向牌仍**必须**落在敌人身上（与旧页面的有意分歧）──
const hasDebug = await evaluate("Boolean(window.__p1.debug)");
check(hasDebug, "`?debug` 钩子存在（造单敌局面用）");
if (hasDebug) {
  await evaluate("window.__p1.debug.setEnemyHp(0, 0)");
  await sleep(80);
  const loneAt = await cardPoint(3); // 铁斩：定向
  const commitsBefore = (await evaluate("window.__p1.commits()")).length;
  const grabbedLone = await mouseDrag(loneAt, empty);
  check(
    grabbedLone.phase === "pressed" && grabbedLone.handSlot === 3,
    "按下命中的是第 3 张牌（铁斩）",
    JSON.stringify(grabbedLone)
  );
  commits = await evaluate("window.__p1.commits()");
  check(
    commits.length === commitsBefore,
    "只剩一个敌人时，定向牌丢在空白处**仍然回弹**（旧 `actionFor` 会直接打出去）",
    `commits=${commits.length}`
  );
  // 落到那个唯一敌人身上则必须成功。
  const liveAt = await enemyPoint(1);
  await mouseDrag(loneAt, liveAt);
  commits = await evaluate("window.__p1.commits()");
  check(commits.length === commitsBefore + 1, "落到唯一敌人身上则提交", `commits=${commits.length}`);
  check(commits[commits.length - 1]?.targetSlot === 1, "目标是敌人 1", JSON.stringify(commits.at(-1)));
  await evaluate("window.__p1.debug.setEnemyHp(0, 32)");
  await sleep(80);
}

// ── 5. 触摸：同一套状态机 ─────────────────────────────────────────────────
const twinAt = await cardPoint(6);
const enemy0At = await enemyPoint(0);
const beforeTouch = (await evaluate("window.__p1.commits()")).length;
await touchDrag(twinAt, enemy0At);
commits = await evaluate("window.__p1.commits()");
check(commits.length === beforeTouch + 1, "触摸拖动也能提交", `commits=${commits.length}`);
check(commits.at(-1)?.targetSlot === 0, "触摸打的是敌人 0", JSON.stringify(commits.at(-1)));

// ── 6. 模态：输入隔离 ─────────────────────────────────────────────────────
await evaluate("window.__p1.setModal(true)");
await sleep(120);
const commitsBeforeModal = (await evaluate("window.__p1.commits()")).length;
const anyCard = await cardPoint(4);
await mouseDrag(anyCard, enemy0At);
const phaseInModal = (await evaluate("window.__p1.state()")).phase;
commits = await evaluate("window.__p1.commits()");
check(phaseInModal === "idle", "模态打开时按下卡牌不进入 pressed", `phase=${phaseInModal}`);
check(commits.length === commitsBeforeModal, "模态打开时拖牌不产生提交", `commits=${commits.length}`);
await evaluate("window.__p1.setModal(false)");
await sleep(120);

// ── 7. 中文可读性：390×844（P1 的最大视觉风险，第十二轮 Review D3）─────────
await page.send("Emulation.setDeviceMetricsOverride", {
  width: 390,
  height: 844,
  deviceScaleFactor: 2,
  mobile: true,
});
await sleep(400);
const narrow = await waitStable(20);
check(narrow.w === 390 && narrow.h === 844, "视口切到 390×844", `${narrow.w}x${narrow.h}`);

const readability = await evaluate(`(() => {
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
})()`);
check(readability.cards === 10, "窄屏下 10 张牌都在", `got ${readability.cards}`);
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
);

await mkdir(OUT_DIR, { recursive: true });
const shotHand = await page.screenshotPng();
await writeFile(join(OUT_DIR, "390x844-hand.png"), shotHand);

// 选中态：抬起后标题放大、规则文本出现且不被裁切
const selectedAt = await cardPoint(5);
const grabbedSelected = await mouseHold(selectedAt, { x: selectedAt.x, y: selectedAt.y - 120 }, { steps: 4 });
check(
  grabbedSelected.phase === "pressed" && grabbedSelected.handSlot === 5,
  "按下命中的是第 5 张牌（顺劈）",
  JSON.stringify(grabbedSelected)
);
const selectedMetrics = await evaluate(`(() => {
  const rules = document.querySelector("[data-rules]");
  const title = document.querySelector(".card-text.is-selected [data-title]");
  if (!rules || !title) return { present: false };
  return {
    present: true,
    titleFont: parseFloat(getComputedStyle(title).fontSize),
    rulesFont: parseFloat(getComputedStyle(rules).fontSize),
    clippedV: rules.scrollHeight > rules.clientHeight + 1,
    clippedH: rules.scrollWidth > rules.clientWidth + 1,
    text: rules.textContent,
  };
})()`);
check(selectedMetrics.present, "选中态出现了规则文本");
check((selectedMetrics.rulesFont ?? 0) >= 12, "选中态规则字号 >= 12px", `got ${selectedMetrics.rulesFont}`);
check(selectedMetrics.clippedV === false && selectedMetrics.clippedH === false, "选中态规则文本没有被裁切");
const shotSelected = await page.screenshotPng();
await writeFile(join(OUT_DIR, "390x844-selected.png"), shotSelected);
// 观察完再释放（抬起在空白处 ⇒ 回弹，局面不变）
await mouseRelease({ x: selectedAt.x, y: selectedAt.y - 120 });

// 详情态：点开一张牌，看"完整描述"这一档
await evaluate("window.__p1.setModal(false)");
await evaluate(`window.__p1.openDetail(9)`);
await sleep(200);
const detailMetrics = await evaluate(`(() => {
  const title = document.querySelector("[data-detail-title]");
  const rules = document.querySelector("[data-detail-rules]");
  if (!title || !rules) return { present: false };
  return {
    present: true,
    titleFont: parseFloat(getComputedStyle(title).fontSize),
    rulesFont: parseFloat(getComputedStyle(rules).fontSize),
    clippedV: rules.scrollHeight > rules.clientHeight + 1,
    clippedH: rules.scrollWidth > rules.clientWidth + 1,
    text: rules.textContent,
  };
})()`);
check(detailMetrics.present, "详情态出现了完整规则文本");
check((detailMetrics.titleFont ?? 0) >= 20, "详情态标题字号 >= 20px", `got ${detailMetrics.titleFont}`);
check((detailMetrics.rulesFont ?? 0) >= 14, "详情态规则字号 >= 14px", `got ${detailMetrics.rulesFont}`);
check(detailMetrics.clippedV === false && detailMetrics.clippedH === false, "详情态规则文本没有被裁切");
const shotDetail = await page.screenshotPng();
await writeFile(join(OUT_DIR, "390x844-detail.png"), shotDetail);
await evaluate("window.__p1.openDetail(-1)");

// ── 8. 帧率（headless 软件光栅：**记录，不作判据**）────────────────────────
const fpsNarrow = await evaluate("window.__p1.fps(1200)");
await page.send("Emulation.setDeviceMetricsOverride", {
  width: 1280,
  height: 800,
  deviceScaleFactor: 1,
  mobile: false,
});
await sleep(300);
const fpsWide = await evaluate("window.__p1.fps(1200)");
await mkdir(OUT_DIR, { recursive: true });
const shotWide = await page.screenshotPng();
await writeFile(join(OUT_DIR, "1280x800-desktop.png"), shotWide);

await page.close();

console.log(notes.join("\n"));
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} check(s) failed`);
  process.exit(1);
}
const finalCommits = commits.length;
console.log(
  `UI_NEXT PASS cards=10 enemies=2 commits=${finalCommits} rebound=${rebounds.length} ` +
    `touch=1 modal-isolation=1 minTitle=${readability.minTitle}px ` +
    `selected=${selectedMetrics.titleFont}/${selectedMetrics.rulesFont}px ` +
    `detail=${detailMetrics.titleFont}/${detailMetrics.rulesFont}px ` +
    `fps390=${fpsNarrow.toFixed(0)} fps1280=${fpsWide.toFixed(0)}`
);
