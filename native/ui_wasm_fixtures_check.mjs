// 闸门 31 `ui-wasm-fixtures`：plan P2 点名的定向夹具。
//
// | 夹具 | 这条闸门怎么造 | 断言什么 |
// |---|---|---|
// | **同名卡** | 起手就有 3 张 `strike`（真实内容） | 打**最后一张**同名卡，手牌里该 id 只少**一张**、其它同名还在 |
// | **0 能量** | 一路出牌直到能量 0 | 动作表里**没有**买不起的牌（可出性由内核判，不是 UI 判） |
// | **敌人槽位稳定** | 打到某个敌人死 | 活着的敌人**保留原槽位**（不重新编号），且动作不再指向死槽 |
// | **X 费扣能量** | ⚠️ 见文件末尾 | 当前可达路径拿不到 X 费牌，只覆盖解码层 |
//
// 为什么"同名卡"值得单独测：手牌槽位是**位置**（打出后压实），不是身份。UI 若把"第 3 张 strike"
// 当成"strike"去查，就会打错副本 —— 这正是第十三轮 Review P2-A 的 `handSlot ≠ CardInstanceId`。

import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_WASM_FIXTURES";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};

const { execFileSync } = await import("node:child_process");
try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

const page = await openPage({
  page: "web-next/dist/p2.html",
  query: "",
  gate: GATE,
  waitFor: "Boolean(window.__p2 && window.__p2.ready)",
});
const evaluate = (expression) => page.evaluate(expression);
check((await evaluate("window.__p2.load()"))?.ok === true, "装载成功");

// ⚠️ 分组键用 **defSlot**（ABI 冻结的定义身份），不是 `id`：`names()` 返回的是
// `{slot, defSlot, name, text}`，没有 `id` 字段 —— 第一版按 `card.id` 分组，全部落到 `undefined`，
// 于是"起手里有同名卡"那条**假通过**了（5 张牌全算同一个 id）。
const handIds = () =>
  evaluate(`window.__p2.names().hand.map((card) => ({ slot: card.slot, def: card.defSlot, id: card.defSlot }))`);

// ── 夹具 1：同名卡 ────────────────────────────────────────────────────────
const started = await evaluate("window.__p2.startFight(1)");
check(started?.fightCode === 0, "进入战斗", String(started?.fightCode));
const before = await handIds();
const counts = {};
for (const card of before) counts[card.id] = (counts[card.id] ?? 0) + 1;
const duplicateId = Object.keys(counts).find((id) => counts[id] > 1) ?? null;
check(duplicateId !== null, "起手里有同名卡（真实内容：3 张 strike ⇒ 两个同 defSlot）", JSON.stringify(counts));
check(
  Object.keys(counts).every((key) => key !== "undefined"),
  "分组键不是 undefined（`names()` 里确实有 defSlot）",
  JSON.stringify(counts)
);

if (duplicateId) {
  // 取**最后一张**同名卡：如果 UI 把"同名"当身份，它就会打错副本（打第一张）。
  // ⚠️ 对象键是**字符串**、`card.id` 是**数字** —— 第一版直接 `===` 比较，`slots` 空、`lastSlot`
  // 成了 undefined，于是"同名卡"这条夹具静默退化成"没测"。
  const duplicateDef = Number(duplicateId);
  const slots = before.filter((card) => card.id === duplicateDef).map((card) => card.slot);
  check(slots.length > 1, "同名卡有多个槽位可选", JSON.stringify(slots));
  const lastSlot = slots[slots.length - 1];
  const target = await evaluate(`(() => {
    const s = window.__p2.snapshot();
    return s.actions.find((a) => a.kind === "play" && a.handSlot === ${lastSlot}) ?? null;
  })()`);
  check(target !== null, `同名卡的最后一张（槽 ${lastSlot}）有可用动作`, JSON.stringify(target));
  if (target) {
    const played = await evaluate(`window.__p2.dispatch(${lastSlot}, ${target.targetSlot})`);
    check(played.accepted === true, "打出的是**那一张**（按槽位，不按名字）", JSON.stringify(played));
    const after = await handIds();
    const afterCount = after.filter((card) => card.id === duplicateDef).length;
    check(
      afterCount === counts[duplicateId] - 1,
      `同名卡只少了**一张**（${duplicateId}: ${counts[duplicateId]} → ${afterCount}）`,
      JSON.stringify(after.map((card) => card.id))
    );
    check(
      after.length === before.length - 1,
      "手牌总数减一",
      `${before.length} -> ${after.length}`
    );
    // 槽位被压实：剩下的同名卡应当占据连续槽位（0..n-1），没有空洞
    const slotsAfter = after.map((card) => card.slot).sort((a, b) => a - b);
    check(
      slotsAfter.every((slot, index) => slot === index),
      "手牌槽位被压实成 0..n-1（没有空洞）",
      JSON.stringify(slotsAfter)
    );
  }
}

