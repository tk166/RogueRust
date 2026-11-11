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

// ── 1b. 同一张牌打同一个敌人**两次**（§352 P1-A）──────────────────────────
// payload 完全相同，所以"按内容去重"会把第二次吞掉。事件身份必须是**第几次发生**。
const grabbedAgain = await mouseDrag(strikeAt, enemy1At);
check(
  grabbedAgain.phase === "pressed" && grabbedAgain.handSlot === 0,
  "第二次按下仍命中的是第 0 张牌",
  JSON.stringify(grabbedAgain)
);
commits = await evaluate("window.__p1.commits()");
check(commits.length === 2, "同样的动作做两次 ⇒ 两次提交（不被内容去重吞掉）", `commits=${commits.length}`);
const afterRepeat = await evaluate("window.__p1.enemies()");
check(afterRepeat[1].hp === 32, "敌人 1 掉了两次血（44 → 38 → 32）", JSON.stringify(afterRepeat));

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
check(commits.length === 2, "非法释放没有产生提交", `commits=${commits.length}`);
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
check(commits.length === 3, "无目标牌在空白处释放也提交", `commits=${commits.length}`);
check(commits.at(-1)?.targetSlot === -1, "无目标牌的 targetSlot 是 -1", JSON.stringify(commits.at(-1)));
const blockAfter = (await evaluate("window.__p1.hero()")).block;
check(blockAfter === blockBefore + 5, "防御牌真的加了 5 点格挡", `${blockBefore} -> ${blockAfter}`);

// ── 3b. 无目标牌释放在**敌人身上**（§352 P1-B）────────────────────────────
// 物理落点是敌人 0，但业务目标永远是 -1。旧实现拿物理落点去查选项 ⇒ 查不到 ⇒ 误回弹，
// 而 `decide()` 判的是 commit —— 判定与执行互相矛盾。
const enemy0At = await enemyPoint(0);
const beforeUntargetedOnEnemy = await evaluate("window.__p1.hero()");
const grabbedOnEnemy = await mouseDrag(defendAt, enemy0At);
check(
  grabbedOnEnemy.phase === "pressed" && grabbedOnEnemy.handSlot === 1,
  "第三次按下仍命中的是第 1 张牌（防御）",
  JSON.stringify(grabbedOnEnemy)
);
commits = await evaluate("window.__p1.commits()");
check(commits.length === 4, "无目标牌丢在敌人身上也提交（不误判回弹）", `commits=${commits.length}`);
check(
  commits.at(-1)?.targetSlot === -1,
  "无目标牌丢在敌人身上，业务目标仍是 -1",
  JSON.stringify(commits.at(-1))
);
const afterUntargetedOnEnemy = await evaluate("window.__p1.hero()");
check(
  afterUntargetedOnEnemy.block === beforeUntargetedOnEnemy.block + 5,
  "这一次也真的加了 5 点格挡（不是只记了一笔提交）",
  `${beforeUntargetedOnEnemy.block} -> ${afterUntargetedOnEnemy.block}`
);

// ── 3c. hover 与合法目标同源（本轮修的"两个来源"）────────────────────────
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

// ⚠️ 牙齿：把指针放到**敌人轮廓外、触摸半径内**（`r + 10`）。
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

// ── 3d. 点选路径（不拖拽）：按下同一张牌原地松开 ⇒ targeting；再点敌人 ⇒ 提交 ──
// 敌人身上的 onPointerUp 已被拆掉（落点统一由 window.pointerup 算），这条路必须实测。
const tapAt = await cardPoint(0);
const tapPress = await mousePress(tapAt);
check(
  tapPress.phase === "pressed" && tapPress.handSlot === 0,
  "点选路径：按下第 0 张牌",
  JSON.stringify(tapPress)
);
await mouseRelease(tapAt); // 原地松开 ⇒ 位移 0 ⇒ 点按语义
const afterTap = await evaluate("window.__p1.state()");
check(
  afterTap.phase === "targeting",
  "点选路径：原地松开后进入 targeting（未出牌）",
  JSON.stringify(afterTap)
);
const commitsBeforeTapTarget = (await evaluate("window.__p1.commits()")).length;
await page.send("Input.dispatchMouseEvent", {
  type: "mousePressed",
  x: enemy1At.x,
  y: enemy1At.y,
  button: "left",
  buttons: 1,
  clickCount: 1,
});
await page.send("Input.dispatchMouseEvent", {
  type: "mouseReleased",
  x: enemy1At.x,
  y: enemy1At.y,
  button: "left",
  buttons: 0,
  clickCount: 1,
});
await sleep(80);
commits = await evaluate("window.__p1.commits()");
check(
  commits.length === commitsBeforeTapTarget + 1 && commits.at(-1)?.targetSlot === 1,
  "点选路径：再点敌人 1 ⇒ 提交到敌人 1",
  JSON.stringify(commits.at(-1))
);

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

