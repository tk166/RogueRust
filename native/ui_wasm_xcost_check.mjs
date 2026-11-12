// 闸门 32 `ui-wasm-xcost`：X 费牌真的**扣光能量**（plan P2 的最后一条定向夹具）。
//
// ## 为什么这条要绕这么大一圈
//
// X 费牌（whirlwind / skewer / malaise / transmutation / conjure_blade）**不在起手牌**里，
// 药水三选一也**不给**（它们被排除在"随机攻击/技能牌"候选之外 —— 扫过 14 个种子 × 2 种药水共
// 28 组，一个都没有）。唯一确定性入口是**战斗奖励屏**：
//
//   开局 → 走到战斗 → 打赢 → `fight_end()`（这一步才会生成奖励屏）→ 奖励里挑 X 费牌
//   → 走到下一场战斗 → 结束回合直到抽到它
//
// 扫描结果：**seed 58 的第一场奖励含 `whirlwind`**（seed 59 含 `skewer`）。所以夹具是确定性的。
//
// ## 断言
//
// 1. 手里那张牌 `cost === "X"`（ABI 的 `-2` 被正确解码成 `"X"`，不是数字）；
// 2. 出牌前能量 ≥ 1；
// 3. 打出后 **能量变成 0**（X 费 = 花光所有能量）；
// 4. 敌人**确实掉血**（whirlwind 对所有敌人造成 N 次伤害）；
// 5. 手牌少一张。

import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_WASM_XCOST";
const SEED = 58;
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

// ── 1. 夹具：打赢第一场 → 奖励挑 X 费牌 → 第二场抽到它 ─────────────────────
const fixture = await evaluate(`window.__p2.xCardFixture(${SEED})`);
check(fixture?.ok === true, `seed ${SEED}：把一张 X 费牌弄进手牌`, JSON.stringify(fixture?.why ?? ""));
const trail = fixture?.trail ?? [];
const rewardStep = trail.find((step) => step.step === "reward");
check(
  Array.isArray(rewardStep?.offers) && rewardStep.offers.some((id) => /whirlwind|skewer|malaise|transmutation|conjure_blade/.test(id)),
  "奖励屏里确实有 X 费牌（不是碰运气抽到的）",
  JSON.stringify(rewardStep?.offers)
);
check(fixture?.xCard?.cost === "X", "手里那张牌的 cost 是 **\"X\"**（ABI 的 -2 正确解码）", JSON.stringify(fixture?.xCard));

// ── 2. 出牌前：能量、敌人血量 ──────────────────────────────────────────────
const before = await evaluate("window.__p2.snapshot()");
const energyBefore = before.hero.energy;
check(energyBefore >= 1, "出牌前有能量（X 才有意义）", String(energyBefore));
const enemiesBefore = before.enemies.map((enemy) => ({ slot: enemy.slot, hp: enemy.hp }));
check(enemiesBefore.length >= 1, "场上有敌人", JSON.stringify(enemiesBefore));

// ── 3. 打出 X 费牌 ────────────────────────────────────────────────────────
const slot = fixture.xCard.slot;
const action = await evaluate(`(() => {
  const snapshot = window.__p2.snapshot();
  return snapshot.actions.find((a) => a.kind === "play" && a.handSlot === ${slot}) ?? null;
})()`);
check(action !== null, "X 费牌在动作表里有可出的动作", JSON.stringify(action));

let played = null;
if (action) {
  played = await evaluate(`window.__p2.dispatch(${slot}, ${action.targetSlot})`);
  check(played?.accepted === true, "X 费牌被内核接受", JSON.stringify(played));
}

const after = await evaluate("window.__p2.snapshot()");
check(
  after.hero.energy === 0,
  "打出 X 费牌后**能量变成 0**（X = 花光所有能量）",
  `${energyBefore} -> ${after.hero.energy}`
);
check(
  after.handCount === before.handCount - 1,
  "手牌少一张",
  `${before.handCount} -> ${after.handCount}`
);
const damaged = before.enemies.filter((enemy) => {
  const now = after.enemies.find((candidate) => candidate.slot === enemy.slot);
  return now && now.hp < enemy.hp;
});
// X 费的语义是"花掉多少能量就打多少次"：伤害至少随能量增长（不写死每点几点，那是内容细节）。
const damageDealt = damaged.map((enemy) => {
  const now = after.enemies.find((candidate) => candidate.slot === enemy.slot);
  return enemy.hp - (now?.hp ?? enemy.hp);
});
check(
  damageDealt.length > 0 && Math.max(...damageDealt) >= energyBefore,
  "伤害至少等于花掉的能量数（X = 每点能量至少打一下）",
  JSON.stringify({ energyBefore, damageDealt })
);
check(
  damaged.length > 0,
  "至少一个敌人掉血（whirlwind 是全体伤害）",
  JSON.stringify({
    before: enemiesBefore,
    after: after.enemies.map((enemy) => ({ slot: enemy.slot, hp: enemy.hp })),
  })
);

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_WASM_XCOST PASS seed=${SEED} card=${fixture.trail.find((s) => s.step === "takeCard")?.id} ` +
    `energy=${energyBefore}->${after.hero.energy} damaged=${damaged.length}`
);
