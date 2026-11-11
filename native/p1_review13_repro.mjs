// 复现并**守住**第十三轮 Review 的 P1-A / P1-B，外加"8px 阈值有没有牙"。
//
// Review 说 P1-A、P1-B 是"按控制流推导、未独立跑浏览器复现"。这里跑**真的**状态机：
// 先把 `src/input/pointerMachine.ts` 编成 JS，再用它跑三组场景。
//
// 三条判据：
//   1. 同一动作做两次 ⇒ 事件序号递增（payload 可以完全相同，去重不能按内容）；
//   2. 无目标牌丢在敌人身上 ⇒ 与丢在空白处**同一个**业务目标（-1）；
//   3. 位移小于阈值 ⇒ 不产生结果（点按语义，留在 targeting）。
//
// 它同时是闸门 26（`ui-pointer`）：修好之后必须打印 `P1_REVIEW13_REPRO PASS`。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const WEB_NEXT = fileURLToPath(new URL("../web-next/", import.meta.url));
const out = await mkdtemp(join(tmpdir(), "rd-pm-"));

/**
 * 编译状态机。
 *
 * ⚠️ 不要走 `npx`：验收链的 `Invoke-Gate` 给的是一个**收窄的 PATH**（只有 cargo / System32 /
 * dotnet），`npx` 不在里面 —— 那条路径下本脚本会以"跑了但没做事"的样子失败（闸门 26 第一次
 * 接进去就是这么红的）。所以直接用跑本脚本的这个 node 去执行 typescript 的 tsc.js，与 PATH 无关。
 */
function compile() {
  const tscJs = join(WEB_NEXT, "node_modules", "typescript", "bin", "tsc");
  if (!existsSync(tscJs)) {
    throw new Error(`找不到 ${tscJs}；先在 web-next 里 npm ci`);
  }
  execFileSync(
    process.execPath,
    [
      tscJs,
      "--target", "es2022",
      "--module", "es2022",
      "--moduleResolution", "bundler",
      "--skipLibCheck",
      "--outDir", out,
      "src/input/pointerMachine.ts",
    ],
    { cwd: WEB_NEXT, stdio: "pipe" }
  );
}

try {
  compile();
  const { INITIAL, reduce, DRAG_THRESHOLD_PX } = await import(
    pathToFileURL(join(out, "pointerMachine.js")).href
  );

  const targeted = [
    { slot: 0, actionIndex: 1, label: "打击 → 敌人 0" },
    { slot: 1, actionIndex: 2, label: "打击 → 敌人 1" },
  ];
  const untargeted = [{ slot: -1, actionIndex: 10, label: "打出 防御" }];

  // ⚠️ 必须沿**同一条状态链**走：真实 store 是长活的。第一版每次从 INITIAL 重来，
  // 于是 resultSeq 永远是 1，"序号递增"这条断言测的是复现脚本自己的 bug。
  let session = INITIAL;
  const play = (options, hoverSlot, distance = 40) => {
    session = reduce(session, { type: "down", handSlot: 0, options });
    session = reduce(session, { type: "move", hoverSlot, distance });
    session = reduce(session, { type: "up", hoverSlot, distance });
    return session;
  };

  let bad = 0;
  const report = (ok, label, detail) => {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
    if (!ok) bad += 1;
  };

  console.log("=== P1-A：同一动作连做两次 ===");
  const first = play(targeted, 1);
  const second = play(targeted, 1);
  // 修法**不是**让 payload 不同 —— 同一张牌打同一个敌人，动作本来就一模一样。
  // 要证明的是"两次是**两个事件**"：payload 可以相同，但事件序号必须递增。
  const samePayload = JSON.stringify(first.lastResult) === JSON.stringify(second.lastResult);
  report(
    second.resultSeq === first.resultSeq + 1,
    "两次相同动作的事件序号递增（payload 相同也不影响）",
    `seq ${first.resultSeq} -> ${second.resultSeq}, samePayload=${samePayload}`
  );

  console.log("");
  console.log("=== P1-B：无目标牌释放在敌人身上 ===");
  const onEnemy = play(untargeted, 1);
  const onEmpty = play(untargeted, -1);
  report(
    JSON.stringify(onEnemy.lastResult) === JSON.stringify(onEmpty.lastResult),
    "丢在敌人上与丢在空白处结果一致（业务目标都是 -1）",
    `onEnemy=${JSON.stringify(onEnemy.lastResult)} onEmpty=${JSON.stringify(onEmpty.lastResult)}`
  );

  console.log("");
  console.log("=== 附：8px 拖拽阈值有没有牙 ===");
  const tiny = play(targeted, 1, DRAG_THRESHOLD_PX - 1);
  report(
    tiny.lastResult === null,
    "小于阈值时不该产生结果（点按语义，留在 targeting）",
    `lastResult=${JSON.stringify(tiny.lastResult)}`
  );

  await rm(out, { recursive: true, force: true });
  console.log("");
  if (bad > 0) {
    console.error(`P1_REVIEW13_REPRO FAIL: ${bad} 条成立（即缺陷存在）`);
    process.exit(1);
  }
  console.log("P1_REVIEW13_REPRO PASS: 三条都已修复");
} catch (error) {
  await rm(out, { recursive: true, force: true }).catch(() => {});
  console.error(`P1_REVIEW13_REPRO ERROR: ${error.message}`);
  process.exit(1);
}
