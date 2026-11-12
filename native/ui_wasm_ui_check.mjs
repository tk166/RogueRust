// 闸门 29 `ui-wasm-ui`：**主页面接真 wasm 之后，UI 与内核一致**。
//
// 闸门 28 证明的是"适配器对"（对着 p2.html 的探针），这道闸门证明的是"**渲染层**对"：
// 主页面默认走真 wasm，于是可以断言
//   * 屏幕上的敌人血量 == 内核观察向量里的血量；
//   * 从 UI 拖一张牌出去 ⇒ 内核接受 ⇒ **DOM 上的血量跟着变**（不是只改了内存里的 view）；
//   * 能量与手牌数同步变化；
//   * 结束回合后时间前进。
//
// 这是 plan P2 退出条件"行动后 HP/能量/手牌与内核一致"的直接落地。

import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_WASM_UI";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};

// 自包含：先确保 web-next 里有一份 wasm（与闸门 28 同样的理由）。
const { execFileSync } = await import("node:child_process");
try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch (error) {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  console.error(String(error.stdout ?? "") + String(error.stderr ?? ""));
  process.exit(1);
}

const page = await openPage({
  page: "web-next/dist/index.html",
  query: "still",
  gate: GATE,
  waitFor: "Boolean(window.__p1 && window.__p1.ready)",
});
const evaluate = (expression) => page.evaluate(expression);

// 固定视口：证据截图要可复现（与闸门 25 同样的理由）。
await page.send("Emulation.setDeviceMetricsOverride", {
  width: 1280,
  height: 800,
  deviceScaleFactor: 1,
  mobile: false,
});
await sleep(300);

// ── 0. 默认就是 wasm，并且真的装好了 ──────────────────────────────────────
let mode = null;
let diagnostics = null;
for (let attempt = 0; attempt < 150; attempt += 1) {
  const state = await evaluate(
    "({ mode: window.__p1.mode(), diag: window.__p1.wasmDiagnostics(), err: window.__p1.wasmError(), view: window.__p1.view() })"
  );
  mode = state.mode;
  diagnostics = state.diag;
  if (state.err) {
    check(false, "wasm 装载没有报错", state.err);
    break;
  }
  // ⚠️ 判据必须是"视图真的来自内核"：装载期间视图是**空局面**（mode 也是 wasm），
  // 所以要看 hand 非空 + 诊断已生成，不能只看 mode。
  if (state.diag !== null && state.view && state.view.hand.length > 0) break;
  await sleep(100);
}
check(mode === "wasm", "默认走真 wasm（`?mock` 才用 Mock 局面）", String(mode));
check(diagnostics?.ok === true, "装载诊断通过", JSON.stringify(diagnostics?.problems ?? []));

const view = await evaluate("window.__p1.view()");
check(view?.hand?.length === 5, "手牌来自内核：5 张", JSON.stringify(view?.hand?.length));

// ⚠️ 视图就绪 ≠ 布局就绪：`layout().cards` 由 `useFrame` 每帧写，要等它跟上手牌数。
let layoutReady = false;
for (let attempt = 0; attempt < 100; attempt += 1) {
  layoutReady = await evaluate(
    `(() => {
      const l = window.__p1.layout();
      return l.frames > 20 && l.cards.length === window.__p1.view().hand.length && l.enemies.length > 0;
    })()`
  );
  if (layoutReady) break;
  await sleep(100);
}
check(layoutReady, "布局跟上手牌与敌人（投影帧数足够）");
check(
  view.hand.every((card) => card.name.length > 0 && card.playable),
  "每张手牌都有名字且可出（可出性来自内核动作表）",
  JSON.stringify(view.hand.map((card) => `${card.name}:${card.playable}`))
);
// i18n：手牌名必须是**中文**（映射表真的接上了，不是回退到定义 id）。
const CJK = /[一-鿿]/;
check(
  view.hand.every((card) => CJK.test(card.name)),
  "每张手牌的显示名都是中文（i18n 映射表生效）",
  JSON.stringify(view.hand.map((card) => card.name))
);
const i18nReport = await evaluate("window.__p1.i18n()");
check(
  (i18nReport.entries.cards ?? 0) > 200 && (i18nReport.entries.monsters ?? 0) > 30,
  "映射表有内容（卡牌 >200、怪物 >30）",
  JSON.stringify(i18nReport.entries)
);
check(
  i18nReport.fallbacks.cards === 0 && i18nReport.fallbacks.monsters === 0,
  "这一局里没有 id 走回退（手牌与敌人都在表里）",
  JSON.stringify(i18nReport.fallbackIds)
);
check(
  view.enemies.every((enemy) => enemy.name.length > 0 && enemy.hp > 0),
  "敌人名字与血量来自内核",
  JSON.stringify(view.enemies.map((enemy) => `${enemy.name} ${enemy.hp}/${enemy.hpMax}`))
);
check(view.hero.energy === 3 && view.hero.hpMax === 80, "英雄 3 能量 / 80 血", JSON.stringify(view.hero));

