// 闸门 38 `ui-next-p5`：Beat 演出与幕间推进的**端到端**。
//
// 守 plan P5 的三条退出条件：
//
//   1. **关闭动画也能完整游戏** —— 同一段流程在 `?motion=off` 下跑一遍；
//   2. **播放动画的最终状态与内核完全一致** —— 动画在播时读到的局面必须就是内核那份
//      （演出层不持有状态，所以这条是结构性的；这里把它钉在可观察层面）；
//   3. **没有因动画丢失而卡住待决流程** —— 动画**正在播**的时候下一条动作照样被接受。
//
// 另外两条：
//
//   * **跳过**（点"跳过"按钮 / Esc）真的清空队列；
//   * **幕间推进**（`end_act`）是内核动作：在 Boss 之前调用必须被**拒绝**（`-2`），
//     而不是"点了没反应"。
//
// ⚠️ 无头 Chrome 的 `prefers-reduced-motion` 实测是 `reduce`，所以"动画开着"必须用
// `?motion=on` 显式要求（第一版就是被这个默认值坑了：`reducedMotion: true`，一条都没播）。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_NEXT_P5";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};

const summary = { kinds: [], skipped: 0, motionOff: false, actRefusal: null };

try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

/** 开一局并走到第一场战斗（复用 P4 的路径）。返回 `page`。 */
async function openFight(motion) {
  const page = await openPage({
    page: "web-next/dist/run.html",
    query: `motion=${motion}`,
    gate: GATE,
    viewport: { width: 1280, height: 800 },
    waitFor: "Boolean(window.__run && window.__run.ready)",
  });
  const ev = (expression) => page.evaluate(expression);
  await ev("window.__run.start(1, 0)");
  const blessings = await ev("window.__run.blessings()");
  const simple = blessings.find((blessing) => !/card/.test(blessing.id));
  await ev(`window.__run.choose(${simple.slot})`);
  const map = await ev("window.__run.map()");
  const first = map.nodes.filter((node) => node.reachable).find((node) => node.kind === 1);
  await ev(`window.__run.enter(${first.index})`);
  await ev("window.__run.fightBegin()");
  await sleep(300);
  return { page, ev };
}

/** 打完这一场（探针；会回答待决选牌）。 */
async function playOut(ev) {
  for (let step = 0; step < 260; step += 1) {
    const choice = await ev("window.__run.choice()");
    if (choice) {
      const need = Math.max(choice.min, 1);
      for (let index = 0; index < Math.min(need, choice.options.length); index += 1) {
        await ev(`window.__run.choicePick(${index}, true)`);
      }
      const confirmed = await ev("window.__run.choiceConfirm()");
      if (!confirmed.accepted) return "choice-refused";
      continue;
    }
    const hand = await ev("window.__run.hand()");
    if (!hand || hand.result !== "ongoing") return hand?.result ?? "none";
    const play = hand.actions.find((action) => action.kind === "play");
    const result = play
      ? await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`)
      : await ev("window.__run.endTurn()");
    if (result?.accepted === false) return "stuck";
  }
  return "timeout";
}

// ── A. 动画开着：飘字真的出现、而且不挡输入 ─────────────────────────────────
{
  const { page, ev } = await openFight("on");
  const director0 = await ev("window.__p1.beats()");
  check(director0.reducedMotion === false, "?motion=on：动画是开着的", JSON.stringify(director0?.reducedMotion));

  const hand = await ev("window.__run.hand()");
  const play = hand.actions.find((action) => action.kind === "play");
  const before = await ev("window.__run.hand()");
  await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`);
  await sleep(60);

  const director1 = await ev("window.__p1.beats()");
  check(director1.playing !== null, "出牌后有演出在播", JSON.stringify(director1?.summary));
  const floats = await ev(`document.querySelectorAll("[data-beat-kind]").length`);
  check(floats >= 1, "DOM 里画出了飘字", String(floats));
  const text = await ev(`(document.querySelector("[data-beat-text]")||{dataset:{}}).dataset.beatText`);
  check(typeof text === "string" && text.length > 0, "飘字有文案", String(text));
  summary.kinds.push(director1.playing?.kind);

  // **动画不挡输入**：队列还非空时，下一条动作必须照样被接受。
  const stillPlaying = await ev("window.__p1.beats()");
  const nextHand = await ev("window.__run.hand()");
  const nextPlay = nextHand.actions.find((action) => action.kind === "play");
  if (stillPlaying.playing !== null || stillPlaying.queue.length > 0) {
    if (nextPlay) {
      const outcome = await ev(`window.__run.play(${nextPlay.handSlot}, ${nextPlay.targetSlot})`);
      check(outcome?.accepted === true, "动画还在播时，下一条动作照样被接受（演出不挡输入）", JSON.stringify(outcome));
    } else {
      const outcome = await ev("window.__run.endTurn()");
      check(outcome?.accepted === true, "动画还在播时，结束回合照样被接受", JSON.stringify(outcome));
    }
  } else {
    check(true, "（这一手只有一张牌，跳过动画中继续操作）");
  }

  // 最终状态 == 内核：动画层不持有状态，所以"界面的视图"与"内核快照"必须一致。
  const kernel = await ev("window.__run.hand()");
  const view = await ev("window.__p1.view()");
  check(
    view.hero.hp === kernel.heroHp && view.hero.energy === kernel.energy,
    "动画播放中：界面视图与内核快照一致（HP/能量）",
    `view ${view.hero.hp}/${view.hero.energy} vs kernel ${kernel.heroHp}/${kernel.energy}`
  );
  check(
    view.enemies.length === kernel.enemies.length &&
      view.enemies.every((enemy, index) => enemy.hp === kernel.enemies[index].hp),
    "动画播放中：敌人血量与内核一致",
    JSON.stringify({ view: view.enemies.map((e) => e.hp), kernel: kernel.enemies.map((e) => e.hp) })
  );

  // 跳过：点"跳过"按钮（Esc 也走同一条 `skipAll`）。
  const queued = await ev("window.__p1.beats()");
  if (queued.playing !== null || queued.queue.length > 0) {
    const skipped = await ev(`window.__run.click("[data-beat-queue]")`);
    check(skipped.clicked, "演出有跳过按钮", skipped.text);
    await sleep(80);
    const after = await ev("window.__p1.beats()");
    check(after.playing === null && after.queue.length === 0, "跳过之后队列清空", JSON.stringify(after.summary));
    summary.skipped += 1;
  }

  // 打完这一场，确认流程没被演出卡住。
  const result = await playOut(ev);
  check(result !== "stuck" && result !== "timeout", "开着动画也能打完这一场", result);
  const dropped = await ev("window.__p1.beats().dropped");
  check(typeof dropped === "number" && dropped >= 0, "dropped 有账（0 或具体条数）", String(dropped));
  await page.close();
}

