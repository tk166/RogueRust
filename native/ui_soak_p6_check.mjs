// 闸门 40 `ui-soak-p6`：**稳定性**（plan P6 的"长局 / 多次重开 / 重新载入 / context lost"）。
//
// 四组：
//
//   A. **多次重开**：连开 8 局，每局都要能重新走到地图，对账干净，堆内存没有单调增长的趋势。
//   B. **长局**：一场战斗里连打 60 步，对账始终干净、没有卡住。
//   C. **重新载入**：`location.reload()` 之后回到标题（这一版没有存档，所以"干净重来"就是正确行为）。
//   D. **WebGL 上下文丢失**：真的用 `WEBGL_lose_context` 丢一次，界面必须给诊断 + 一键重新初始化，
//      点完之后战斗还能继续（局面在内核里，不需要重打）。
//   E. **动效偏好持久化**：设置里选"关"，写进 `localStorage`，重载后战斗屏读到的仍然是关。
//
// ## 关于内存
//
// 无头 Chrome 暴露 `performance.memory.usedJSHeapSize`（需要 `--enable-precise-memory-info`
// 才是精确值，但趋势够用）。断言不是"绝对字节数"，而是**趋势**：后 4 次重开的堆增长不超过
// 前 4 次的 1.5 倍 + 4 MB —— 抓的是"每次重开都泄漏一份 wasm/session"这种量级的问题。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_SOAK_P6";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { restarts: 0, steps: 0, heapStart: 0, heapEnd: 0, contextLost: 0, motionPersisted: 0 };

try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

const page = await openPage({
  page: "web-next/dist/run.html",
  query: "motion=off",
  gate: GATE,
  viewport: { width: 1280, height: 800 },
  waitFor: "Boolean(window.__run && window.__run.ready)",
});
const ev = (expression) => page.evaluate(expression);

const heap = () => ev("(performance.memory ? performance.memory.usedJSHeapSize : 0)");

/** 开一局并走到地图（可选：走到战斗）。 */
async function startToMap(seed) {
  await ev(`window.__run.start(${seed}, 0)`);
  const blessings = await ev("window.__run.blessings()");
  const simple = blessings.find((blessing) => !/card/.test(blessing.id)) ?? blessings[0];
  await ev(`window.__run.choose(${simple.slot})`);
  // 有些祝福要求选牌（`SC-01b`）。
  if ((await ev("window.__run.scene()")).base === "SC-01b") {
    await ev("window.__run.pickBlessingCard(0)");
  }
  return ev("window.__run.scene()");
}

// ── A. 多次重开 ────────────────────────────────────────────────────────────
{
  const samples = [];
  for (let round = 1; round <= 8; round += 1) {
    const scene = await startToMap(round);
    const bad = await ev("window.__run.violations()");
    const run = await ev("window.__run.run()");
    if (scene.base !== "SC-02" || bad.length > 0 || run === null || run.floor !== 0) {
      check(false, `第 ${round} 次重开之后状态干净`, JSON.stringify({ scene: scene.base, bad, floor: run?.floor }));
    }
    summary.restarts += 1;
    samples.push(await heap());
  }
  check(summary.restarts === 8, "连开 8 局都不崩", String(summary.restarts));
  const firstHalf = samples.slice(0, 4).reduce((sum, value) => sum + value, 0) / 4;
  const secondHalf = samples.slice(4).reduce((sum, value) => sum + value, 0) / 4;
  summary.heapStart = Math.round(firstHalf);
  summary.heapEnd = Math.round(secondHalf);
  // 判据是**趋势**：后 4 次不超过前 4 次的 1.5 倍 + 4 MB（抓"每次重开泄漏一份会话"这种量级）。
  check(
    secondHalf <= firstHalf * 1.5 + 4 * 1024 * 1024,
    "8 次重开之后堆内存没有单调增长",
    `${Math.round(firstHalf / 1024)}KB → ${Math.round(secondHalf / 1024)}KB`
  );
}