// ── 1. DOM 上的敌人血量 == 内核里的血量 ───────────────────────────────────
const readLabels = () =>
  evaluate(`(() => {
    const out = {};
    for (const node of document.querySelectorAll("[data-enemy]")) {
      const hp = node.querySelector(".enemy-label__hp");
      out[node.dataset.enemy] = hp ? hp.textContent.trim() : null;
    }
    return out;
  })()`);
const labelsBefore = await readLabels();
const labelsMatch = view.enemies.every(
  (enemy) => labelsBefore[String(enemy.slot)] === `${enemy.hp}/${enemy.hpMax}`
);
check(labelsMatch, "屏幕上的敌人血量与内核一致（不是陈旧值）", JSON.stringify(labelsBefore));

// ── 1b. 目标语义：**来自内容元数据**，不是动作表的 targetSlot（Review P1-A）─────
// 内核会为"每张可出的牌 × 每个活敌人"各发一条动作，所以 `targetSlot >= 0` 什么都说明不了。
// 这里断言"手牌里同时有无目标牌和定向牌"，再各拖一次空白处：
// 无目标牌要**生效**，定向牌要**回弹**。
const targetFlags = await evaluate("window.__p1.view().hand.map((c) => ({ name: c.name, targeted: c.targeted }))");
check(
  targetFlags.some((card) => card.targeted === false),
  "手牌里有**无目标**牌（防御/技能），且被标成 targeted=false",
  JSON.stringify(targetFlags)
);
check(
  targetFlags.some((card) => card.targeted === true),
  "手牌里有**定向**牌（打击/攻击），且被标成 targeted=true",
  JSON.stringify(targetFlags)
);

/** 按下某张牌 → 拖到 `to` → 松开（真实指针事件）。 */
async function dragCard(slot, to) {
  const from = await evaluate(`(() => {
    const card = window.__p1.layout().cards.find((c) => c.slot === ${slot});
    return card ? { x: card.hitX, y: card.hitY } : null;
  })()`);
  if (!from) return false;
  await page.send("Input.dispatchMouseEvent", {
    type: "mousePressed", x: from.x, y: from.y, button: "left", buttons: 1, clickCount: 1,
  });
  for (let step = 1; step <= 6; step += 1) {
    const ratio = step / 6;
    await page.send("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: from.x + (to.x - from.x) * ratio,
      y: from.y + (to.y - from.y) * ratio,
      button: "left", buttons: 1,
    });
    await sleep(16);
  }
  await page.send("Input.dispatchMouseEvent", {
    type: "mouseReleased", x: to.x, y: to.y, button: "left", buttons: 0, clickCount: 1,
  });
  await sleep(250);
  return true;
}

// ⚠️ 宽高在 layout() 里，不在 view() 里（第一版取 view.width ⇒ undefined ⇒ NaN ⇒ CDP 报
// "double value expected"）。
const viewport = await evaluate("({ w: window.__p1.layout().width, h: window.__p1.layout().height })");
const emptySpot = { x: Math.round(viewport.w / 2), y: Math.round(viewport.h * 0.15) };

// ① 无目标牌拖到空白处 ⇒ **生效**（旧实现会回弹：实测能量/格挡/手牌都不变）
const untargetedSlot = targetFlags.findIndex((card) => card.targeted === false);
const beforeUntargeted = await evaluate("window.__p1.view()");
await dragCard(untargetedSlot, emptySpot);
const afterUntargeted = await evaluate("window.__p1.view()");
check(
  afterUntargeted.hand.length === beforeUntargeted.hand.length - 1 &&
    (afterUntargeted.hero.block > beforeUntargeted.hero.block ||
      afterUntargeted.hero.energy < beforeUntargeted.hero.energy ||
      JSON.stringify(afterUntargeted.hero) !== JSON.stringify(beforeUntargeted.hero)),
  "无目标牌拖到**空白处**就生效（不需要选敌人）",
  `block ${beforeUntargeted.hero.block} -> ${afterUntargeted.hero.block}, ` +
    `hand ${beforeUntargeted.hand.length} -> ${afterUntargeted.hand.length}`
);

