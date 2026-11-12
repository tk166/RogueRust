// 闸门 28 `ui-wasm`：P2 的 ABI 接线证明。
//
// 驱动 `web-next/dist/p2.html` 的 `window.__p2` 探针（**不碰 3D**）。它证明的是 plan P2 的
// 四条退出条件里最硬的两条：
//   * "相同输入得到正确动作与结果" —— 用 `(手牌槽位, 目标槽位)` 找内核给的那条动作，走一步，
//     断言**只有被指的那个敌人**掉血；
//   * "拒绝操作不产生成功演出" —— 制造非法动作，断言返回 `-1` 且观察向量**逐字节不变**。
//
// 装载校验也在这里：导出/长度/哨兵/指纹任何一条不符，`load()` 就该抛 `WasmMismatch`。

import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

// 自包含：把**同一份** `web/rd_wasm.wasm` 同步进 web-next（public/ 与 dist/）。
// 不依赖"谁先跑过 wasm-rebuild"，但源不存在时会给出明确报错（验收里 wasm-rebuild 在前）。
try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch (error) {
  console.error("UI_WASM FAIL: 同步 wasm 失败（先跑一次内核构建 / wasm-rebuild 闸门）");
  console.error(String(error.stdout ?? "") + String(error.stderr ?? ""));
  process.exit(1);
}

const GATE = "UI_WASM";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};

// ── 0. 单一构建产物：manifest 里的 sha256 必须与 web/rd_wasm.wasm 一致 ──────────
const manifest = JSON.parse(await readFile(join("web-next", "public", "wasm.json"), "utf8"));
const source = await readFile(join("web", "rd_wasm.wasm"));
const { createHash } = await import("node:crypto");
const sourceSha = createHash("sha256").update(source).digest("hex");
check(
  manifest.sha256 === sourceSha,
  "web-next 用的 wasm 与 web/rd_wasm.wasm 是**同一份**（sha256 相同）",
  `manifest=${manifest.sha256.slice(0, 12)} source=${sourceSha.slice(0, 12)}`
);

const page = await openPage({
  page: "web-next/dist/p2.html",
  query: "",
  gate: GATE,
  waitFor: "Boolean(window.__p2 && window.__p2.ready)",
});
const evaluate = (expression) => page.evaluate(expression);

// ── 1. 装载 + 校验 ─────────────────────────────────────────────────────────
const loaded = await evaluate("window.__p2.load()");
check(loaded?.ok === true, "装载成功（导出/长度/哨兵全部通过）", JSON.stringify(loaded?.error ?? ""));
check(
  loaded?.diagnostics?.sha256 === sourceSha,
  "装载时算出的 sha256 与磁盘上的一致（不是另一份二进制）",
  `${String(loaded?.diagnostics?.sha256).slice(0, 12)}`
);
check(
  loaded?.diagnostics?.combatObserveLen === 148 && loaded?.diagnostics?.runObserveLen === 19,
  "向量长度由模块自己报：19 / 148",
  JSON.stringify({ run: loaded?.diagnostics?.runObserveLen, combat: loaded?.diagnostics?.combatObserveLen })
);
check(
  typeof loaded?.diagnostics?.contentFingerprint === "string" &&
    loaded.diagnostics.contentFingerprint.startsWith("0x"),
  "内容指纹已记录",
  loaded?.diagnostics?.contentFingerprint
);

// ── 1b. 运行时比对清单：篡改 sha 必须**拒绝装载**（Review P2-A 的负控）────────
// 上一版只把 sha 记进诊断、从不比对 ⇒ "换了 wasm 忘了更新 manifest" 与 "dev 载入旧副本" 都发现不了。
const tampered = await evaluate(`(async () => {
  const response = await fetch("./wasm.json");
  const manifest = await response.json();
  manifest.sha256 = "0".repeat(64);
  const blob = new Blob([JSON.stringify(manifest)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  try {
    // ⚠️ 探针自己会 catch（返回 ok:false / error），所以这里看 ok 与 error，不是看 throw。
    const result = await window.__p2.load("./rd_wasm.wasm", url);
    return { ok: result.ok, error: String(result.error ?? "") };
  } finally {
    URL.revokeObjectURL(url);
  }
})()`);
check(tampered.ok === false, "清单 sha 被篡改 ⇒ 装载被拒绝（运行时比对真的在跑）", JSON.stringify(tampered));
check(
  tampered.error.includes("不是同一份构建产物"),
  "拒绝原因说清楚了（不是同一份构建产物）",
  tampered.error.slice(0, 80)
);
// 负控之后重新正常装载（后续断言要用）
check((await evaluate("window.__p2.load()"))?.ok === true, "负控之后仍能正常装载");

