// 闸门 27 `ui-pure`：P1 的**纯函数**回归（不需要浏览器、不需要 WebGL）。
//
// 覆盖参考包自带的测试（队形 0–6 个敌人、屏幕命中、状态机），并补上本仓库自己关心的三条：
//   * 队形**不按数组下标**重编号（业务 slot 必须原样带出来）；
//   * 超过 6 个敌人与重复 slot **响亮失败**（`RangeError`，不静默截掉可攻击目标）；
//   * 无目标牌丢在敌人身上仍然落到 `slot = -1`（§352 P1-B），以及 `dismiss` 不产生提交。
//
// 为什么与闸门 25/26 分开：红了要能一眼看出坏在**纯逻辑**、**接线**还是**渲染**。
// 编译用跑本脚本的这个 node 去执行 typescript 的 tsc.js，**不依赖 PATH**（验收链给的是收窄的 PATH）。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const WEB_NEXT = fileURLToPath(new URL("../web-next/", import.meta.url));
const out = await mkdtemp(join(tmpdir(), "rd-pure-"));

let bad = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) bad += 1;
};

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
      "src/input/pointerMachine.ts",
      "src/input/hitTest.ts",
      "src/stage/formation.ts",
      "src/stage/layout.ts",
    ],
    { cwd: WEB_NEXT, stdio: "pipe" }
  );

  const formation = await import(pathToFileURL(join(out, "stage/formation.js")).href);
  const hit = await import(pathToFileURL(join(out, "input/hitTest.js")).href);
  const machine = await import(pathToFileURL(join(out, "input/pointerMachine.js")).href);

  // ── 队形：0–6 个敌人，横竖屏 ─────────────────────────────────────────────
  const portrait = { width: 390, height: 844, halfW: 1.82, halfH: 3.93 };
  const desktop = { width: 1280, height: 800, halfW: 3.98, halfH: 2.49 };
  let formationOk = true;
  let slotOk = true;
  let rowOk = true;
  let heroOk = true;
  for (let n = 0; n <= 6; n += 1) {
    // 故意用**非连续**的 slot：证明队形不按下标重编号（业务身份原样带出来）
    const slots = Array.from({ length: n }, (_, i) => i * 7 + 3);
    for (const view of [portrait, desktop]) {
      const result = formation.computeCombatFormation(slots, view);
      if (result.enemies.length !== n) formationOk = false;
      if (JSON.stringify(result.enemies.map((e) => e.slot)) !== JSON.stringify(slots)) slotOk = false;
      if (!(result.hero.x < 0)) heroOk = false;
    }
    const wide = formation.computeCombatFormation(slots, desktop);
    const upper = wide.enemies.filter((e) => e.row === 0).length;
    const lower = wide.enemies.filter((e) => e.row === 1).length;
    if (upper !== Math.ceil(n / 2) || lower !== Math.floor(n / 2)) rowOk = false;
  }
  check(formationOk, "队形：0–6 个敌人在横竖屏都生成正确数量");
  check(slotOk, "队形：业务 slot 原样带出（不按数组下标重编号）");
  check(rowOk, "队形：横屏上行 ceil(n/2)、下行 floor(n/2)");
  check(heroOk, "队形：我方永远在左侧");

  const portrait2 = formation.computeCombatFormation([0, 1], portrait);
  const gap2 = Math.abs(portrait2.enemies[0].y - portrait2.enemies[1].y);
  check(gap2 >= 1.3, "竖屏两个敌人的纵向间距放得下三行标签", `gap=${gap2.toFixed(2)}`);

  let threw6 = false;
  try {
    formation.computeCombatFormation([0, 1, 2, 3, 4, 5, 6], desktop);
  } catch (error) {
    threw6 = error instanceof RangeError;
  }
  check(threw6, "7 个敌人 ⇒ RangeError（不静默截掉可攻击目标）");

  let threwDup = false;
  try {
    formation.computeCombatFormation([1, 1], desktop);
  } catch (error) {
    threwDup = error instanceof RangeError;
  }
  check(threwDup, "重复 slot ⇒ RangeError");

  // ── 屏幕命中 ────────────────────────────────────────────────────────────
  const enemies = [
    { slot: 4, x: 200, y: 120, r: 40 },
    { slot: 5, x: 300, y: 120, r: 40 },
  ];
  check(hit.enemyAtScreen(enemies, 210, 120, new Set([4, 5])) === 4, "命中最近的合法敌人");
  check(hit.enemyAtScreen(enemies, 210, 120, new Set([5])) === -1, "不在合法集合里的敌人不算命中");
  check(hit.enemyAtScreen(enemies, 10, 10, new Set([4, 5])) === -1, "空白处不命中");
  const cards = [
    { slot: 0, hitX: 50, hitY: 400, visibleW: 30, h: 90 },
    { slot: 1, hitX: 80, hitY: 400, visibleW: 30, h: 90 },
  ];
  check(hit.cardAtScreen(cards, 50, 400) === 0 && hit.cardAtScreen(cards, 80, 400) === 1,
    "手牌命中按**露出条**中心（hitX），不按被遮住的牌心");
  check(hit.cardAtScreen(cards, 10, 100) === -1, "手牌外不命中");

  // ── 状态机 ──────────────────────────────────────────────────────────────
  const targeted = [
    { slot: 0, actionIndex: 1, label: "a" },
    { slot: 1, actionIndex: 2, label: "b" },
  ];
  const untargeted = [{ slot: -1, actionIndex: 9, label: "skill" }];
  let session = machine.INITIAL;
  const play = (options, hoverSlot, distance = 40) => {
    session = machine.reduce(session, { type: "down", handSlot: 0, options });
    session = machine.reduce(session, { type: "move", hoverSlot, distance });
    session = machine.reduce(session, { type: "up", hoverSlot, distance });
    return session;
  };
  const first = play(targeted, 1);
  const second = play(targeted, 1);
  check(
    second.resultSeq === first.resultSeq + 1,
    "同一动作做两次 ⇒ 事件序号递增（不按 payload 去重）",
    `seq ${first.resultSeq} -> ${second.resultSeq}`
  );
  const onEnemy = play(untargeted, 1);
  check(
    onEnemy.lastResult?.kind === "commit" && onEnemy.lastResult.targetSlot === -1,
    "无目标牌丢在敌人身上 ⇒ commit 且 targetSlot = -1",
    JSON.stringify(onEnemy.lastResult)
  );
  const tiny = play(targeted, 1, machine.DRAG_THRESHOLD_PX - 1);
  check(tiny.lastResult === null, "位移小于阈值 ⇒ 不产生结果（点按语义）");

  let dismissed = machine.reduce(machine.INITIAL, { type: "down", handSlot: 0, options: targeted });
  dismissed = machine.reduce(dismissed, { type: "dismiss" });
  check(
    dismissed.phase === "idle" && dismissed.lastResult === null,
    "dismiss（长按看详情）⇒ 回 idle 且不产生提交",
    JSON.stringify(dismissed.lastResult)
  );

  await rm(out, { recursive: true, force: true });
  console.log("");
  if (bad > 0) {
    console.error(`UI_PURE FAIL: ${bad} 条`);
    process.exit(1);
  }
  console.log(`UI_PURE PASS formation=0..6 hit=5 machine=4`);
} catch (error) {
  await rm(out, { recursive: true, force: true }).catch(() => {});
  console.error(`UI_PURE ERROR: ${error.message}`);
  process.exit(1);
}