// ② 定向牌拖到空白处 ⇒ **回弹**（不给目标 = 取消）
const targetedSlot = targetFlags.findIndex((card) => card.targeted === true);
const beforeTargeted = await evaluate("window.__p1.view()");
if (targetedSlot >= 0) {
  await dragCard(targetedSlot, emptySpot);
}
const afterTargeted = await evaluate("window.__p1.view()");
check(
  afterTargeted.hand.length === beforeTargeted.hand.length &&
    afterTargeted.hero.energy === beforeTargeted.hero.energy,
  "定向牌拖到**空白处**回弹（不消耗能量、不出牌）",
  `energy ${beforeTargeted.hero.energy} -> ${afterTargeted.hero.energy}, ` +
    `hand ${beforeTargeted.hand.length} -> ${afterTargeted.hand.length}`
);

// ── 2. 从 UI 拖一张**会打人**的牌出去 ─────────────────────────────────────
const pick = await evaluate(`(() => {
  const view = window.__p1.view();
  const card = view.hand.find((c) => c.targeted && /damage|伤害/i.test(c.rules ?? ""));
  return card ? card.id : null;
})()`);
const playable = await evaluate(`(() => {
  const view = window.__p1.view();
  const cards = window.__p1.layout().cards;
  // 视图里的手牌按槽位排列；找到那张会打人的牌在哪个槽位
  const index = view.hand.findIndex((c) => c.targeted && /damage|伤害/i.test(c.rules ?? ""));
  if (index < 0) return null;
  const screen = cards.find((c) => c.slot === index);
  const enemy = window.__p1.layout().enemies[0];
  return screen && enemy ? { cardIndex: index, from: { x: screen.hitX, y: screen.hitY }, to: { x: enemy.x, y: enemy.y } } : null;
})()`);
check(playable !== null, "找到一张可拖到敌人身上的攻击牌", JSON.stringify({ pick, playable }));

const before = await evaluate("window.__p1.view()");
if (playable) {
  await page.send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: playable.from.x,
    y: playable.from.y,
    button: "left",
    buttons: 1,
    clickCount: 1,
  });
  for (let step = 1; step <= 6; step += 1) {
    const ratio = step / 6;
    await page.send("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: playable.from.x + (playable.to.x - playable.from.x) * ratio,
      y: playable.from.y + (playable.to.y - playable.from.y) * ratio,
      button: "left",
      buttons: 1,
    });
    await sleep(16);
  }
  await page.send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: playable.to.x,
    y: playable.to.y,
    button: "left",
    buttons: 0,
    clickCount: 1,
  });
  await sleep(200);
}

const after = await evaluate("window.__p1.view()");
check(after.hand.length === before.hand.length - 1, "UI 出牌后手牌少一张", `${before.hand.length} -> ${after.hand.length}`);
check(after.hero.energy < before.hero.energy, "UI 出牌后能量减少", `${before.hero.energy} -> ${after.hero.energy}`);
const targetBefore = before.enemies[0];
const targetAfter = after.enemies[0];
check(
  targetAfter.hp < targetBefore.hp,
  "被拖上去的那个敌人掉血（内核接受了这条动作）",
  `${targetBefore.hp} -> ${targetAfter.hp}`
);
const othersHeld = before.enemies.slice(1).every((enemy) => {
  const now = after.enemies.find((candidate) => candidate.slot === enemy.slot);
  return now.hp === enemy.hp;
});
check(othersHeld, "其他敌人没有掉血（目标不串位）");

// ── 3. DOM 跟着内核变（这才是"UI 与内核一致"）─────────────────────────────
const labelsAfter = await readLabels();
const labelsFollow = after.enemies.every(
  (enemy) => labelsAfter[String(enemy.slot)] === `${enemy.hp}/${enemy.hpMax}`
);
check(labelsFollow, "出牌后屏幕上的血量跟着内核变（DOM 不是陈旧值）", JSON.stringify(labelsAfter));