// 拒绝半可用：装载前 `rd_env_active_slot()` 必须是 -3（查询不创建会话）
check(
  (await evaluate("window.__p2.run()")).activeSlot === -3,
  "装载后仍未开局时 active_slot = -3"
);

// ── 2. 开局 → 走到战斗 ────────────────────────────────────────────────────
const started = await evaluate("window.__p2.startFight(1)");
const runAfter = await evaluate("window.__p2.run()");
check(runAfter.exists === true, "开局成功（rd_run_exists = 1）");
check(runAfter.inFight === true, "走到并进入了战斗（rd_run_in_fight = 1）", JSON.stringify(runAfter));
check(started?.fightCode === 0, "rd_run_fight_begin() 返回 0", String(started?.fightCode));

const initial = await evaluate("window.__p2.snapshot()");
check(initial !== null, "能读到战斗快照");
check(initial.hero.hpMax === 80 && initial.hero.energy === 3, "英雄 80 血 / 3 能量", JSON.stringify(initial.hero));
check(initial.handCount === 5 && initial.hand.length === 5, "起手 5 张牌", `${initial.handCount}`);
check(initial.enemies.length >= 1, "至少一个敌人", `${initial.enemies.length}`);
check(initial.result === "ongoing", "战斗进行中", initial.result);
check(
  initial.hand.every((card) => card.cost === "X" || (typeof card.cost === "number" && card.cost >= 0)),
  "每张手牌的费用是数字或 X（不是 -1 的'未产生'）",
  JSON.stringify(initial.hand.map((card) => card.cost))
);
check(initial.piles.hand === initial.handCount, "牌堆计数与手牌数一致", JSON.stringify(initial.piles));

// ── 3. 名字与文本（presentation only）────────────────────────────────────
const names = await evaluate("window.__p2.names()");
check(
  names.hand.length === initial.handCount && names.hand.every((card) => card.name.length > 0),
  "每张手牌都有显示名",
  JSON.stringify(names.hand.map((card) => card.name))
);
check(
  names.enemies.every((enemy) => enemy.name.length > 0),
  "每个敌人都有显示名",
  JSON.stringify(names.enemies.map((enemy) => enemy.name))
);

// ── 4. 正确动作：只有被指的那个敌人掉血 ───────────────────────────────────
// ⚠️ 内核为"每张可出的牌 × 每个活敌人"都发一条动作（`env-abi.md` §5：过度指定目标无害），
// 所以 `(防御, 敌人0)` 也是合法动作 —— 但防御不碰敌人。要断言"掉血"就得挑**真的会打人**的牌。
const attack = await evaluate(`(() => {
  const s = window.__p2.snapshot();
  const names = window.__p2.names();
  // 这里用的是内核文本（英文 "Deal 6 damage."），所以匹配英文 damage。
  // 闸门 29 用的是视图规则文本（i18n 之后是中文），那边匹配 damage 或 伤害。
  // 注意：这段在模板字符串里，注释里不许出现反引号（会截断字符串）。
  const damaging = new Set(
    names.hand.filter((card) => /damage/i.test(card.text)).map((card) => card.slot)
  );
  return s.actions.find(
    (a) => a.kind === "play" && a.targetSlot >= 0 && damaging.has(a.handSlot)
  ) ?? null;
})()`);
check(attack !== null, "动作表里有**带目标且会打人**的出牌动作", JSON.stringify(attack));

let played = null;
if (attack) {
  const before = await evaluate("window.__p2.snapshot()");
  played = await evaluate(`window.__p2.dispatch(${attack.handSlot}, ${attack.targetSlot})`);
  check(played.accepted === true, "出牌被接受", JSON.stringify(played));
  const after = await evaluate("window.__p2.snapshot()");
  const targetBefore = before.enemies.find((enemy) => enemy.slot === attack.targetSlot);
  const targetAfter = after.enemies.find((enemy) => enemy.slot === attack.targetSlot);
  const others = before.enemies.filter((enemy) => enemy.slot !== attack.targetSlot);
  check(
    targetAfter.hp < targetBefore.hp || targetAfter.block < targetBefore.block ||
      JSON.stringify(targetAfter.statuses) !== JSON.stringify(targetBefore.statuses),
    "**被指的那个敌人**确实受到了影响（掉血/掉格挡/中状态）",
    `${JSON.stringify(targetBefore)} -> ${JSON.stringify(targetAfter)}`
  );
  const othersUnhurt = others.every((enemy) => {
    const now = after.enemies.find((candidate) => candidate.slot === enemy.slot);
    return now.hp === enemy.hp;
  });
  check(othersUnhurt, "其他敌人**没有**掉血（目标没有串位）");
  check(
    after.hero.energy === before.hero.energy - (typeof before.hand.find((c) => c.slot === attack.handSlot).cost === "number"
      ? before.hand.find((c) => c.slot === attack.handSlot).cost
      : before.hero.energy),
    "能量按那张牌的费用扣（X 费牌这里不断言）",
    `${before.hero.energy} -> ${after.hero.energy}`
  );
  // ⚠️ 手牌槽位是**位置**，不是身份：打出槽 0 之后手牌是 [0,1,2,3]（槽位被压实）。
  // 所以不能断言"槽 0 消失了" —— 那是把 handSlot 当成 CardInstanceId（Review P2-A）。
  check(
    after.handCount === before.handCount - 1,
    "打出一张后手牌数减一",
    `${before.handCount} -> ${after.handCount}`
  );
}

