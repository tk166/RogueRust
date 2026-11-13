// 闸门 47 `ui-act`：**幕间**（§370）—— 幕数显示 + Boss 遗物三选一。
//
// 三件事：
//
// 1. **幕数必须显示**：换幕后 `floor` 归 0，只画层数会变成"第 0 层"；`act` 只能从
//    `rd_run_act()` 读（观察向量 19 格里没有它）。标题页（还没开局）显示"—"而不是"第 0 幕"。
// 2. **三选一是内核动作**：候选只含 **Boss 档**（对着内容 JSON 验）、互不重复、拿到手就清空，
//    取走之后场景**自动**回到新一幕的地图（界面不需要自己跳屏）。
// 3. **没有待选时取 ⇒ 响亮拒绝**（不是安静地什么都不做）。
//
// ## 为什么用 `?debug` 夹具造 offer
//
// 三选一是 `mark_boss_beaten` 换幕后由内核生成的，而"打赢一场 Boss"没法按需制造
// （自动出牌策略打不过第 16 层）。所以内核另给了一个夹具导出 `rd_run_offer_boss_relics()`，
// 它走的是**同一个** `offer_boss_relics`，只是触发时机由闸门决定。纪律与 `rd_run_grant_potion`
// 一致：只在 `?debug` 页面存在，正式路径没有这个入口（本闸门也断言了这一点）。

import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_ACT";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { act: 0, offer: 0, taken: "" };

try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

// 内容里的 Boss 档遗物（用来验"三选一只从 Boss 池里来"）。
const content = JSON.parse(
  await readFile(join("tools", "contentc", "packages", "sts", "sts.roguedeck.json"), "utf8")
);
const bossPool = new Set(
  (content.Relics ?? [])
    .filter((relic) => String(relic.Rarity ?? "").toLowerCase() === "boss")
    .map((relic) => relic.Id)
);
check(bossPool.size >= 10, "内容里有 Boss 遗物池（>= 10 件）", String(bossPool.size));

// ── A. 正式路径（无 `?debug`）：没有夹具入口 ────────────────────────────────
{
  const page = await openPage({
    page: "web-next/dist/run.html",
    query: "motion=off",
    gate: GATE,
    viewport: { width: 1280, height: 800 },
    waitFor: "Boolean(window.__run && window.__run.ready)",
  });
  const ev = (expression) => page.evaluate(expression);
  const fixture = await ev("typeof window.__run.offerBossRelics");
  check(fixture === "undefined", "正式路径没有夹具入口（`offerBossRelics` 只在 ?debug 下存在）", fixture);
  await page.close();
}