// ── 3b. 手势过期：按住一张牌，期间另一条路径改了动作表 ⇒ 松手必须取消（Review P1-B）──
// `actionIndex` 是数字位置、不是身份。这里模拟"多指同时点结束回合"：
// 按下 → 调 endTurn（动作表换版）→ 松开，期望**不出牌**、能量不变。
const staleView = await evaluate("window.__p1.view()");
const staleSlot = staleView.hand.findIndex((card) => card.targeted);
const stalePoint = await evaluate(`(() => {
  const card = window.__p1.layout().cards.find((c) => c.slot === ${staleSlot});
  return card ? { x: card.hitX, y: card.hitY } : null;
})()`);
const enemyPoint = await evaluate(
  "(() => { const e = window.__p1.layout().enemies[0]; return e ? { x: e.x, y: e.y } : null; })()"
);
if (stalePoint && enemyPoint) {
  await page.send("Input.dispatchMouseEvent", {
    type: "mousePressed", x: stalePoint.x, y: stalePoint.y, button: "left", buttons: 1, clickCount: 1,
  });
  await sleep(80);
  // ⚠️ 另一条路径：结束回合（真实 dispatch，动作表换版）
  const endedMidDrag = await evaluate("window.__p1.endTurn()");
  await sleep(150);
  const midView = await evaluate("window.__p1.view()");
  // 松手在敌人身上 —— 若没有版本校验，这个 index 可能指向"另一张牌打另一个敌人"
  await page.send("Input.dispatchMouseEvent", {
    type: "mouseMoved", x: enemyPoint.x, y: enemyPoint.y, button: "left", buttons: 1,
  });
  await sleep(30);
  await page.send("Input.dispatchMouseEvent", {
    type: "mouseReleased", x: enemyPoint.x, y: enemyPoint.y, button: "left", buttons: 0, clickCount: 1,
  });
  await sleep(300);
  const afterStale = await evaluate("window.__p1.view()");
  check(endedMidDrag?.accepted === true, "按住期间另一条路径（结束回合）成功改了动作表", JSON.stringify(endedMidDrag));
  check(
    afterStale.hero.energy === midView.hero.energy,
    "松手**没有**出牌（能量不变）—— 过期手势被取消",
    `${midView.hero.energy} -> ${afterStale.hero.energy}; hero=${JSON.stringify(afterStale.hero)}`
  );
  check(
    afterStale.epoch > staleView.epoch,
    "视图版本号在状态变化后前进了（epoch 生效）",
    `${staleView.epoch} -> ${afterStale.epoch}`
  );
} else {
  check(false, "构造过期手势的场景（拿到牌与敌人的屏幕坐标）");
}

// ── 4. 结束回合：走内核动作，时间前进 ─────────────────────────────────────
const clockBefore = await evaluate("window.__p1.view()");
const ended = await evaluate("window.__p1.endTurn()");
check(ended?.accepted === true, "结束回合被内核接受", JSON.stringify(ended));
// ⚠️ 探针读的是 **React 状态**：`dispatch` 触发 setState，读太早会拿到旧快照（假红）。
await sleep(200);
const clockAfter = await evaluate("window.__p1.view()");
check(
  clockAfter.turn > clockBefore.turn ||
    clockAfter.round > clockBefore.round ||
    clockAfter.hero.hp < clockBefore.hero.hp,
  "结束回合后时间/局面前进（回合、轮次或掉血）",
  `turn ${clockBefore.turn}->${clockAfter.turn}, round ${clockBefore.round}->${clockAfter.round}, ` +
    `hp ${clockBefore.hero.hp}->${clockAfter.hero.hp}`
);

// ── 5. 证据截图（真 wasm 的 UI，不是 Mock）────────────────────────────────
const { mkdir, writeFile } = await import("node:fs/promises");
const shot = await page.screenshotPng();
await mkdir(join("docs", "ui-p2-real"), { recursive: true });
await writeFile(join("docs", "ui-p2-real", "1280x800-wasm.png"), shot);

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_WASM_UI PASS mode=wasm hand=${after.hand.length} energy=${after.hero.energy} ` +
    `enemy0=${targetBefore.hp}->${targetAfter.hp} dom-synced=1`
);