// ── 5. 拒绝不变性：非法动作必须 `-1` 且**一个字节都不改** ──────────────────
const actionCount = (await evaluate("window.__p2.snapshot()")).actionCount;
const rejected = await evaluate(`window.__p2.stepRaw(${actionCount + 5})`);
check(rejected.code === -1, "越界动作被拒绝（返回 -1）", JSON.stringify(rejected));
check(rejected.unchanged === true, "被拒绝后观察向量**逐字节不变**", JSON.stringify(rejected));

// ── 6. 结束回合：回合数前进 ───────────────────────────────────────────────
const clockBefore = await evaluate("window.__p2.snapshot()");
const ended = await evaluate("window.__p2.endTurn()");
check(ended.accepted === true, "结束回合被接受", JSON.stringify(ended));
const clockAfter = await evaluate("window.__p2.snapshot()");
// ⚠️ 断言"时间动了"而不是"turn 一定涨"：`endTurn` 之后敌人行动、再回到英雄回合，
// `turn` 可能只在英雄回合开始时前进（实测 turn 1→1、round 不变，但敌人已经打过来了）。
check(
  clockAfter.turn > clockBefore.turn ||
    clockAfter.round > clockBefore.round ||
    clockAfter.hero.hp < clockBefore.hero.hp,
  "结束回合后时间/局面确实前进了（回合数、轮次或英雄掉血）",
  `turn ${clockBefore.turn}->${clockAfter.turn}, round ${clockBefore.round}->${clockAfter.round}, ` +
    `hp ${clockBefore.hero.hp}->${clockAfter.hero.hp}`
);

// ── 7. 能一路打到终局，且终局时动作表为空 ─────────────────────────────────
// 上限 200 步：真实战斗不需要这么多，超过就是"驱动卡住"而不是"打得久"。
let steps = 0;
let terminal = null;
while (steps < 200) {
  const snapshot = await evaluate("window.__p2.snapshot()");
  if (snapshot.result !== "ongoing") {
    terminal = snapshot;
    break;
  }
  const action = snapshot.actions.find((candidate) => candidate.kind === "play" && candidate.targetSlot >= 0)
    ?? snapshot.actions.find((candidate) => candidate.kind === "play")
    ?? snapshot.actions.find((candidate) => candidate.kind === "endTurn");
  if (!action) {
    // 没有动作 = 待决选牌或驱动坏了；都不是本闸门要断言的，停下来记录。
    terminal = { result: "stuck", actions: 0, choicePending: (await evaluate("window.__p2.run()")).choicePending };
    break;
  }
  if (action.kind === "endTurn") await evaluate("window.__p2.endTurn()");
  else await evaluate(`window.__p2.dispatch(${action.handSlot}, ${action.targetSlot})`);
  steps += 1;
}
check(
  terminal !== null && (terminal.result === "victory" || terminal.result === "defeat"),
  "能在 200 步内打到终局（胜利或失败，不是卡住）",
  JSON.stringify({ steps, terminal: terminal && { result: terminal.result, hp: terminal.hero?.hp } })
);
if (terminal && terminal.result !== "stuck") {
  check(terminal.actionCount === 0, "终局时动作表为空（不能再出牌）", `${terminal.actionCount}`);
}

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_WASM PASS exports=${loaded.diagnostics.exports} content=${loaded.diagnostics.contentFingerprint} ` +
    `hand=${initial.handCount} enemies=${initial.enemies.length} steps=${steps} ` +
    `result=${terminal ? terminal.result : "?"} rejected-unchanged=1`
);
