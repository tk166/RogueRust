// 闸门 48 `ui-curtain`：幕间幕布（`ui-state-model.md` §2.3）。
//
// 规格原文：*"纯演出，1.6 秒自动淡出。触发条件是「`act` 变大」（T1），**不需要**任何新导出。"*
// 所以这一道守三件事：
//
// 1. **判定是纯函数**（`shouldShowCurtain`）：`act` 变大才播；变小（重开）不播；第一次读到
//    幕号不播；关动画不播。闸门 33 里也有一份（那边跑的是编译后的 `scene.ts`，这里是
//    `ActCurtain.tsx` —— 两处都要能单独跑，所以各自编译各自的）。
// 2. **它不挡操作**：覆盖层 `pointer-events: none`（换幕之后第一件该做的事就是点地图），
//    只有"点一下继续"可点；**不点也会自己走**。
// 3. **关动画不播**：`?motion=off` 下 `curtain` 恒为 `null`。
//
// ## 夹具
//
// 幕布由"真换幕"触发，而打赢 Boss 没法按需制造（同 §370）。所以 `?debug` 下有一个
// `simulateActChange(act)`：它**只动演出层**（`lastAct` + `curtain`），不碰任何游戏事实
// （act/floor/地图都由内核给）。闸门也断言正式路径没有这个入口。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_CURTAIN";
const WEB_NEXT = fileURLToPath(new URL("../web-next/", import.meta.url));
const out = await mkdtemp(join(tmpdir(), "rd-curtain-"));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { cases: 0, auto: 0, click: 0 };

try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

// ── A. 判定是纯函数 ────────────────────────────────────────────────────────
try {
  const tscJs = join(WEB_NEXT, "node_modules", "typescript", "bin", "tsc");
  if (!existsSync(tscJs)) throw new Error(`找不到 ${tscJs}；先在 web-next 里 npm ci`);
  execFileSync(
    process.execPath,
    [
      tscJs,
      "--target", "es2022",
      "--module", "es2022",
      "--moduleResolution", "bundler",
      "--skipLibCheck",
      "--rootDir", "src",
      "--outDir", out,
      "src/run/curtain.ts",
    ],
    { cwd: WEB_NEXT, stdio: "pipe" }
  );
  const curtain = await import(pathToFileURL(join(out, "run/curtain.js")).href);
  const should = curtain.shouldShowCurtain;
  const cases = [
    ["act 变大 ⇒ 播", 1, 2, false, true],
    ["act 变大（2→3）⇒ 播", 2, 3, false, true],
    ["act 不变 ⇒ 不播", 2, 2, false, false],
    ["act 变小（重开一局）⇒ 不播", 3, 1, false, false],
    ["第一次读到幕号（previous=0）⇒ 不播", 0, 1, false, false],
    ["关动画 ⇒ 不播（即使 act 变大）", 1, 2, true, false],
  ];
  let bad = 0;
  for (const [label, previous, act, motionOff, want] of cases) {
    summary.cases += 1;
    if (should(previous, act, motionOff) !== want) {
      bad += 1;
      check(false, label, `shouldShowCurtain(${previous}, ${act}, ${motionOff})`);
    }
  }
  check(bad === 0, `判定纯函数：${cases.length} 条边界都对`, `${bad} 条错`);
  check(curtain.CURTAIN_MS === 1600, "自动淡出时长是 1600 ms（与旧页面一致）", String(curtain.CURTAIN_MS));
} finally {
  await rm(out, { recursive: true, force: true });
}

// ── B. 正式路径没有夹具入口 ────────────────────────────────────────────────
{
  const page = await openPage({
    page: "web-next/dist/run.html",
    query: "motion=on",
    gate: GATE,
    viewport: { width: 1280, height: 800 },
    waitFor: "Boolean(window.__run && window.__run.ready)",
  });
  const fixture = await page.evaluate("typeof window.__run.simulateActChange");
  check(fixture === "undefined", "正式路径没有幕布夹具（`simulateActChange` 只在 ?debug）", fixture);
  await page.close();
}

