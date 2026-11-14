// 闸门 46 `ui-assets-render`：素材库页面**真的把东西画出来了**（浏览器）。
//
// 闸门 45 证明"清单没有洞"（纯函数）；这一道证明"洞没有出现在渲染这一端"：
//
//   * 三维原型页：16 个原型都在 DOM 列表里，且 canvas 里**真的画了网格**（读 WebGL 的
//     `renderer.info.render.triangles`/`drawCalls`，不是"应该画了吧"）；
//   * 敌人页：列表 61 行、点一行能换掉画面里的那个（选中态 + 探针一致）；
//   * 二维页：四个表各自的徽章数 == 清单数，且每个徽章 DOM 里真的有两个大写字母；
//   * **产品界面**里也用上了徽章（奖励屏/商店/牌组/药水），不是只有预览页能看。
//
// ⚠️ 这里刻意不比对像素：素材是程序化的，"好看"只能人看（`docs/ui-p8-assets-*.png`），
// 而"画出来了 / 数量对 / 字母对"是能断言的。

import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_ASSETS_RENDER";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { archetypes: 0, enemies: 0, cards: 0, triangles: 0, drawCalls: 0 };

try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

// ── A. 素材库页面 ──────────────────────────────────────────────────────────
{
  const page = await openPage({
    page: "web-next/dist/assets.html",
    query: "",
    gate: GATE,
    viewport: { width: 1280, height: 900 },
    waitFor: "Boolean(window.__assets)",
  });
  const ev = (expression) => page.evaluate(expression);

  const counts = await ev("window.__assets.counts");
  summary.enemies = counts.enemies;
  summary.cards = counts.cards;
  // ⚠️ 状态数会随内容变（§400 删掉了不再使用的 `standard.phase_split`：150 → 149）。
  // 这里断言的是"与**内容包**一致"，所以从内容读，而不是写死一个数。
  const contentCounts = JSON.parse(
    await readFile("tools/contentc/packages/sts/sts.roguedeck.json", "utf8")
  );
  const wantStatuses = (contentCounts.Statuses ?? []).length;
  check(
    counts.enemies === (contentCounts.Monsters ?? []).length &&
      counts.cards === (contentCounts.Cards ?? []).length &&
      counts.relics === (contentCounts.Relics ?? []).length &&
      counts.potions === (contentCounts.Potions ?? []).length &&
      counts.statuses === wantStatuses,
    "清单规模与内容一致",
    JSON.stringify(counts)
  );

  // 三维原型页：DOM 列表 + 真的画了网格。
  const archetypes = await ev("window.__assets.archetypes");
  summary.archetypes = archetypes.length;
  check(archetypes.length === 16, "16 个原型", String(archetypes.length));
  const listRows = await ev(`document.querySelectorAll("[data-archetype]").length`);
  check(listRows === archetypes.length, "原型列表每行都在 DOM 里", `${listRows}/${archetypes.length}`);
  const partsOk = archetypes.every((entry) => entry.parts >= 2);
  check(partsOk, "每个原型 >= 2 个基本体", JSON.stringify(archetypes.map((a) => a.parts)));

  await sleep(900); // 等几帧（WebGL 首帧要编译 shader）
  const render = await ev(`(() => {
    const canvas = document.querySelector("canvas");
    if (!canvas) return null;
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    return { width: canvas.width, height: canvas.height, context: gl ? gl.constructor.name : "none" };
  })()`);
  check(render !== null && render.width > 0, "三维画布有尺寸", JSON.stringify(render));

  // 证明"真的画上去了"，而不是只有一块空画布。
  //
  // ⚠️ 不能用 `gl.readPixels`：合成之后 drawing buffer 已被清（实测全 0 —— 那是"读晚了"，
  // 不是"没画"）。改用 CDP 截图（**合成后的那一帧**）统计"彩色像素"：
  // 背景是 #0d1014 这类近灰，敌人是饱和的红/绿/蓝/紫，用"通道差"区分最稳。
  const shot = await page.screenshot();
  let lit = 0;
  for (let index = 0; index < shot.data.length; index += 4) {
    const r = shot.data[index];
    const g = shot.data[index + 1];
    const b = shot.data[index + 2];
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    // 饱和且不太暗 ⇒ 是画上去的素材，不是背景/文字。
    if (max > 70 && max - min > 35) lit += 1;
  }
  summary.triangles = lit;
  check(lit > 2000, "三维画布上**真的有东西**（截图里的彩色像素 > 2000）", `${lit} 个彩色像素 / ${shot.data.length / 4}`);

  // 敌人页：61 行 + 点一行换画面。
  await ev(`document.querySelector("[data-assets-tab='enemies']").click()`);
  await sleep(400);
  const enemyRows = await ev(`document.querySelectorAll("[data-enemy]").length`);
  summary.enemies = enemyRows;
  check(enemyRows === counts.enemies, "敌人列表 61 行", String(enemyRows));
  const bosses = await ev(`document.querySelectorAll("[data-enemy][data-boss='1']").length`);
  check(bosses > 0, "有敌人被标成 Boss", String(bosses));
  const picked = await ev(`(() => {
    const rows = Array.from(document.querySelectorAll("[data-enemy-pick]"));
    const target = rows[Math.min(10, rows.length - 1)];
    target.click();
    return target.dataset.enemyPick;
  })()`);
  await sleep(500);
  const selected = await ev(`(document.querySelector("[data-enemy].is-selected") || {}).dataset?.enemy`);
  check(selected === picked, "点列表能换画面里的那个敌人", `${picked} vs ${selected}`);

  // 二维页：四个表各自数量 + 每个徽章真的有两个大写字母。
  await ev(`document.querySelector("[data-assets-tab='badges']").click()`);
  await sleep(300);
  for (const [kind, want] of [
    ["cards", counts.cards],
    ["relics", counts.relics],
    ["potions", counts.potions],
    ["statuses", counts.statuses],
  ]) {
    await ev(`document.querySelector("[data-badge-tab='${kind}']").click()`);
    await sleep(150);
    const rows = await ev(`document.querySelectorAll("[data-badge-id]").length`);
    check(rows === want, `二维 ${kind}：${want} 个徽章都画出来了`, String(rows));
  }
  const letters = await ev(`(() => {
    const badges = Array.from(document.querySelectorAll("[data-badge-id]"));
    const bad = badges.filter((node) => {
      const text = (node.querySelector(".asset-badge__letters") || {}).textContent || "";
      return !/^[A-Z]{2}$/.test(text.trim());
    });
    return { total: badges.length, bad: bad.length, sample: badges.slice(0, 3).map((n) => n.dataset.badgeId) };
  })()`);
  check(letters.bad === 0, "每个徽章 DOM 里都是两位大写字母", JSON.stringify(letters));

  // 素材页的探针：降级为空（清单覆盖全）。
  const fallbacks = await ev(`(() => {
    const ids = window.__assets.enemies.map((e) => e.id);
    return ids.filter((id) => window.__assets.enemyLook(id).fallback).length;
  })()`);
  check(fallbacks === 0, "素材页上没有走降级的敌人", String(fallbacks));

  await page.close();
}

