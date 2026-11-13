// 闸门 51 `ui-replay`：设置里的**回放**（导出到剪贴板 / 导入并逐步对拍）。
//
// 回放与存档是**两件事**：
// * 存档（§368/§372）描述"现在这一局"；
// * 回放脚本描述"这一局是怎么走到现在的" —— 每一步都带指纹，导入时内核**逐步比对**，
//   所以"分叉在第几步"是可说的，而不是"看起来不一样"。
//
// 守六件事：
//
// 1. **没有局不能导出**（内核 `-1`）；
// 2. **导出的是内核的脚本**：头 `RDR1,S,<seed>,<asc>,<内容指纹>`，至少 5 步；
// 3. **导入逐步对拍**：`code == 0`、`checked == 步数`、`diverged == 0`，且 `run()` **逐字段相同**；
// 4. **篡改一步的指纹 ⇒ 就在那一步分叉**（`diverged == 3`、`checked == 2`）；
// 5. **内容指纹不同 ⇒ 直接拒绝**（不是"走到一半说分叉"）—— 这是最便宜的负控；
// 6. **战斗中导不出**（一场战斗只有结果进脚本，回放必然分叉）。
//
// 另外走一遍**真界面**：设置面板里的「导出回放（至剪贴板）」把脚本写进 textarea。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_REPLAY";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { bytes: 0, steps: 0, diverged: 0 };

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

// ── 1. 没有局不能导出 ──────────────────────────────────────────────────────
check((await ev("window.__run.exportReplay()")) === null, "没有局时导出回放被拒绝（null）");

