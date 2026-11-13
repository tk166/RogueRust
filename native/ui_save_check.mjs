// 闸门 49 `ui-save`：**自动存档**（§372）。
//
// 背景：默认入口已经切到新 UI，而"刷新一下就丢一局"对正式入口是不可接受的回退。内核早有
// 可信档案（`MAGIC-base64-校验和` + 内容指纹），这一版把它写进 `localStorage`，并在标题页给
// "继续上次"。
//
// 守五件事：
//
// 1. **写**：开局走到地图之后 `localStorage` 里有档案，元信息（幕/层/HP）与局面一致；
// 2. **读**：刷新 → 标题页出现"继续上次" → 点它之后 `run()` **逐字段相同**；
// 3. **战斗中不写**：内核拒绝战斗中存档（`CombatState` 不进档案），所以刷新只会回到开战前 ——
//    这是**诚实**的行为，闸门把"档案没变"钉住；
// 4. **坏档被丢**：把 `localStorage` 改成乱码 → 刷新 → 没有"继续上次"、不崩、日志说清；
// 5. **能清**：清掉之后 `resumeInfo()` 是 `null`。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_SAVE";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { bytes: 0, restored: 0, corrupt: 0 };

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

// 干净起点：清掉上一次跑留下的存档（否则断言会被历史污染）。
await ev("window.__run.clearAutosave()");
check((await ev("window.__run.autosave()")) === null, "清掉之后没有自动存档");

// ── 1. 写：开局走到地图 ────────────────────────────────────────────────────
await ev("window.__run.start(3, 0)");
const blessings = await ev("window.__run.blessings()");
const simple = blessings.find((blessing) => !/card/.test(blessing.id));
await ev(`window.__run.choose(${simple.slot})`);
if ((await ev("window.__run.scene()")).base === "SC-01b") {
  await ev("window.__run.pickBlessingCard(0)");
}
await sleep(150);
const saved = await ev("window.__run.autosave()");
check(saved !== null, "走到地图之后有自动存档", JSON.stringify(saved?.text?.length ?? null));
const runNow = await ev("window.__run.run()");
check(
  saved !== null && saved.act === 1 && saved.floor === runNow.floor && saved.health === runNow.health,
  "存档的元信息（幕/层/HP）与当前局面一致",
  JSON.stringify({ saved: { act: saved?.act, floor: saved?.floor, hp: saved?.health }, run: { floor: runNow.floor, hp: runNow.health } })
);
summary.bytes = saved?.text?.length ?? 0;
check(
  typeof saved?.text === "string" && /^[A-Za-z0-9]+-/.test(saved.text),
  "存的是内核的档案格式（MAGIC-base64-…），不是页面自己序列化的 JSON",
  String(saved?.text?.slice(0, 12))
);
const beforeReload = await ev("JSON.stringify(window.__run.run())");

// ── 2. 读：刷新 → 继续上次 → 逐字段相同 ───────────────────────────────────
await page.evaluate("location.reload()");
await sleep(1500);
check((await ev("window.__run.scene()")).base === "SC-00", "刷新之后回到标题");
const resumeButtons = await ev(`document.querySelectorAll("[data-resume]").length`);
check(resumeButtons === 1, "标题页出现继续上次按钮", String(resumeButtons));
const resumeText = await ev(`(document.querySelector("[data-resume]") || {}).textContent || ""`);
check(resumeText.includes("第 1 幕") && resumeText.includes("生命"), "按钮上写着幕/层/生命", resumeText.trim());
const clicked = await ev(`window.__run.click("[data-resume]")`);
check(clicked.clicked === true, "能点继续上次");
await sleep(250);
const afterResume = await ev("JSON.stringify(window.__run.run())");
check(afterResume === beforeReload, "继续之后运行层观察**逐字段相同**", afterResume.slice(0, 60));
check((await ev("window.__run.scene()")).base === "SC-02", "继续之后回到地图", (await ev("window.__run.scene()")).base);
summary.restored = 1;

// ── 3. 战斗中不写：档案保持不变（刷新只会回到开战前）──────────────────────
const map = await ev("window.__run.map()");
const node = map.nodes.filter((entry) => entry.reachable).find((entry) => entry.kind === 1);
await ev(`window.__run.enter(${node.index})`);
await sleep(120);
const beforeFight = await ev("window.__run.autosave()");
await ev("window.__run.fightBegin()");
await sleep(300);
check((await ev("window.__run.scene()")).base === "SC-03b", "进入战斗");
const duringFight = await ev("window.__run.autosave()");
check(
  duringFight !== null && duringFight.text === beforeFight?.text,
  "战斗中**不写**存档（内核拒绝：CombatState 不进档案）",
  `${beforeFight?.text?.length ?? 0} vs ${duringFight?.text?.length ?? 0}`
);
// 打一手牌，确认战斗中仍然不写。
const hand = await ev("window.__run.hand()");
const play = hand?.actions.find((action) => action.kind === "play");
if (play) await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`);
await sleep(150);
check(
  (await ev("window.__run.autosave()"))?.text === beforeFight?.text,
  "战斗里出牌也不写存档（否则回档会回到半场战斗）"
);

// ── 4. 坏档被丢：乱码 → 刷新 → 没有"继续上次"、不崩、日志说清 ──────────────
await page.evaluate(`window.localStorage.setItem("rd.autosave", "{ this is not json")`);
await page.evaluate("location.reload()");
await sleep(1500);
const buttonsAfterCorrupt = await ev(`document.querySelectorAll("[data-resume]").length`);
check(buttonsAfterCorrupt === 0, "坏存档 ⇒ 标题页没有继续上次", String(buttonsAfterCorrupt));
check((await ev("window.__run.scene()")).base === "SC-00", "坏存档不会让页面崩（仍停在标题）");
check((await ev("window.__run.autosave()")) === null, "坏存档被**清掉**（不留在那里反复失败）");
const log = await ev("window.__run.log()");
check(
  log.some((entry) => entry.text.includes("自动存档损坏")),
  "坏存档在日志里说清（不是静默丢弃）",
  JSON.stringify(log.slice(-2).map((entry) => entry.text))
);
summary.corrupt = 1;

// ── 5. 清：清掉之后 resumeInfo 是 null ────────────────────────────────────
await ev("window.__run.start(1, 0)");
await sleep(120);
check((await ev("window.__run.autosave()")) !== null, "新开一局之后又有存档");
const cleared = await ev("window.__run.clearAutosave()");
check(cleared.autosave === null, "清掉之后 resumeInfo 是 null", JSON.stringify(cleared));

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(`UI_SAVE PASS bytes=${summary.bytes} restored=${summary.restored} corrupt=${summary.corrupt}`);