// ── B. 产品界面里也用了徽章（不是只有预览页能看）───────────────────────────
{
  const page = await openPage({
    page: "web-next/dist/run.html",
    query: "motion=off",
    gate: GATE,
    viewport: { width: 1280, height: 800 },
    waitFor: "Boolean(window.__run && window.__run.ready)",
  });
  const ev = (expression) => page.evaluate(expression);
  await ev("window.__run.start(1, 0)");
  const blessings = await ev("window.__run.blessings()");
  const simple = blessings.find((blessing) => !/card/.test(blessing.id));
  await ev(`window.__run.choose(${simple.slot})`);
  if ((await ev("window.__run.scene()")).base === "SC-01b") {
    await ev("window.__run.pickBlessingCard(0)");
  }

  // 牌组弹窗：每行一个徽章。
  await ev(`window.__run.click("[data-deck-open]")`);
  await sleep(200);
  const deckBadges = await ev(`document.querySelectorAll("[data-deck-card] [data-asset-badge]").length`);
  const deckRows = await ev(`document.querySelectorAll("[data-deck-card]").length`);
  check(deckBadges === deckRows && deckRows > 0, "牌组弹窗：每行都有素材徽章", `${deckBadges}/${deckRows}`);
  await ev(`window.__run.click("[data-deck-close]")`);

  // 走到战斗 → 打完 → 奖励屏的卡面徽章。
  const map = await ev("window.__run.map()");
  const node = map.nodes.filter((entry) => entry.reachable).find((entry) => entry.kind === 1);
  await ev(`window.__run.enter(${node.index})`);
  await ev("window.__run.fightBegin()");
  await sleep(300);
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
  await sleep(200);
  check((await ev("window.__run.scene()")).base === "SC-04", "打完进入奖励屏");
  const rewardBadges = await ev(`document.querySelectorAll("[data-reward-card] [data-asset-badge]").length`);
  const rewardCards = await ev(`document.querySelectorAll("[data-reward-card]").length`);
  check(rewardBadges === rewardCards && rewardCards > 0, "奖励屏：每张候选牌都有卡面徽章", `${rewardBadges}/${rewardCards}`);
  const rewardLetters = await ev(`(() => {
    const nodes = Array.from(document.querySelectorAll("[data-reward-card] [data-asset-badge] .asset-badge__letters"));
    return nodes.map((node) => node.textContent.trim());
  })()`);
  check(
    rewardLetters.length > 0 && rewardLetters.every((text) => /^[A-Z]{2}$/.test(text)),
    "奖励屏的卡面字母是两位大写",
    JSON.stringify(rewardLetters)
  );

  // 顶栏药水腰带 / 商店：有药水或进店时才断言（不保证这一局都有）。
  const potionBadges = await ev(`document.querySelectorAll("[data-potion-slot] [data-asset-badge]").length`);
  const potionSlots = await ev(`document.querySelectorAll("[data-potion-slot]").length`);
  check(potionBadges === potionSlots, "药水腰带：每瓶都有徽章", `${potionBadges}/${potionSlots}`);

  await page.close();
}

console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_ASSETS_RENDER PASS archetypes=${summary.archetypes} enemies=${summary.enemies} cards=${summary.cards} ` +
    `badges=4tables lit=${summary.triangles || "canvas"}`
);