// ── 夹具 2：0 能量 ────────────────────────────────────────────────────────
// 一路出牌直到能量 0，然后断言动作表里没有买不起的牌。
for (let step = 0; step < 12; step += 1) {
  const state = await evaluate("window.__p2.snapshot()");
  if (state.hero.energy === 0) break;
  const action = state.actions.find((candidate) => candidate.kind === "play");
  if (!action) break;
  const cost = state.hand.find((card) => card.slot === action.handSlot)?.cost;
  if (typeof cost === "number" && cost > state.hero.energy) break; // 内核不该给这条
  await evaluate(`window.__p2.dispatch(${action.handSlot}, ${action.targetSlot})`);
}
const zero = await evaluate("window.__p2.snapshot()");
check(zero.hero.energy === 0, "把能量花到 0", `energy=${zero.hero.energy}`);
const affordable = zero.actions
  .filter((action) => action.kind === "play")
  .map((action) => ({ action, card: zero.hand.find((card) => card.slot === action.handSlot) }))
  .filter((entry) => entry.card);
const overpriced = affordable.filter(
  (entry) => typeof entry.card.cost === "number" && entry.card.cost > zero.hero.energy
);
check(
  overpriced.length === 0,
  "0 能量时动作表里**没有**买不起的牌（可出性由内核判，不是 UI 判）",
  JSON.stringify(overpriced.map((entry) => ({ slot: entry.card.slot, cost: entry.card.cost })))
);
check(
  affordable.every((entry) => entry.card.cost === 0),
  "0 能量时还能出的牌都是 0 费（如果有）",
  JSON.stringify(affordable.map((entry) => entry.card.cost))
);

// ── 夹具 3：敌人槽位稳定 ──────────────────────────────────────────────────
// 打到某个敌人死，断言活着的敌人**保留原槽位**。
const restarted = await evaluate("window.__p2.startFight(1)");
check(restarted?.fightCode === 0, "重开一场（用于槽位夹具）", String(restarted?.fightCode));
const initial = await evaluate("window.__p2.snapshot()");
const slotsBefore = initial.enemies.map((enemy) => enemy.slot);
check(slotsBefore.length >= 2, "至少两个敌人（否则槽位稳定性无从谈起）", JSON.stringify(slotsBefore));

let killedSlot = null;
for (let step = 0; step < 60 && killedSlot === null; step += 1) {
  const state = await evaluate("window.__p2.snapshot()");
  if (state.result !== "ongoing") break;
  // 优先打槽位最小的活敌人
  const alive = state.enemies.filter((enemy) => enemy.alive).map((enemy) => enemy.slot);
  const targetSlot = alive[0];
  const action =
    state.actions.find(
      (candidate) => candidate.kind === "play" && candidate.targetSlot === targetSlot
    ) ?? state.actions.find((candidate) => candidate.kind === "endTurn");
  if (!action) break;
  if (action.kind === "endTurn") await evaluate("window.__p2.endTurn()");
  else await evaluate(`window.__p2.dispatch(${action.handSlot}, ${action.targetSlot})`);
  const after = await evaluate("window.__p2.snapshot()");
  const dead = after.enemies.filter((enemy) => !enemy.alive).map((enemy) => enemy.slot);
  if (dead.length > 0) killedSlot = dead[0];
}
if (killedSlot !== null) {
  const state = await evaluate("window.__p2.snapshot()");
  const survivors = state.enemies.filter((enemy) => enemy.alive).map((enemy) => enemy.slot);
  check(
    survivors.every((slot) => slotsBefore.includes(slot)),
    "活着的敌人**保留原槽位**（没有被重新编号）",
    JSON.stringify({ before: slotsBefore, after: state.enemies.map((enemy) => enemy.slot), survivors })
  );
  check(
    state.actions.every((action) => action.targetSlot !== killedSlot),
    "动作不再指向已死的槽位",
    JSON.stringify(state.actions.map((action) => action.targetSlot))
  );
  check(
    state.enemies.find((enemy) => enemy.slot === killedSlot)?.alive === false,
    "死掉的敌人**仍在向量里**（槽位不塌缩，只是 alive=false）",
    JSON.stringify(state.enemies.map((enemy) => ({ slot: enemy.slot, alive: enemy.alive })))
  );
} else {
  // 打不死不是"通过"：说明夹具没造出来，必须响亮地红。
  check(false, "60 步内打死了至少一个敌人（否则槽位稳定性没被验证）");
}

await page.close();
console.log(
  "note X 费：起手牌不含 X 费牌，药水三选一也不给（X 费牌被排除在随机候选外，扫了 seeds 1..14 的 " +
    "attack_potion / skill_potion 共 28 组都没有）。要造这个夹具得走奖励/商店选牌（P3 的 run 循环），" +
    "或让内核提供一个「给一张牌」的调试导出。当前只覆盖解码层（-2 解码成 X，闸门 27 的 decode=8）。"
);
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_WASM_FIXTURES PASS duplicate=${duplicateId} zero-energy=1 slot-stable=${killedSlot !== null ? "1" : "0"}`
);