// ── C. 行为：出现 / 不挡操作 / 自动淡出 / 点一下也关 ─────────────────────────
{
  const page = await openPage({
    page: "web-next/dist/run.html",
    query: "debug&motion=on",
    gate: GATE,
    viewport: { width: 1280, height: 800 },
    waitFor: "Boolean(window.__run && window.__run.ready)",
  });
  const ev = (expression) => page.evaluate(expression);

  await ev("window.__run.start(1, 0)");
  const blessings = await ev("window.__run.blessings()");
  const simple = blessings.find((blessing) => !/card/.test(blessing.id));
  await ev(`window.__run.choose(${simple.slot})`);
  if ((await ev("window.__run.scene()")).base === "SC-01b") {
    await ev("window.__run.pickBlessingCard(0)");
  }
  check((await ev("window.__run.curtain()")) === null, "开局不播幕布（那不是换幕）");

  // 换到第 2 幕。
  await ev("window.__run.simulateActChange(2)");
  await sleep(120);
  const shown = await ev("window.__run.curtain()");
  check(shown !== null && shown.act === 2, "换幕之后幕布出现（第 2 幕）", JSON.stringify(shown));
  const domCount = await ev(`document.querySelectorAll("[data-act-curtain]").length`);
  check(domCount === 1, "DOM 里只有一层幕布", String(domCount));
  const label = await ev(`(document.querySelector("[data-act-curtain-label]") || {}).textContent || ""`);
  check(label.includes("第 2 幕"), "幕布上写着第 2 幕", label.trim());

  // 不挡操作：覆盖层 pointer-events: none，地图节点仍可点。
  const overlayPe = await ev(`(() => { const el = document.querySelector(".act-curtain"); return el ? getComputedStyle(el).pointerEvents : null; })()`);
  check(overlayPe === "none", "覆盖层不吃指针事件（点击穿透）", String(overlayPe));
  const nodePe = await ev(`(() => { const n = document.querySelector("[data-node][data-reachable='1']"); return n ? getComputedStyle(n).pointerEvents : null; })()`);
  check(nodePe === "auto", "幕布在播时地图节点仍可点", String(nodePe));

  // 1.6 秒后自动淡出。
  await sleep(1900);
  const gone = await ev("window.__run.curtain()");
  const goneDom = await ev(`document.querySelectorAll("[data-act-curtain]").length`);
  check(gone === null && goneDom === 0, "1.6 秒后自己关掉（不需要玩家操作）", JSON.stringify({ gone, goneDom }));
  summary.auto = 1;

  // 点一下也能关（两条路都只调 dismissCurtain）。
  await ev("window.__run.simulateActChange(3)");
  await sleep(120);
  check((await ev("window.__run.curtain()")) !== null, "第 3 幕的幕布也出现");
  const clicked = await ev(`window.__run.click(".act-curtain-inner")`);
  check(clicked.clicked, "幕布可点", clicked.text.slice(0, 12));
  await sleep(120);
  check((await ev("window.__run.curtain()")) === null, "点一下立刻关掉");
  summary.click = 1;

  // dismiss 幂等（没有幕布时再调不炸）。
  const twice = await ev("window.__run.dismissCurtain()");
  check(twice.curtain === null, "没有幕布时再 dismiss 也不炸（幂等）", JSON.stringify(twice));
  await page.close();
}

// ── D. 关动画：幕布不播 ────────────────────────────────────────────────────
{
  const page = await openPage({
    page: "web-next/dist/run.html",
    query: "debug&motion=off",
    gate: GATE,
    viewport: { width: 1280, height: 800 },
    waitFor: "Boolean(window.__run && window.__run.ready)",
  });
  const ev = (expression) => page.evaluate(expression);
  await ev("window.__run.start(1, 0)");
  const blessings = await ev("window.__run.blessings()");
  const simple = blessings.find((blessing) => !/card/.test(blessing.id));
  await ev(`window.__run.choose(${simple.slot})`);
  await ev("window.__run.simulateActChange(2)");
  await sleep(150);
  const curtain = await ev("window.__run.curtain()");
  const dom = await ev(`document.querySelectorAll("[data-act-curtain]").length`);
  check(curtain === null && dom === 0, "?motion=off：换幕也不播幕布", JSON.stringify({ curtain, dom }));
  await page.close();
}

console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(`UI_CURTAIN PASS cases=${summary.cases} auto=${summary.auto} click=${summary.click}`);