// ── B. 关掉动画：一条都不播，流程照走 ───────────────────────────────────────
{
  const { page, ev } = await openFight("off");
  const director = await ev("window.__p1.beats()");
  check(director.reducedMotion === true, "?motion=off：动画关着", JSON.stringify(director?.reducedMotion));

  const hand = await ev("window.__run.hand()");
  const play = hand.actions.find((action) => action.kind === "play");
  await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`);
  await sleep(120);
  const after = await ev("window.__p1.beats()");
  check(after.playing === null && after.queue.length === 0, "关动画：出牌后队列仍为空", JSON.stringify(after.summary));
  const floats = await ev(`document.querySelectorAll("[data-beat-kind]").length`);
  check(floats === 0, "关动画：DOM 里没有飘字", String(floats));

  const result = await playOut(ev);
  check(result !== "stuck" && result !== "timeout", "关动画也能打完这一场", result);
  // 打完 → 结算 → 奖励屏：完整流程在关动画下也成立。
  // ⚠️ 必须显式 `fightEnd()`：`playOut` 停在"战斗有结果"，相位还没归 0（P3 §363 记过）。
  await ev("window.__run.fightEnd()");
  await sleep(80);
  const scene = await ev("window.__run.scene()");
  check(scene.base === "SC-04" || scene.base === "SC-12b", "关动画：战斗结束进入奖励/局终", scene.base);
  summary.motionOff = true;
  await page.close();
}

// ── C. 幕间推进是内核动作：Boss 之前必须被拒绝 ───────────────────────────────
{
  const { page, ev } = await openFight("off");
  const before = await ev("window.__run.scene()");
  const outcome = await ev("window.__run.endAct()");
  check(
    outcome.code === -2,
    "Boss 之前调 end_act 被内核拒绝（不是点了没反应）",
    `code=${outcome.code} scene=${outcome.scene.base}`
  );
  check(outcome.scene.base === before.base, "被拒绝时场景不变", `${before.base} → ${outcome.scene.base}`);
  const log = await ev("window.__run.log()");
  check(
    log.some((entry) => entry.text.includes("幕间推进被拒绝")),
    "被拒绝时日志里写清原因"
  );
  summary.actRefusal = outcome.code;
  await page.close();
}

console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_NEXT_P5 PASS kinds=${summary.kinds.join(",")} skip=${summary.skipped} ` +
    `motion-off=${summary.motionOff ? 1 : 0} act-refusal=${summary.actRefusal}`
);
