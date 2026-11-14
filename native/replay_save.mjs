// 回放存档（从**文件**读，避免转录错误）：`node native/replay_save.mjs <path> [--walk]`
//
// 为什么要有这个脚本：玩家把存档贴在聊天里，人工再抄一遍必然出错（这次就是 CRC 不匹配）。
// 所以存档一律**落盘再读**。`--walk` 会一路走到战斗（打完路上的仗/领完奖励），并把
// 战斗局面与敌人标签打出来 —— 复现"意图/状态/分裂"这类问题就靠它。
import { readFile } from "node:fs/promises";
import { openPage } from "../web/cdp.mjs";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const file = process.argv[2];
if (!file) {
  console.error("用法：node native/replay_save.mjs <save.txt> [--walk]");
  process.exit(2);
}
const walk = process.argv.includes("--walk");
const text = (await readFile(file, "utf8")).trim();

const page = await openPage({
  page: "web-next/dist/run.html",
  query: "",
  gate: "REPLAY_SAVE",
  viewport: { width: 1280, height: 900 },
  waitFor: "Boolean(window.__run && window.__run.ready)",
});
const ev = (e) => page.evaluate(e);

const imported = await ev(`window.__run.importArchive(${JSON.stringify(text)})`);
if (imported?.code !== 0) {
  console.log("IMPORT FAILED:", imported?.message ?? JSON.stringify(imported));
  await page.close();
  process.exit(1);
}
await sleep(400);
console.log("import: ok");
console.log("scene:", JSON.stringify(await ev("window.__run.scene()")));
console.log("run:", JSON.stringify(await ev("window.__run.run()")));

if (!walk) {
  await page.close();
  process.exit(0);
}

/** 走一步：地图→进节点；战斗打完→领奖励；其它屏离开。 */
async function stepOnce() {
  const scene = await ev("window.__run.scene()");
  if (scene.base === "SC-02") {
    const map = await ev("window.__run.map()");
    const next = map.nodes.find((n) => n.reachable);
    if (!next) return "no-node";
    await ev(`window.__run.click("[data-node='${next.index}']")`);
    await sleep(250);
    return "entered";
  }
  if (scene.base === "SC-03") {
    await ev('window.__run.click("[data-fight-begin]")');
    for (let wait = 0; wait < 40; wait += 1) {
      if (await ev("Boolean(window.__run.hand())")) break;
      await sleep(100);
    }
    return "fight";
  }
  if (scene.base === "SC-03b") {
    // 打完这一场（如果还没结束就继续打）。
    for (let i = 0; i < 240; i += 1) {
      const hand = await ev("window.__run.hand()");
      if (!hand || hand.result !== "ongoing") break;
      const play = hand.actions.find((a) => a.kind === "play");
      await (play
        ? ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`)
        : ev("window.__run.endTurn()"));
    }
    await ev('(() => { const n = document.querySelector("[data-combat-continue]"); if (n) n.click(); })()');
    await sleep(250);
    return "finished";
  }
  if (scene.base === "SC-04") {
    await ev('window.__run.click("[data-reward-skip]")');
    await sleep(200);
    return "reward";
  }
  const left = await ev(`(() => {
    for (const s of ["[data-shop-leave]", "[data-rest-leave]", "[data-chest-leave]"]) {
      const n = document.querySelector(s);
      if (n) { n.click(); return s; }
    }
    const option = document.querySelector("[data-event-option][data-available='1']");
    if (option) { option.click(); return "event"; }
    const pick = document.querySelector("[data-deck-pick][data-deck-allowed='1']");
    if (pick) { pick.click(); return "deck"; }
    return null;
  })()`);
  await sleep(250);
  return left ? "left" : "stuck:" + scene.base;
}

/** 敌人标签（名字 / 血 / 意图 / 状态 chip）。 */
const enemyLabels = () =>
  ev(`(() => Array.from(document.querySelectorAll("[data-enemy]")).map((el) => ({
    slot: Number(el.dataset.enemy),
    text: el.textContent.replace(/\\s+/g, " ").trim(),
    statuses: Array.from(el.querySelectorAll("[data-status-id]")).map((s) => ({
      id: s.dataset.statusId,
      text: s.textContent.trim(),
    })),
  })))()`);

for (let i = 0; i < 40; i += 1) {
  const scene = await ev("window.__run.scene()");
  if (scene.base === "SC-03b") break;
  const outcome = await stepOnce();
  if (outcome.startsWith("stuck") || outcome === "no-node") {
    console.log("停在:", outcome, JSON.stringify(await ev("window.__run.scene()")));
    break;
  }
}

const combat = await ev("window.__run.combat()");
if (combat) {
  console.log(
    "敌人:",
    JSON.stringify(
      combat.enemies.map((e) => ({ slot: e.slot, hp: `${e.hp}/${e.hpMax}`, kind: e.intentKind, dmg: e.intentDamage }))
    )
  );
  console.log("标签:", JSON.stringify(await enemyLabels(), null, 1));
  console.log("牌堆:", JSON.stringify(await ev("window.__run.piles()")));
}
await page.close();
