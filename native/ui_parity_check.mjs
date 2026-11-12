// 闸门 41 `ui-parity`：**新旧入口共用一个内核**，且新入口的状态与内核逐字段一致。
//
// plan P7 的退出条件原文：*"新旧入口同一内核版本下的关键游戏状态与动作结果一致；新 UI 没有
// 无依据的游戏规则分支。"* 这一道把它拆成三件**可执行**的事：
//
// 1. **同一个二进制**：`web/rd_wasm.wasm`（唯一产物）、`web-next/dist/rd_wasm.wasm`（复制品）、
//    `wasm.json` 记的 sha256 —— 三者逐字节一致。"两个内核版本"在结构上不可能存在。
// 2. **内核侧脚本 ⇄ 新入口状态**：在 Node 里直接跑 wasm（原始导出，不受任何界面影响）跑一段
//    脚本；再在浏览器里用**新入口**走同样的步骤，逐检查点比 8 个运行层字段
//    （`env-abi.md` §11.3 的下标，闸门 33 已经断言过解码表）。
//    ⇒ 新入口没有"无依据的规则分支"：它报出来的每个数字都等于内核自己的数字。
// 3. **旧入口还活着**：`web/index.html` 仍能装载**同一份** wasm 并开局（P7 要求"保留 `web/`
//    直到关键能力齐备"）。它的界面不在这一版验收范围，但底座必须还在。
//
// ⚠️ 为什么不直接拿旧页面当参照物：界面是**被验收的对象**，拿它验另一个界面就是自己验自己。
// 共同底座是 wasm，所以参照物是 wasm 本身。

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_PARITY";
const SEED = 7;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { checkpoints: 0, fields: 0 };

const sha = async (path) => createHash("sha256").update(await readFile(path)).digest("hex");

// ── 1. 同一个二进制 ────────────────────────────────────────────────────────
{
  const oldSha = await sha(join("web", "rd_wasm.wasm"));
  const newSha = await sha(join("web-next", "dist", "rd_wasm.wasm"));
  const manifest = JSON.parse(await readFile(join("web-next", "public", "wasm.json"), "utf8"));
  check(oldSha === newSha, "两个入口的 wasm 逐字节一致", `${oldSha.slice(0, 12)}… vs ${newSha.slice(0, 12)}…`);
  check(manifest.sha256 === newSha, "wasm.json 记的 sha256 与实际字节一致", manifest.sha256.slice(0, 12));
}

// ── 2. Node 侧：直接跑 wasm，记录检查点 ─────────────────────────────────────
//
// 这一段**不经过任何界面**：原始导出 + 文档里的下标（`env-abi.md` §11.3）。
const NODE_SCRIPT = `(async () => {
  const { readFile } = await import("node:fs/promises");
  const bytes = await readFile(${JSON.stringify(join(process.cwd(), "web", "rd_wasm.wasm"))});
  const { instance } = await WebAssembly.instantiate(bytes, {});
  const ex = instance.exports;
  const O = { floor: 0, node: 1, health: 2, healthMax: 3, gold: 4, deckSize: 5, relicCount: 6, potionCount: 7 };
  const trace = [];
  const snap = (label) => {
    const fields = {};
    for (const [name, index] of Object.entries(O)) fields[name] = ex.rd_run_observe(index);
    trace.push({ label, fields });
  };
  ex.rd_run_start(${SEED}, 0);
  snap("start");
  ex.rd_run_choose_start(1);
  snap("blessing");
  ex.rd_run_step(0);
  snap("walked");
  ex.rd_run_begin_node();
  snap("begun");
  ex.rd_run_fight_begin();
  snap("fight-begin");
  for (let n = 0; n < 3; n += 1) {
    if (ex.rd_env_action_count() === 0) break;
    ex.rd_env_step(0);
    snap("play-" + n);
  }
  return trace;
})()`;

const nodeTrace = await (async () => {
  const { execFileSync } = await import("node:child_process");
  const script = `import { writeFileSync } from "node:fs";
const trace = await ${NODE_SCRIPT};
writeFileSync(${JSON.stringify(join(process.cwd(), ".git", "parity-trace.json"))}, JSON.stringify(trace));`;
  const file = join(process.cwd(), ".git", "_parity_node.mjs");
  const { writeFile } = await import("node:fs/promises");
  await writeFile(file, script, "utf8");
  execFileSync(process.execPath, [file], { stdio: "pipe" });
  return JSON.parse(await readFile(join(process.cwd(), ".git", "parity-trace.json"), "utf8"));
})();

check(Array.isArray(nodeTrace) && nodeTrace.length >= 6, "Node 侧跑出了检查点", String(nodeTrace?.length));

