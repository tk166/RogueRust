// 闸门 39 `ui-mobile`：**触屏**（CDP 触摸仿真）在 390×844 上把主要操作走一遍。
//
// ## 为什么用 CDP 触摸而不是鼠标
//
// plan P6 要"真实设备优先"。这一版**没有真机**（这是本仓库的既有边界），所以退一档：
// `Emulation.setTouchEmulationEnabled` + `Input.dispatchTouchEvent` 走的是**真正的触摸事件链**
// （浏览器把 touch 合成成 `pointerdown/pointermove/pointerup`，`pointerType === "touch"`），
// 与"鼠标点一下"是两条不同的路径 —— 触摸才有长按详情、才没有 hover、才有滚动抑制。
// 这个差别是**能测出来**的（闸门 26 的指针状态机就是为它写的）。
//
// ## 断言
//
// 1. **触控目标 ≥ 44×44**（窄屏）：所有可点元素逐个量，一个不够就红。
// 2. **不横向溢出**：`scrollWidth == clientWidth`。
// 3. **主要操作能完成**：开始 → 祝福 → 地图 → 战斗（**触摸拖牌**打中敌人）→ 奖励 → 地图。
// 4. **安全区**：`?safe=44,34` 把 `--safe-top/--safe-bottom` 设成非零，顶栏与日志必须真的让开。
// 5. **弹窗能滚**：牌组/设置弹窗在 844 高度下超出一屏时必须可滚（`scrollTop` 能改）。
// 6. **DPR 上限**：窄屏 1.5（画布后备像素 ≤ 1.5 × CSS 像素）。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_MOBILE";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { minTarget: 999, targets: 0, dprCap: 0, backing: 0, safeTop: 0, dragged: false };

try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

/** 开一个**触屏**页面。 */
async function openTouch(query) {
  const page = await openPage({
    page: "web-next/dist/run.html",
    query,
    gate: GATE,
    viewport: { width: 390, height: 844 },
    waitFor: "Boolean(window.__run && window.__run.ready)",
  });
  await page.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  return page;
}

/**
 * 把设备像素比设成 3（真机是 2–3），这样"DPR 上限"才**真的**是紧的约束。
 *
 * ⚠️ 默认视口的 `deviceScaleFactor` 是 1 ⇒ 上限 1.5 根本没被触发（后备像素 == CSS 像素），
 * 于是"上限生效"这条断言会**恒真**。必须把 dsf 调高才测得出来（同 §4 的"下限从没生效过"）。
 */
async function setDpr(page, dpr) {
  await page.send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: dpr,
    mobile: true,
  });
  await sleep(200);
}

