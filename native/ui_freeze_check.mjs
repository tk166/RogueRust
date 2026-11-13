// 闸门 43 `ui-freeze`：**契约违约之后，所有操作入口都必须真的动不了**。
//
// 第十五轮 Review §2 的核心指控：`blocked` 只作为几个组件的 `busy`/`inert` 属性，
// `RunStore` 的动作方法没有统一保护，`CombatScreen` 走 `GameStore.dispatch` 完全绕过 ——
// 也就是说横幅上写着"界面已冻结"，而玩家照样能出牌、能拿奖励、能用默认动作跳过欠账。
//
// 这一道闸门用**注入违约**（`?debug` 的 `injectViolation`）把界面推进冻结态，然后逐个入口试：
//
//   * 每个入口都必须**被拒绝**（返回值是失败值 / 日志里有"界面已冻结"）；
//   * 局面必须**逐字段不变**（运行层 19 格 + 战斗 148 格）；
//   * 冻结必须**粘性**：把注入撤掉之后仍然冻结（只有重开一局能解）。
//
// ⚠️ 为什么用注入而不是等真的 ABI 违约：真的违约没法按需制造。但**判据**是同一份
// （`RunStore.frozenReason` → `canMutate()` / `GameStore.dispatchGuard`），所以注入测到的
// 就是真违约会走的那条路。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_FREEZE";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { entries: 0, refused: 0, sticky: 0 };

try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

const page = await openPage({
  page: "web-next/dist/run.html",
  // `?debug` 才装注入钩子（正式路径没有它）。
  query: "debug&motion=off",
  gate: GATE,
  viewport: { width: 1280, height: 800 },
  waitFor: "Boolean(window.__run && window.__run.ready)",
});
const ev = (expression) => page.evaluate(expression);

/** 运行层 19 格（逐字段比"没变"）。 */
const runObs = () => ev("(() => { const r = window.__run.run(); return JSON.stringify(r); })()");
/** 战斗 148 格（有战斗时才有）。 */
const combatObs = () => ev("window.__run.combat() ? JSON.stringify(window.__run.combat()) : null");

// ── 1. 开局 → 走到战斗（这样"战斗入口"也在射程内）─────────────────────────
{
  await ev("window.__run.start(1, 0)");
  const blessings = await ev("window.__run.blessings()");
  const simple = blessings.find((blessing) => !/card/.test(blessing.id));
  await ev(`window.__run.choose(${simple.slot})`);
  if ((await ev("window.__run.scene()")).base === "SC-01b") {
    await ev("window.__run.pickBlessingCard(0)");
  }
  const map = await ev("window.__run.map()");
  const node = map.nodes.filter((n) => n.reachable).find((n) => n.kind === 1);
  await ev(`window.__run.enter(${node.index})`);
  await ev("window.__run.fightBegin()");
  await sleep(300);
  check((await ev("window.__run.scene()")).base === "SC-03b", "先走到战斗（战斗入口在射程内）");
  check((await ev("window.__run.frozen()")) === null, "注入之前没有冻结");
}

// ── 2. 注入违约 → 必须冻结 ─────────────────────────────────────────────────
{
  const injected = await ev(`window.__run.injectViolation("闸门 43：注入的违约")`);
  check(injected.frozen !== null, "注入违约之后 frozen 非空", JSON.stringify(injected));
  const banner = await ev(`Boolean(document.querySelector("[data-run-violation]"))`);
  check(banner, "顶部出现对账失败横幅");
  const combatBanner = await ev(`Boolean(document.querySelector("[data-combat-frozen]"))`);
  check(combatBanner, "战斗屏也知道外面冻了（以前完全不知道）");
}