// ── B. 幕数显示 + 三选一（`?debug`）────────────────────────────────────────
{
  const page = await openPage({
    page: "web-next/dist/run.html",
    query: "debug&motion=off",
    gate: GATE,
    viewport: { width: 1280, height: 800 },
    waitFor: "Boolean(window.__run && window.__run.ready)",
  });
  const ev = (expression) => page.evaluate(expression);

  // B1. 还没开局：`act` 是 0，顶栏显示"—"（不是"第 0 幕"）。
  const idleAct = await ev("window.__run.act()");
  const idleText = await ev(`(document.querySelector("[data-run-act]") || {}).textContent || ""`);
  check(idleAct === 0, "没开局时 act = 0", String(idleAct));
  check(idleAct === 0 && idleText.trim() === "—", "没开局时顶栏显示破折号（不是第 0 幕）", idleText.trim());
  check((await ev("window.__run.bossRelics()")).length === 0, "没开局时没有待选遗物");
  const refuseIdle = await ev("window.__run.takeBossRelic(0)");
  check(refuseIdle.code !== 0, "没开局时取三选一被拒绝", JSON.stringify(refuseIdle.code));

  // B2. 开局 ⇒ 第 1 幕，顶栏与地图标题都带幕数。
  await ev("window.__run.start(1, 0)");
  const blessings = await ev("window.__run.blessings()");
  const simple = blessings.find((blessing) => !/card/.test(blessing.id));
  await ev(`window.__run.choose(${simple.slot})`);
  if ((await ev("window.__run.scene()")).base === "SC-01b") {
    await ev("window.__run.pickBlessingCard(0)");
  }
  const act1 = await ev("window.__run.act()");
  summary.act = act1;
  check(act1 === 1, "开局后是第 1 幕", String(act1));
  const topbar = await ev(`(document.querySelector("[data-run-act]") || {}).textContent || ""`);
  check(topbar.includes("第 1 幕"), "顶栏显示第 1 幕", topbar.trim());
  const mapHead = await ev(`(document.querySelector(".scene-map h2") || {}).textContent || ""`);
  check(mapHead.includes("第 1 幕"), "地图标题带幕数（否则换幕后会只剩第 0 层）", mapHead.trim());

  // B3. 夹具：造一次三选一 ⇒ 场景切到 SC-13，三件都画出来。
  const offered = await ev("window.__run.offerBossRelics()");
  check(offered.code === 0, "夹具能生成三选一", JSON.stringify(offered.code));
  await sleep(150);
  const scene = await ev("window.__run.scene()");
  check(scene.base === "SC-13", "有待选时场景是 SC-13（幕间）", scene.base);
  const domScene = await ev("window.__run.domScene()");
  check(domScene === "SC-13", "DOM 的 data-scene 也是 SC-13", domScene);

  const relics = await ev("window.__run.bossRelics()");
  summary.offer = relics.length;
  check(relics.length === 3, "三选一正好三件", String(relics.length));
  check(new Set(relics).size === relics.length, "三件互不重复", JSON.stringify(relics));
  const notBoss = relics.filter((id) => !bossPool.has(id));
  check(notBoss.length === 0, "三件都来自内容的 **Boss** 档（不是随便什么遗物）", JSON.stringify(notBoss));

  const options = await ev(`document.querySelectorAll("[data-boss-relic]").length`);
  check(options === relics.length, "界面把三件都画出来了", `${options}/${relics.length}`);
  const badges = await ev(`document.querySelectorAll("[data-boss-relic] [data-asset-badge]").length`);
  check(badges === relics.length, "每件都带素材徽章", `${badges}/${relics.length}`);
  const header = await ev(`(document.querySelector(".scene-boss-relic h2") || {}).textContent || ""`);
  check(header.includes("通关"), "这一屏同时说清这一幕通关", header.trim());

  // B4. 取走一件 ⇒ 腰带 +1、这一手清空、场景**自动**回地图、对账干净。
  const beltBefore = (await ev("window.__run.inventory()")).relics.length;
  const picked = relics[0];
  const taken = await ev("window.__run.takeBossRelic(0)");
  summary.taken = picked;
  check(taken.code === 0, "能取走第 0 件", JSON.stringify(taken.code));
  await sleep(150);
  const beltAfter = (await ev("window.__run.inventory()")).relics;
  check(beltAfter.length === beltBefore + 1, "遗物真的进了腰带", `${beltBefore} → ${beltAfter.length}`);
  check(beltAfter.includes(picked), "拿到的是刚才那一件", JSON.stringify({ picked, belt: beltAfter }));
  check((await ev("window.__run.bossRelics()")).length === 0, "取走之后这一手清空");
  const afterTake = await ev("window.__run.scene()");
  check(afterTake.base === "SC-02", "取走之后自动回到地图（不需要界面自己跳屏）", afterTake.base);
  check((await ev("window.__run.violations()")).length === 0, "取走之后对账干净");

  // B5. 没有待选时再取 ⇒ 响亮拒绝，且局面不变。
  const beltNow = (await ev("window.__run.inventory()")).relics.length;
  const again = await ev("window.__run.takeBossRelic(0)");
  check(again.code !== 0, "没有待选时再取被拒绝（不是安静地什么都不做）", JSON.stringify(again.code));
  check(
    (await ev("window.__run.inventory()")).relics.length === beltNow,
    "被拒绝之后腰带不变"
  );

  await page.close();
}

console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(`UI_ACT PASS act=${summary.act} offer=${summary.offer} taken=${summary.taken}`);