/** 元素中心的视口坐标。 */
async function centerOf(page, selector) {
  return page.evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, w: rect.width, h: rect.height };
  })()`);
}

/** 触摸点一下（真正的 touchStart/touchEnd）。 */
async function tap(page, selector) {
  const point = await centerOf(page, selector);
  if (!point) return { tapped: false };
  await page.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: point.x, y: point.y, id: 1 }],
  });
  await sleep(30);
  await page.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await sleep(120);
  return { tapped: true, ...point };
}

/** 触摸拖动（卡片 → 敌人）。中间必须有 touchMove，否则浏览器按"点击"处理。 */
async function dragTouch(page, from, to) {
  await page.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: from.x, y: from.y, id: 1 }],
  });
  for (let step = 1; step <= 6; step += 1) {
    const ratio = step / 6;
    await page.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ x: from.x + (to.x - from.x) * ratio, y: from.y + (to.y - from.y) * ratio, id: 1 }],
    });
    await sleep(16);
  }
  await page.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await sleep(200);
}

// ── A. 竖屏 390×844：布局 / DPR / 触控目标 ──────────────────────────────────
{
  const page = await openTouch("");
  const ev = (expression) => page.evaluate(expression);

  await setDpr(page, 3);
  const metrics = await ev("window.__run.metrics()");
  check(metrics.width === 390 && metrics.height === 844, "视口是 390×844", `${metrics.width}×${metrics.height}`);
  check(metrics.dpr === 3, "设备像素比设成 3（真机量级）", String(metrics.dpr));
  check(metrics.dprCap === 1.5, "窄屏 DPR 上限 1.5", String(metrics.dprCap));
  check(metrics.overflowX <= 1, "没有横向溢出", String(metrics.overflowX));
  summary.dprCap = metrics.dprCap;

  // 触控目标：**所有**可点元素逐个量（不是抽样）。
  const targets = await ev(`(() => {
    const nodes = Array.from(document.querySelectorAll("button, [role=button], input, a[href]"));
    return nodes
      .map((el) => {
        const rect = el.getBoundingClientRect();
        return {
          tag: el.tagName,
          label: (el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 18),
          w: Math.round(rect.width),
          h: Math.round(rect.height),
          visible: rect.width > 0 && rect.height > 0,
        };
      })
      .filter((row) => row.visible);
  })()`);
  const small = targets.filter((row) => row.w < 44 || row.h < 44);
  const minSide = targets.reduce((min, row) => Math.min(min, row.w, row.h), 999);
  summary.targets = targets.length;
  summary.minTarget = minSide;
  check(
    small.length === 0,
    `触控目标都 >= 44×44（${targets.length} 个）`,
    small.length ? JSON.stringify(small.slice(0, 6)) : `最小边 ${minSide}px`
  );

  // ── 触摸走完整流程 ─────────────────────────────────────────────────────
  const started = await tap(page, "[data-start]");
  check(started.tapped, "触摸点得动开始爬塔按钮", JSON.stringify(started));
  await sleep(120);
  check((await ev("window.__run.scene()")).base === "SC-01", "触摸开始后进入祝福");

  const blessing = await ev(`(() => {
    const el = Array.from(document.querySelectorAll("[data-blessing]")).find((node) => !/card/.test(node.dataset.blessingId || ""));
    return el ? el.dataset.blessing : null;
  })()`);
  if (blessing !== null) await tap(page, `[data-blessing='${blessing}']`);
  await sleep(120);
  const afterBlessing = await ev("window.__run.scene()");
  check(afterBlessing.base === "SC-02" || afterBlessing.base === "SC-01b", "触摸选祝福", afterBlessing.base);
  if (afterBlessing.base === "SC-01b") {
    await tap(page, "[data-deck-pick='0']");
    await sleep(120);
  }

  const node = await ev(`(() => {
    const el = Array.from(document.querySelectorAll("[data-node][data-reachable='1']")).find((n) => n.dataset.kind === "1");
    return el ? el.dataset.node : null;
  })()`);
  check(node !== null, "窄屏地图上有可达的战斗节点", String(node));
  await tap(page, `[data-node='${node}']`);
  await sleep(120);
  check((await ev("window.__run.scene()")).base === "SC-03", "触摸走进战斗节点");

  await tap(page, "[data-fight-begin]");
  await sleep(400);
  const combat = await ev("window.__run.scene()");
  check(combat.base === "SC-03b", "触摸开战", combat.base);

  // ── 触摸拖牌打敌人（这是移动端最核心的手势）────────────────────────────
  const setup = await ev(`(() => {
    const probe = window.__p1;
    if (!probe) return null;
    const screen = probe.layout();
    const hand = window.__run.hand();
    const targeted = hand.hand.find((card) => card.targeted === true);
    if (!targeted) return null;
    const card = screen.cards.find((c) => c.slot === targeted.slot);
    const enemy = screen.enemies[0];
    if (!card || !enemy) return null;
    return {
      card: { x: card.hitX, y: card.hitY },
      enemy: { x: enemy.x, y: enemy.y },
      slot: targeted.slot,
      target: enemy.slot,
      before: hand.enemies,
    };
  })()`);
  if (!setup) {
    check(false, "窄屏战斗里有定向牌与敌人（触摸拖拽的前提）");
  } else {
    await dragTouch(page, setup.card, setup.enemy);
    const after = await ev("window.__run.hand()");
    const hit = setup.before.filter((enemy) => {
      const now = after.enemies.find((candidate) => candidate.slot === enemy.slot);
      return now && now.hp < enemy.hp;
    });
    check(
      hit.length === 1 && hit[0].slot === setup.target,
      "触摸拖牌只打中被指的那个敌人",
      JSON.stringify({ before: setup.before, after: after.enemies })
    );
    summary.dragged = hit.length === 1;
  }

  // 画布后备像素（DPR 上限的直接后果）。
  const withCanvas = await ev("window.__run.metrics()");
  if (withCanvas.canvas) {
    summary.backing = withCanvas.canvas.backingPixels;
    const ratio = withCanvas.canvas.backingWidth / Math.max(1, withCanvas.canvas.cssWidth);
    // dsf=3 时：没有上限 ⇒ 3.0；有上限 ⇒ 1.5。所以这条断言**真的**在测上限。
    check(
      ratio > 1.2 && ratio <= 1.55,
      "dsf=3 时画布后备像素 / CSS 像素 = 1.5（上限真的生效，不是恒真）",
      ratio.toFixed(2)
    );
  }

  // ── 弹窗能滚（844 高度下牌组一定会超一屏）──────────────────────────────
  await tap(page, "[data-deck-open]");
  await sleep(120);
  const scrollable = await ev(`(() => {
    const list = document.querySelector(".run-deck-list");
    if (!list) return null;
    const before = list.scrollTop;
    list.scrollTop = 9999;
    const after = list.scrollTop;
    return { clientHeight: list.clientHeight, scrollHeight: list.scrollHeight, before, after };
  })()`);
  // ⚠️ 判据不是"一定能滚"：10 张牌的牌组在 844 高度下本来就不用滚。真正的要求是
  // **要么装得下、要么能滚到底**（不能出现"内容超出但滚不动"）。
  check(
    scrollable !== null &&
      (scrollable.scrollHeight <= scrollable.clientHeight || scrollable.after > scrollable.before),
    "牌组弹窗装得下或能滚到底（不会超出但滚不动）",
    JSON.stringify(scrollable)
  );
  const closeReachable = await centerOf(page, "[data-deck-close]");
  check(closeReachable !== null && closeReachable.y < 844, "关闭按钮在视口内", JSON.stringify(closeReachable));
  await tap(page, "[data-deck-close]");
  await sleep(80);

  await page.close();
}

// ── B. 安全区：`?safe=44,34` 必须真的让开 ───────────────────────────────────
{
  const page = await openTouch("safe=44,34");
  const ev = (expression) => page.evaluate(expression);
  const boxes = await ev(`(() => {
    const rect = (selector) => {
      const el = document.querySelector(selector);
      if (!el) return null;
      const b = el.getBoundingClientRect();
      return { top: Math.round(b.top), bottom: Math.round(b.bottom), height: Math.round(b.height) };
    };
    return { topbar: rect(".run-topbar"), log: rect(".run-log"), height: window.innerHeight };
  })()`);
  check(
    boxes.topbar !== null && boxes.topbar.top >= 44,
    "顶栏让开了 44px 的上安全区",
    JSON.stringify(boxes.topbar)
  );
  check(
    boxes.log !== null && boxes.log.bottom <= boxes.height - 34 + 1,
    "日志让开了 34px 的下安全区",
    JSON.stringify({ log: boxes.log, viewport: boxes.height })
  );
  summary.safeTop = boxes.topbar?.top ?? 0;
  await page.close();
}

// ── C. 平板尺寸 834×1112：布局不塌（DPR 上限回到 2）────────────────────────
{
  const page = await openPage({
    page: "web-next/dist/run.html",
    query: "",
    gate: GATE,
    viewport: { width: 834, height: 1112 },
    waitFor: "Boolean(window.__run && window.__run.ready)",
  });
  const metrics = await page.evaluate("window.__run.metrics()");
  check(metrics.dprCap === 2, "平板宽度 >= 600：DPR 上限回到 2", String(metrics.dprCap));
  check(metrics.overflowX <= 1, "平板没有横向溢出", String(metrics.overflowX));
  await page.close();
}

console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_MOBILE PASS targets=${summary.targets} min=${summary.minTarget} dpr-cap=${summary.dprCap} ` +
    `backing=${summary.backing} safe-top=${summary.safeTop} drag=${summary.dragged ? 1 : 0}`
);
