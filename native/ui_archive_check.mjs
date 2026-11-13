// 闸门 44 `ui-archive`：**存档 / 回档**（第十五轮 Review §6 的缺口）。
//
// 背景：默认入口已经切到新 UI，而新 UI 之前**没有**存档 —— 玩家刷新一下就把一局丢了。
// 内核早就有可信的档案格式（`MAGIC-base64-校验和`，含内容指纹），缺的只是界面。
//
// 这一道守四件事：
//
// 1. **导出 → 刷新 → 导入** 之后，运行层观察逐字段相同（"局还在"）；
// 2. **坏档案**（乱码 / 篡改 base64 / 截断）必须被内核**拒绝**，且当前这一局**一个字节都不动**
//    （内核是"全有或全无"，这里把这条钉在可观察层面）；
// 3. **战斗中不能存档**（`CombatState` 不进档案）—— 拒绝必须说出原因，而不是静默；
// 4. 走的是**真界面**（设置面板里的两个 textarea + 两个按钮），不是直接调探针。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_ARCHIVE";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { bytes: 0, refused: 0 };

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
const click = (selector) => ev(`window.__run.click(${JSON.stringify(selector)})`);

/** 运行层观察的可比快照（逐字段）。 */
const snapshot = () => ev("JSON.stringify(window.__run.run())");

/** 把文本塞进「回档」输入框并点按钮（走真界面）。 */
async function importText(text) {
  await ev(`(() => {
    const box = document.querySelector("[data-archive-in]");
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    setter.call(box, ${JSON.stringify(text)});
    box.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
  await sleep(60);
  await click("[data-archive-import]");
  await sleep(160);
  return ev(`(document.querySelector("[data-archive-result]") || {}).textContent ?? ""`);
}

// ── 1. 走到地图（有牌组、有金币的一局）────────────────────────────────────
await ev("window.__run.start(11, 0)");
const blessings = await ev("window.__run.blessings()");
const simple = blessings.find((blessing) => !/card/.test(blessing.id));
await ev(`window.__run.choose(${simple.slot})`);
if ((await ev("window.__run.scene()")).base === "SC-01b") {
  await ev("window.__run.pickBlessingCard(0)");
}
const map = await ev("window.__run.map()");
const firstNode = map.nodes.filter((node) => node.reachable).find((node) => node.kind === 1);
await ev(`window.__run.enter(${firstNode.index})`);
const beforeExport = await snapshot();
check(beforeExport.includes('"floor":1'), "导出前站在第 1 层", beforeExport.slice(0, 60));

// ── 2. 真界面导出 ─────────────────────────────────────────────────────────
await click("[data-settings-open]");
await sleep(120);
check(await ev(`Boolean(document.querySelector("[data-settings-archive]"))`), "设置面板里有存档区");
await click("[data-archive-export]");
await sleep(160);
const archive = await ev(`(document.querySelector("[data-archive-out]") || {}).value ?? ""`);
check(archive.length > 20, "导出的档案非空", `${archive.length} 字节`);
check(/^[A-Za-z0-9]+-/.test(archive), "档案是内核的文本格式（MAGIC-base64-…）", archive.slice(0, 16));
summary.bytes = archive.length;
await click("[data-settings-close]");
await sleep(80);

// ── 3. 刷新 → 回到标题 → 导入 → 局回来了 ─────────────────────────────────
await page.evaluate("location.reload()");
await sleep(1400);
check((await ev("window.__run.scene()")).base === "SC-00", "刷新之后回到标题（这一版没有自动存档）");
const freshRun = await ev("window.__run.run()");
check(freshRun === null, "刷新之后没有残留的局", JSON.stringify(freshRun));

await click("[data-settings-open]");
await sleep(120);
const imported = await importText(archive);
check(imported.includes("已回档"), "导入成功", imported);
const afterImport = await snapshot();
check(afterImport === beforeExport, "回档之后运行层观察**逐字段相同**", afterImport.slice(0, 60));
await click("[data-settings-close]");
await sleep(80);
check((await ev("window.__run.scene()")).base === "SC-03", "回档之后回到战斗前（站在同一格上）", (await ev("window.__run.scene()")).base);

// ── 4. 坏档案：拒绝，且当前这一局一个字节都不动 ───────────────────────────
await click("[data-settings-open]");
await sleep(120);
const guardBefore = await snapshot();

const garbage = await importText("这不是档案");
check(garbage.includes("回档失败") || garbage.includes("code -3") || garbage.includes("code -2"), "乱码被拒绝", garbage);
check((await snapshot()) === guardBefore, "乱码被拒绝之后局面不变（全有或全无）");
summary.refused += 1;

// 篡改 base64 的中间一段（校验和会对不上）。
const tampered = archive.slice(0, 12) + (archive[12] === "A" ? "B" : "A") + archive.slice(13);
const tamperedResult = await importText(tampered);
check(
  tamperedResult.includes("回档失败") || tamperedResult.includes("code -3") || tamperedResult.includes("code -2"),
  "篡改过的档案被拒绝（校验和）",
  tamperedResult
);
check((await snapshot()) === guardBefore, "篡改档案被拒绝之后局面不变");
summary.refused += 1;

// 截断：同样必须拒绝。
const truncated = archive.slice(0, Math.floor(archive.length * 0.6));
const truncatedResult = await importText(truncated);
check(
  truncatedResult.includes("回档失败") || truncatedResult.includes("code -3") || truncatedResult.includes("code -2"),
  "截断的档案被拒绝",
  truncatedResult
);
check((await snapshot()) === guardBefore, "截断档案被拒绝之后局面不变");
summary.refused += 1;
await click("[data-settings-close]");
await sleep(80);

// ── 5. 战斗中不能存档（拒绝要说原因）────────────────────────────────────
await ev("window.__run.fightBegin()");
await sleep(300);
check((await ev("window.__run.scene()")).base === "SC-03b", "进入战斗");
await click("[data-settings-open]");
await sleep(120);
await click("[data-archive-export]");
await sleep(160);
const blockedArchive = await ev(`(document.querySelector("[data-archive-out]") || {}).value ?? ""`);
const blockedNote = await ev(`(document.querySelector("[data-archive-result]") || {}).textContent ?? ""`);
check(blockedArchive === "", "战斗中导出得到空档案（内核拒绝）");
check(
  blockedNote.includes("战斗") || blockedNote.includes("拒绝"),
  "战斗中导出的拒绝**说出原因**（不是静默）",
  blockedNote
);
await click("[data-settings-close]");

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(`UI_ARCHIVE PASS bytes=${summary.bytes} refused=${summary.refused} roundtrip=1`);