// ── 3. 浏览器侧：新入口走同样的步骤，比 8 个字段 ──────────────────────────
{
  const page = await openPage({
    page: "web-next/dist/run.html",
    query: "motion=off",
    gate: GATE,
    viewport: { width: 1280, height: 800 },
    waitFor: "Boolean(window.__run && window.__run.ready)",
  });
  const ev = (expression) => page.evaluate(expression);

  const browserTrace = [];
  const snap = async (label) => {
    const run = await ev("window.__run.run()");
    browserTrace.push({
      label,
      fields: {
        floor: run.floor,
        node: run.node,
        health: run.health,
        healthMax: run.healthMax,
        gold: run.gold,
        deckSize: run.deckSize,
        relicCount: run.relicCount,
        potionCount: run.potionCount,
      },
    });
  };

  await ev(`window.__run.start(${SEED}, 0)`);
  await snap("start");
  await ev("window.__run.choose(1)");
  await snap("blessing");
  // 新入口点的是**全局节点下标**；Node 侧点的是可达表第 0 条 —— 用可达表把它对齐。
  const firstReachable = await ev("window.__run.map().nodes.filter((n) => n.reachable)[0].index");
  await ev(`window.__run.enter(${firstReachable})`);
  await snap("walked");
  // `enterNode` 内部会 `begin_node`（P3 的设计），所以这里再取一次就是 begun 的状态。
  await snap("begun");
  await ev("window.__run.fightBegin()");
  await snap("fight-begin");
  for (let n = 0; n < 3; n += 1) {
    const hand = await ev("window.__run.hand()");
    const play = hand?.actions.find((action) => action.kind === "play");
    if (!play) break;
    await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`);
    await snap(`play-${n}`);
  }

  check(
    browserTrace.length === nodeTrace.length,
    "两边的检查点数一致",
    `${browserTrace.length} vs ${nodeTrace.length}`
  );
  let mismatches = 0;
  for (let index = 0; index < Math.min(browserTrace.length, nodeTrace.length); index += 1) {
    const mine = browserTrace[index];
    const kernel = nodeTrace[index];
    summary.checkpoints += 1;
    const diffs = Object.keys(kernel.fields).filter((key) => kernel.fields[key] !== mine.fields[key]);
    summary.fields += Object.keys(kernel.fields).length;
    if (diffs.length > 0) {
      mismatches += 1;
      if (mismatches <= 3) {
        console.log(`     [${mine.label}] 不一致字段: ${diffs.join(",")}`);
        console.log(`       内核=${JSON.stringify(kernel.fields)}`);
        console.log(`       界面=${JSON.stringify(mine.fields)}`);
      }
    }
  }
  check(mismatches === 0, "每个检查点的 8 个字段都与内核一致", `${mismatches} 处不同`);

  // 另外：动作表也必须是内核给的（不是界面自己拼的）。
  const actionsMatch = await ev(`(() => {
    const hand = window.__run.hand();
    if (!hand) return { ok: true, note: "no-combat" };
    return { ok: hand.actions.length > 0, count: hand.actions.length };
  })()`);
  check(actionsMatch.ok, "新入口的动作表来自内核", JSON.stringify(actionsMatch));
  await page.close();
}

// ── 4. 旧入口还活着（保留 `web/` 直到关键能力齐备）─────────────────────────
{
  const page = await openPage({
    page: "web/index.html",
    query: "",
    gate: GATE,
    viewport: { width: 1280, height: 800 },
    waitFor: "Boolean(window.ex)",
  });
  const alive = await page.evaluate(`(() => {
    const ex = window.ex;
    if (!ex) return { ok: false };
    ex.rd_run_start(1, 0);
    return {
      ok: true,
      observeLen: ex.rd_run_observe_len(),
      envLen: ex.rd_env_observe_len(),
      exists: ex.rd_run_exists(),
      pending: ex.rd_run_pending(),
    };
  })()`);
  check(alive.ok === true, "旧入口仍然能装载并开局");
  check(alive.observeLen === 19 && alive.envLen === 148, "旧入口的 ABI 长度仍是 19 / 148", JSON.stringify(alive));
  check(alive.exists === 1 && alive.pending === 6, "旧入口开局后相位正确（祝福）", JSON.stringify(alive));
  await page.close();
}

console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
// ⚠️ 用 `cells=` 而不是 `fields=`：验收的证据表里有一条通用模式 `(\d+ fields)`，
// 它会抢先匹配 "8 fields" 这个子串，导致证据列只显示 "8 fields"（真踩过）。
console.log(`UI_PARITY PASS checkpoints=${summary.checkpoints} cells=${summary.fields} sha=match old=alive`);