// ── 3. 逐个入口：全部必须被拒绝，且局面逐字段不变 ─────────────────────────
{
  const before = { run: await runObs(), combat: await combatObs() };

  /** 每个入口：调它，断言"没变 + 日志里有冻结字样"。 */
  const attempt = async (label, expression) => {
    summary.entries += 1;
    const logBefore = (await ev("window.__run.log()")).length;
    await ev(expression);
    await sleep(40);
    const after = { run: await runObs(), combat: await combatObs() };
    const log = await ev("window.__run.log()");
    const refused = log.slice(logBefore).some((entry) => entry.text.includes("界面已冻结"));
    const unchanged = after.run === before.run && after.combat === before.combat;
    if (refused && unchanged) summary.refused += 1;
    check(refused && unchanged, `${label}：被拒绝且局面不变`, JSON.stringify({ refused, unchanged }));
  };

  // 战斗入口（**以前完全绕过冻结**的那条路）
  const hand = await ev("window.__run.hand()");
  const play = hand?.actions.find((action) => action.kind === "play");
  if (play) {
    await attempt("战斗：出牌", `window.__run.play(${play.handSlot}, ${play.targetSlot})`);
  }
  await attempt("战斗：结束回合", "window.__run.endTurn()");
  await attempt("战斗：结算（fight_end）", "window.__run.fightEnd()");
  // Run 层入口
  await attempt("奖励：拿牌", "window.__run.takeCard(0)");
  await attempt("奖励：跳过", "window.__run.skipReward()");
  await attempt("奖励：拿药水", "window.__run.takePotion()");
  await attempt("奖励：拿遗物", "window.__run.takeRelic()");
  await attempt("祝福：选择", "window.__run.choose(0)");
  await attempt("地图：走路", "window.__run.enter(0)");
  await attempt("**旧 fallback：用默认动作通过**", "window.__run.settleDefault()");
  await attempt("商店：买", "window.__run.buy('card', 0)");
  await attempt("篝火：休息", "window.__run.rest()");
  await attempt("宝箱：打开", "window.__run.openChest()");
  await attempt("事件：选项", "window.__run.chooseEvent(0)");
  await attempt("欠账：跳过", "window.__run.pickupSkip()");
  await attempt("药水：喝", "window.__run.usePotion(0, -1)");
  await attempt("药水：扔", "window.__run.dropPotion(0)");
  await attempt("幕间：推进", "window.__run.endAct()");
  await attempt("离开", "window.__run.leave()");

  // 选择器：不该能弹出（`deckRequest` 由界面触发，这里只验"动作"被拒）
  await attempt("选牌：祝福", "window.__run.pickBlessingCard(0)");
  await attempt("选牌：事件", "window.__run.pickEventCard(0)");
  await attempt("欠账：改牌", "window.__run.pickupPickCard(0)");
  await attempt("欠账：加牌", "window.__run.pickupAddCard(0)");
  await attempt("欠账：换上限", "window.__run.pickupMaxHp()");
}

// ── 4. 粘性：撤掉注入之后**仍然**冻结 ──────────────────────────────────────
{
  await ev("window.__run.injectViolation(null)");
  await sleep(60);
  const violations = await ev("window.__run.violations()");
  const frozen = await ev("window.__run.frozen()");
  check(violations.length === 0, "撤掉注入之后 violations 为空", JSON.stringify(violations));
  check(frozen !== null, "但冻结**仍然**在（粘性：不清空自动解冻）", String(frozen));
  summary.sticky = 1;

  // 再试一次战斗动作：仍然必须被拒。
  const hand = await ev("window.__run.hand()");
  const play = hand?.actions.find((action) => action.kind === "play");
  const before = await combatObs();
  if (play) await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`);
  const after = await combatObs();
  check(before === after, "粘性冻结下战斗动作仍然不动局面");
}

// ── 5. 唯一解除途径：重开一局 ──────────────────────────────────────────────
{
  await ev("window.__run.start(2, 0)");
  await sleep(80);
  const frozen = await ev("window.__run.frozen()");
  check(frozen === null, "重开一局之后解除冻结", String(frozen));
  const scene = await ev("window.__run.scene()");
  check(scene.base === "SC-01", "重开之后回到祝福（状态干净）", scene.base);
}

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(`UI_FREEZE PASS entries=${summary.entries} refused=${summary.refused} sticky=${summary.sticky}`);