// ── UX-2：紧凑态的文字必须落在**露出来那条**的中心（hitX），不是牌心 ─────────
// 叠放顺序是右压左，牌心可能被右邻盖住 —— 文字放牌心等于把费用数字塞到邻居底下。
const anchorDrift = await evaluate(`(() => {
  const cards = window.__p1.layout().cards;
  const bySlot = new Map(cards.map((c) => [c.slot, c]));
  const worst = [];
  for (const node of document.querySelectorAll("[data-card]")) {
    if (!node.classList.contains("is-compact")) continue;
    const slot = Number(node.dataset.card);
    const screen = bySlot.get(slot);
    if (!screen) continue;
    const rect = node.getBoundingClientRect();
    worst.push({ slot, drift: Math.round(Math.abs((rect.left + rect.right) / 2 - screen.hitX)) });
  }
  return worst;
})()`);
check(anchorDrift.length > 0, "紧凑态至少有一张牌（否则这条断言没有样本）", JSON.stringify(anchorDrift));
check(
  anchorDrift.every((item) => item.drift <= 2),
  "紧凑态文字锚点落在露出条中心（与 hitX 偏差 <= 2px）",
  JSON.stringify(anchorDrift)
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
    regions: l.regions,
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

// 敌人必须整个落在**战场区**里（`regions.combatTop..combatBottom`）—— 这是区域模型
// 真正被用上的地方：队形若把敌人推进 HUD 或手牌区，这条会红。
const combatStrays = portraitLayout.regions
  ? portraitLayout.enemies.filter((enemy) => {
      const top = enemy.y - enemy.r;
      const bottom = enemy.y + enemy.r;
      return top < portraitLayout.regions.combatTop || bottom > portraitLayout.regions.combatBottom;
    })
  : [];
check(
  portraitLayout.regions !== null && combatStrays.length === 0,
  "竖屏敌人整个落在战场区内（regions.combatTop..combatBottom）",
  JSON.stringify({ strays: combatStrays, regions: portraitLayout.regions })
);
// 手牌底边不许越过操作栏
const handOverrun = portraitLayout.regions
  ? portraitLayout.cards.filter((card) => card.bottom > portraitLayout.regions.actionsTop)
  : [];
check(
  portraitLayout.regions !== null && handOverrun.length === 0,
  "竖屏手牌底边不越过操作栏（regions.actionsTop）",
  JSON.stringify({ overrun: handOverrun, actionsTop: portraitLayout.regions?.actionsTop })
);
// ⚠️ 对比的是 `computeCombatLayout().regions.hudBottom`（**同一个**函数算出来的），
// 不是硬编码常数 —— 否则提示条位置与断言又成了"两份认识"。
// uikit 的 HUD 是 3D 画的、DOM 量不到，所以模型与真机的一致性靠截图人工复核。
check(
  portraitLayout.regions !== null && (portraitLayout.hintTop ?? 0) >= portraitLayout.regions.hudBottom,
  "窄屏提示气泡在 HUD 下方（对比 regions.hudBottom）",
  `hintTop=${portraitLayout.hintTop}, hudBottom=${portraitLayout.regions?.hudBottom}`
);

// ── 10. 手牌数量夹具：1 / 3 / 12（Review UX-6）──────────────────────────────
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
  // ⚠️ 判据是"这一页真的换成 hand=N 了"，不是"有个探针在"：导航未提交时
  // `window.__p1` 还是**旧页面**的，照着它判断会对着旧布局断言。
  let ready = false;
  for (let attempt = 0; attempt < 150; attempt += 1) {
    ready = await evaluate(
      `Boolean(window.__p1 && window.__p1.ready && window.__p1.hand().length === ${handCase.count}` +
        ` && window.__p1.layout().frames > 10)`
    );
    if (ready) break;
    await sleep(100);
  }
  check(ready, `hand=${handCase.count}：页面重新就绪（手牌数已切换）`);
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
  check(Boolean(lastPoint), `${handCase.label}：拿到最右那张的命中点`);
  const pressedLast = lastPoint ? await mousePress(lastPoint) : { phase: "missing", handSlot: -1 };
  check(
    pressedLast.phase === "pressed" && pressedLast.handSlot === lastSlot,
    `${handCase.label}：最右那张（slot ${lastSlot}）点得到`,
    JSON.stringify(pressedLast)
  );
  if (lastPoint) await mouseRelease(lastPoint);
}

// 回到默认局面，别把后续状态带走（这一段之后没有别的断言，但保持干净）。
await page.send("Page.navigate", {
  url: `http://127.0.0.1:${page.port}/web-next/dist/index.html?debug&still`,
});
await sleep(300);

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