// ── 2. 走一段（含一场战斗），导出 ──────────────────────────────────────────
await ev("window.__run.start(7, 0)");
const blessings = await ev("window.__run.blessings()");
const simple = blessings.find((blessing) => !/card/.test(blessing.id));
await ev(`window.__run.choose(${simple.slot})`);
const map = await ev("window.__run.map()");
const node = map.nodes.filter((entry) => entry.reachable).find((entry) => entry.kind === 1);
await ev(`window.__run.enter(${node.index})`);
await ev("window.__run.fightBegin()");
for (let step = 0; step < 260; step += 1) {
  const choice = await ev("window.__run.choice()");
  if (choice) {
    const need = Math.max(choice.min, 1);
    for (let index = 0; index < Math.min(need, choice.options.length); index += 1) {
      await ev(`window.__run.choicePick(${index}, true)`);
    }
    await ev("window.__run.choiceConfirm()");
    continue;
  }
  const hand = await ev("window.__run.hand()");
  if (!hand || hand.result !== "ongoing") break;
  const play = hand.actions.find((action) => action.kind === "play");
  const outcome = play
    ? await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`)
    : await ev("window.__run.endTurn()");
  if (outcome?.accepted === false) break;
}
await ev("window.__run.fightEnd()");
await ev("window.__run.skipReward()");
await sleep(150);

const script = await ev("window.__run.exportReplay()");
summary.bytes = script?.length ?? 0;
check(typeof script === "string" && script.length > 20, "导出回放脚本非空", `${summary.bytes} 字节`);
check(/^RDR1,S,7,0,[0-9a-f]{8};/.test(script ?? ""), "脚本头自带 seed/进阶/内容指纹（RDR1,S,7,0,…）", (script ?? "").slice(0, 28));
const records = (script ?? "").split(";").filter(Boolean);
summary.steps = records.length - 1;
check(summary.steps >= 5, "脚本里至少 5 步（走一格 + 一场战斗 + 结算）", `${summary.steps} 步`);
const beforeReplay = await ev("JSON.stringify(window.__run.run())");

// ── 2b. 真界面（不在战斗）：导出写进 textarea ─────────────────────────────
await ev("window.__run.click('[data-settings-open]')");
await sleep(150);
check(await ev(`Boolean(document.querySelector("[data-settings-replay]"))`), "设置面板里有回放一节");
const exported = await ev(`window.__run.click("[data-replay-export]")`);
check(exported.clicked, "有「导出回放（至剪贴板）」按钮", exported.text);
await sleep(250);
const box = await ev(`(document.querySelector("[data-replay-out]") || {}).value || ""`);
check(box.startsWith("RDR1,S,"), "textarea 里是内核的脚本（RDR1,S,…）", box.slice(0, 16));
check(box === script, "界面导出的与探针导出的**逐字节相同**", `${box.length} vs ${summary.bytes}`);
const reason = await ev(`(document.querySelector("[data-replay-result]") || {}).textContent || ""`);
check(reason.includes("已导出"), "结果行说清导出结果（复制成功或提示手动复制）", reason.trim().slice(0, 60));
await ev("window.__run.click('[data-settings-close]')");
await sleep(100);

// ── 3. 导入：逐步对拍 ──────────────────────────────────────────────────────
const replayed = await ev(`window.__run.importReplay(${JSON.stringify(script)})`);
check(replayed.code === 0, "导入之后逐步对拍通过（code 0）", JSON.stringify(replayed.code));
check(replayed.checked === summary.steps, "验过的步数 == 脚本步数", `${replayed.checked} vs ${summary.steps}`);
check(replayed.diverged === 0, "没有分叉", String(replayed.diverged));
check(
  (await ev("JSON.stringify(window.__run.run())")) === beforeReplay,
  "回放之后运行层观察**逐字段相同**（这就是可复现的判据）",
  (await ev("JSON.stringify(window.__run.run())")).slice(0, 56)
);

// ── 4. 篡改一步的指纹 ⇒ 就在那一步分叉 ────────────────────────────────────
const tamperedParts = (script ?? "").split(";");
// 第 3 条记录（index 3）的第一个十六进制位取反。
tamperedParts[3] = tamperedParts[3].replace(/,([0-9a-f])/, (_match, digit) => `,${digit === "0" ? "1" : "0"}`);
const tampered = tamperedParts.join(";");
const diverged = await ev(`window.__run.importReplay(${JSON.stringify(tampered)})`);
summary.diverged = diverged.diverged;
check(diverged.code > 0, "篡改之后回放**报分叉**（code > 0）", String(diverged.code));
check(diverged.diverged === 3, "分叉就报在第 3 步（不是笼统的不一致）", String(diverged.diverged));
check(diverged.checked === 2, "分叉前验过 2 步", String(diverged.checked));

// ── 5. 内容指纹不同 ⇒ 直接拒绝（最便宜的负控）─────────────────────────────
const wrongPin = "RDR1,S,7,0,deadbeef;choose_start,0,-1,0000000000000000,;";
const pinResult = await ev(`window.__run.importReplay(${JSON.stringify(wrongPin)})`);
check(pinResult.code === -2, "内容指纹不同 ⇒ 直接拒绝（code -2）", String(pinResult.code));
check(
  String(pinResult.message).includes("内容") || String(pinResult.message).includes("版本"),
  "拒绝理由说清是内容版本不同",
  String(pinResult.message).slice(0, 60)
);

// ── 6. 回放之后**没有脚本**（内核在回放期间不记账）────────────────────────
//
// 这是实测发现的语义：回放会先 `rd_run_start` 清空 journal，而回放期间不记账 ⇒
// 那一局再导出只会得到**只有头部**的脚本，导入必然分叉（缺前缀）。所以必须拒绝。
check((await ev("window.__run.exportReplay()")) === null, "回放之后导出脚本被拒绝（journal 是空的）");
const replayNote = (await ev("window.__run.log()")).map((entry) => entry.text).join(" | ");
check(
  replayNote.includes("回放之后这一局没有脚本"),
  "拒绝时日志说清原因（并指向存档）",
  replayNote.slice(-80)
);

// ── 7. 战斗中导不出（内核拒绝，界面说原因）────────────────────────────────
await ev("window.__run.fightBegin()");
await sleep(250);
check((await ev("window.__run.scene()")).base === "SC-03b", "进入战斗");
check((await ev("window.__run.exportReplay()")) === null, "战斗中导出被拒绝（一场战斗只有结果进脚本）");
await ev("window.__run.click('[data-settings-open]')");
await sleep(150);
await ev(`window.__run.click("[data-replay-export]")`);
await sleep(200);
const blockedBox = await ev(`(document.querySelector("[data-replay-out]") || {}).value || ""`);
check(blockedBox === "", "战斗中：textarea 里没有脚本（内核拒绝）", `${blockedBox.length} 字符`);
const blockedReason = await ev(`(document.querySelector("[data-replay-result]") || {}).textContent || ""`);
check(
  blockedReason.includes("拒绝") || blockedReason.includes("战斗"),
  "战斗中：结果行说清原因",
  blockedReason.trim().slice(0, 40)
);
await ev("window.__run.click('[data-settings-close]')");

// ── 8. 新开一局之后脚本能力恢复 ───────────────────────────────────────────
await ev("window.__run.start(11, 0)");
await sleep(150);
const freshScript = await ev("window.__run.exportReplay()");
check(
  typeof freshScript === "string" && freshScript.startsWith("RDR1,S,11,0,"),
  "新开一局之后又能导出脚本（`replayed` 被清）",
  String(freshScript).slice(0, 20)
);

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(`UI_REPLAY PASS bytes=${summary.bytes} steps=${summary.steps} diverged=${summary.diverged}`);