// ── B. 长局：一场战斗里连打 60 步 ───────────────────────────────────────────
{
  const map = await ev("window.__run.map()");
  const node = map.nodes.filter((n) => n.reachable).find((n) => n.kind === 1);
  await ev(`window.__run.enter(${node.index})`);
  await ev("window.__run.fightBegin()");
  await sleep(200);

  let steps = 0;
  let violations = 0;
  for (; steps < 60; steps += 1) {
    const choice = await ev("window.__run.choice()");
    if (choice) {
      const need = Math.max(choice.min, 1);
      for (let index = 0; index < Math.min(need, choice.options.length); index += 1) {
        await ev(`window.__run.choicePick(${index}, true)`);
      }
      await ev("window.__run.choiceConfirm()");
    } else {
      const hand = await ev("window.__run.hand()");
      if (!hand || hand.result !== "ongoing") break;
      const play = hand.actions.find((action) => action.kind === "play");
      const outcome = play
        ? await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`)
        : await ev("window.__run.endTurn()");
      if (outcome?.accepted === false) {
        check(false, "长局里没有被拒绝的死路", JSON.stringify(outcome));
        break;
      }
    }
    const bad = await ev("window.__run.violations()");
    if (bad.length > 0) {
      violations += 1;
      if (violations === 1) check(false, "长局里对账始终干净", JSON.stringify(bad));
    }
  }
  summary.steps = steps;
  check(steps >= 5, "长局真的打了很多步", String(steps));
  if (violations === 0) check(true, "长局里对账始终干净", `${steps} 步`);
  const finalHand = await ev("window.__run.hand()");
  check(finalHand === null || finalHand.result !== "ongoing" || steps >= 60, "长局要么打完要么跑满 60 步", String(steps));
}

// ── C. 重新载入 ────────────────────────────────────────────────────────────
{
  await page.evaluate("location.reload()");
  await sleep(1200);
  const ready = await ev("Boolean(window.__run && window.__run.ready)");
  check(ready === true, "重载之后页面重新可用");
  const scene = await ev("window.__run.scene()");
  check(scene.base === "SC-00", "重载之后回到标题（没有局）", scene.base);
  const run = await ev("window.__run.run()");
  check(run === null, "重载之后没有残留的局", JSON.stringify(run));
}

// ── D. WebGL 上下文丢失 ────────────────────────────────────────────────────
{
  const scene = await startToMap(21);
  check(scene.base === "SC-02", "context lost 之前先走到地图", scene.base);
  const map = await ev("window.__run.map()");
  const node = map.nodes.filter((n) => n.reachable).find((n) => n.kind === 1);
  await ev(`window.__run.enter(${node.index})`);
  await ev("window.__run.fightBegin()");
  await sleep(400);

  // 真的丢一次上下文（`WEBGL_lose_context`）。
  const lost = await ev(`(() => {
    const canvas = document.querySelector("canvas");
    if (!canvas) return "no-canvas";
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    const ext = gl && gl.getExtension("WEBGL_lose_context");
    if (!ext) return "no-extension";
    ext.loseContext();
    return "lost";
  })()`);
  check(lost === "lost", "能真的丢一次 WebGL 上下文", lost);
  await sleep(300);

  const banner = await ev(`Boolean(document.querySelector("[data-context-lost]"))`);
  check(banner, "丢上下文之后有诊断横幅（不是黑屏）");
  const retry = await ev(`Boolean(document.querySelector("[data-context-retry]"))`);
  check(retry, "横幅上有重新初始化按钮");
  if (retry) {
    await ev(`window.__run.click("[data-context-retry]")`);
    await sleep(600);
    const canvasBack = await ev(`(() => { const c = document.querySelector("canvas"); return c ? { w: c.width, h: c.height } : null; })()`);
    check(canvasBack !== null && canvasBack.w > 0, "重新初始化之后画布回来了", JSON.stringify(canvasBack));
    // 局面在内核里：重挂之后**不需要重打**，动作表还在。
    const hand = await ev("window.__run.hand()");
    check(hand !== null && hand.result === "ongoing", "重挂之后战斗还在（局面在内核里）", JSON.stringify(hand?.result));
    const play = hand?.actions.find((action) => action.kind === "play");
    if (play) {
      const outcome = await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`);
      check(outcome?.accepted === true, "重挂之后还能出牌", JSON.stringify(outcome?.code));
    }
    summary.contextLost = 1;
  }
  const bad = await ev("window.__run.violations()");
  check(bad.length === 0, "context lost 前后对账干净", JSON.stringify(bad));
}

// ── E. 动效偏好持久化 ──────────────────────────────────────────────────────
{
  await ev("window.__run.click('[data-settings-open]')");
  await sleep(120);
  const hasOptions = await ev(`document.querySelectorAll("[data-motion-option]").length`);
  check(hasOptions === 3, "设置里有三个动效选项（跟随系统/开/关）", String(hasOptions));
  await ev(`window.__run.click("[data-motion-option='off']")`);
  await sleep(80);
  const stored = await ev("window.localStorage.getItem('rd.motion')");
  check(stored === "off", "选关之后写进了 localStorage", String(stored));
  await ev(`window.__run.click("[data-settings-close]")`);
  await sleep(60);

  // 重载 → 再进战斗，战斗屏必须读到"关"。
  await page.evaluate("location.reload()");
  await sleep(1200);
  const scene = await startToMap(33);
  check(scene.base === "SC-02", "重载后能重新走到地图", scene.base);
  const map = await ev("window.__run.map()");
  const node = map.nodes.filter((n) => n.reachable).find((n) => n.kind === 1);
  await ev(`window.__run.enter(${node.index})`);
  await ev("window.__run.fightBegin()");
  await sleep(400);
  const motion = await ev("window.__p1.metrics()");
  check(motion?.motionOff === true, "重载之后战斗屏仍然关着动效（偏好持久化）", String(motion?.motionOff));
  const floats = await ev(`document.querySelectorAll("[data-beat-kind]").length`);
  check(floats === 0, "关着动效时没有飘字", String(floats));
  summary.motionPersisted = 1;
}

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_SOAK_P6 PASS restarts=${summary.restarts} steps=${summary.steps} ` +
    `heap=${Math.round(summary.heapStart / 1024)}KB->${Math.round(summary.heapEnd / 1024)}KB ` +
    `context-lost=${summary.contextLost} motion-persisted=${summary.motionPersisted}`
);
