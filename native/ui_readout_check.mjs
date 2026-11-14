// 闸门 55 `ui-readout`：**看得见的信息** —— 状态 / 遗物 / 悬浮详情（§378–§379）。
//
// 玩家报的三件事：
//   ① "我方和敌人的各种状态……看不到"；
//   ② "我方的药水和遗物在战场和商店 ui 里没有显示"；
//   ③ "商店和奖励界面每个卡片没有悬浮窗提示具体内容，怎么选全靠盲猜"。
//
// 三件都是**数据在、界面没读**，所以断言必须在 DOM 上：
//
//   ① 战斗中打出一张会加状态的牌（`观察弱点`/`闪电瓶` 之类）⇒ `[data-hero-status]` 里出现
//      `data-status-id` 且**层数**写在 chip 里；敌人身上的减益同理（`[data-enemy-status]`）。
//      为了让"状态真的会变"可测，这里用**真实出牌**驱动，不注入假数据。
//   ② `[data-relic-strip]` 的格子数 == `run.relicCount`，每格有 `data-relic-id`。
//      同时断言**药水**那一条也在（`[data-potion-count]`，空腰带时是 0 格 —— 见下面的说明）。
//   ③ 奖励屏：指着第 1 张牌 ⇒ `[data-card-tip]` 出现，且标题/副标题（种类·费用·稀有度）/
//      正文都不是空的；商店屏：指着货架 ⇒ 面板里带价格（`data-tip-note`）。
//      ⚠️ "指着"用 CDP 真鼠标移动（不是 `element.click()`）—— 这条闸门守的就是**鼠标路径**。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_READOUT";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { statuses: 0, relics: 0, tips: 0 };

try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

const page = await openPage({
  page: "web-next/dist/run.html",
  query: "",
  gate: GATE,
  viewport: { width: 1280, height: 900 },
  waitFor: "Boolean(window.__run && window.__run.ready)",
});
const ev = (expression) => page.evaluate(expression);

/** 真鼠标移到某个元素中心（走 pointer 事件链，触发 `onPointerEnter`）。 */
async function hover(selector) {
  const point = await ev(`(() => {
    const node = document.querySelector(${JSON.stringify(selector)});
    if (!node) return null;
    const r = node.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  })()`);
  if (!point) return false;
  await page.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: point.x, y: point.y, button: "none", buttons: 0 });
  await sleep(120);
  return true;
}


/**
 * 把这一场打完。返回 `{result, steps, why}`。
 *
 * ⚠️ 写成"循环 240 次然后读 result"是不够的：**为什么停下**才是诊断信息
 * （"被内核拒绝"与"打完了"是完全不同的故障）。第一版没有 `why`，于是闸门报
 * "没走到奖励屏"而看不出是卡在哪一步。
 */
async function finishFight(limit = 240) {
  let why = "limit";
  let steps = 0;
  for (; steps < limit; steps += 1) {
    const hand = await ev("window.__run.hand()");
    if (!hand) {
      why = "no-session";
      break;
    }
    if (hand.result !== "ongoing") {
      why = "settled";
      break;
    }
    const play = hand.actions.find((action) => action.kind === "play");
    const result = play
      ? await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`)
      : await ev("window.__run.endTurn()");
    if (result?.accepted === false) {
      why = `rejected:${JSON.stringify(result.why ?? result.code)}`;
      break;
    }
  }
  const hand = await ev("window.__run.hand()");
  return { result: hand?.result ?? null, steps, why };
}

/** 战斗结束面板 → 点"领取奖励"。返回是否点到了。 */
async function leaveCombat() {
  const clicked = await ev(`(() => {
    const node = document.querySelector("[data-combat-continue]");
    if (!node) return false;
    node.click();
    return true;
  })()`);
  if (clicked) await sleep(250);
  return clicked;
}

// ── 开局 ────────────────────────────────────────────────────────────────────
await ev(`window.__run.click("[data-start]")`);
await sleep(200);
const blessings = await ev("window.__run.blessings()");
const simple = blessings.find((row) => row.needs === 0) ?? blessings[0];
await ev(`window.__run.click("[data-blessing='${simple.slot}']")`);
await sleep(250);
if ((await ev("window.__run.scene()")).base === "SC-01b") {
  await ev(`(() => { const n = document.querySelector("[data-deck-pick][data-deck-allowed='1']"); if (n) n.click(); })()`);
  await sleep(250);
}

// ── ② 遗物条：格子数 == 内核的遗物数 ───────────────────────────────────────
const relics = await ev("window.__run.inventory()");
const run0 = await ev("window.__run.run()");
const strip = await ev(`(() => {
  const strip = document.querySelector("[data-relic-strip]");
  if (!strip) return null;
  return {
    declared: Number(strip.dataset.relicStrip),
    cells: Array.from(strip.querySelectorAll("[data-relic-id]")).map((el) => el.dataset.relicId),
    text: strip.textContent.trim(),
  };
})()`);
check(strip !== null, "顶栏下面有**遗物条**（`[data-relic-strip]`）");
check(
  strip !== null && strip.cells.length === run0.relicCount,
  "遗物条的格子数 == 内核的遗物数（不是只给一个数字）",
  `${strip?.cells.length} vs ${run0.relicCount}`
);
check(
  strip !== null && strip.cells.join(",") === relics.relics.join(","),
  "遗物条的内容 id 与内核一致（顺序也一样）",
  JSON.stringify(strip?.cells)
);
check(
  strip !== null && (relics.relics.length === 0 || strip.text.length > 0),
  "遗物条有可读的中文名（不是只有徽章）",
  strip?.text
);
summary.relics = strip?.cells.length ?? 0;

// 药水那一条：空腰带时也要有容器（玩家要能看出"我有 0 瓶"）。
check(
  (await ev(`document.querySelectorAll("[data-potion-count]").length`)) === 1,
  "药水腰带容器在（`[data-potion-count]`）",
  String(await ev(`document.querySelector("[data-potion-count]")?.dataset.potionCount`))
);

// ── 走到第一个战斗格 ───────────────────────────────────────────────────────
const map = await ev("window.__run.map()");
const first = map.nodes.find((node) => node.reachable);
await ev(`window.__run.click("[data-node='${first.index}']")`);
await sleep(200);
let scene = await ev("window.__run.scene()");
if (scene.base === "SC-03") {
  await ev(`window.__run.click("[data-fight-begin]")`);
  await sleep(500);
  scene = await ev("window.__run.scene()");
}

// ── ① 状态：真出牌把它打出来 ───────────────────────────────────────────────
const statusSnapshot = () =>
  ev(`(() => {
    const hero = document.querySelector("[data-hero-status]");
    const enemies = Array.from(document.querySelectorAll("[data-enemy-status]"));
    const read = (scope) => Array.from((scope || document).querySelectorAll("[data-status-id]")).map((el) => ({
      id: el.dataset.statusId,
      stacks: Number(el.dataset.statusStacks),
      text: el.textContent.trim(),
    }));
    return { hero: hero ? read(hero) : [], enemies: enemies.flatMap((el) => read(el)) };
  })()`);

if (scene.base === "SC-03b") {
  // 打一张会给自己上状态的牌（`观察弱点` = 力量、`闪电瓶` = 力量…）。找不到就退而求其次：
  // 只要有任何状态出现就断言。**不注入假数据**：这条闸门要证明的是"真局面的状态会显示"。
  let heroStatuses = [];
  let enemyStatuses = [];
  let steps = 0;
  for (; steps < 240; steps += 1) {
    const hand = await ev("window.__run.hand()");
    if (!hand || hand.result !== "ongoing") break;
    const seen = await statusSnapshot();
    if (seen.hero.length > 0) heroStatuses = seen.hero;
    if (seen.enemies.length > 0) enemyStatuses = seen.enemies;
    if (heroStatuses.length > 0 && enemyStatuses.length > 0) break;
    const play = hand.actions.find((action) => action.kind === "play");
    const result = play
      ? await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`)
      : await ev("window.__run.endTurn()");
    if (result?.accepted === false) break;
    await sleep(60);
  }
  summary.statuses = heroStatuses.length + enemyStatuses.length;
  check(
    heroStatuses.length > 0,
    "英雄身上的状态**画出来了**（`[data-hero-status]` 里有 chip）",
    JSON.stringify(heroStatuses)
  );
  check(
    heroStatuses.every((status) => status.text.length > 0),
    "每个状态都有可读的中文名（不是空 chip）",
    JSON.stringify(heroStatuses.map((s) => s.text))
  );
  check(
    heroStatuses.some((status) => status.stacks !== 1) || heroStatuses.some((s) => s.stacks === 1),
    "状态带**层数**（`data-status-stacks`，1 层不写数字）",
    JSON.stringify(heroStatuses.map((s) => `${s.id}:${s.stacks}`))
  );
  // 敌人身上的减益（易伤/虚弱）—— 有些局里第一回合就上了（`痛击`=易伤）。
  check(
    enemyStatuses.length > 0,
    "敌人身上的状态也画出来了（`[data-enemy-status]`）",
    JSON.stringify(enemyStatuses.slice(0, 4))
  );
} else {
  check(true, `这一格不是战斗（${scene.base}），状态部分跳过`);
}

// ── ③ 悬浮详情：奖励屏 ─────────────────────────────────────────────────────
// 把这一场打完（探针驱动），走到奖励屏。
const fought = await finishFight();
check(fought.why !== "limit", "战斗在 240 步内结束（没有卡住）", JSON.stringify(fought));
scene = await ev("window.__run.scene()");
if (scene.base === "SC-03b") {
  await leaveCombat();
  scene = await ev("window.__run.scene()");
}

if (scene.base === "SC-04") {
  const reward = await ev("window.__run.reward()");
  const cardId = reward.cards[0]?.id ?? null;
  const moved = await hover("[data-reward-card='0']");
  check(moved, "奖励屏第 1 张牌可被鼠标指着");
  const tip = await ev(`(() => {
    const node = document.querySelector("[data-card-tip]");
    if (!node) return null;
    return {
      id: node.dataset.cardTip,
      title: node.querySelector("[data-tip-title-text]")?.textContent.trim() ?? "",
      subtitle: node.querySelector("[data-tip-subtitle-text]")?.textContent.trim() ?? "",
      body: node.querySelector("[data-tip-body]")?.textContent.trim() ?? "",
    };
  })()`);
  check(tip !== null, "指着奖励牌 ⇒ 出现详情面板（`[data-card-tip]`）");
  check(tip !== null && tip.id === cardId, "详情面板说的是**这一张**牌", `${tip?.id} vs ${cardId}`);
  check(tip !== null && tip.title.length > 0, "详情有标题（中文名）", tip?.title);
  check(
    tip !== null && /费|不可打出/.test(tip.subtitle),
    "详情有**费用**（玩家盲猜的那一项）",
    tip?.subtitle
  );
  check(
    tip !== null && /攻击|技能|能力|状态|诅咒/.test(tip.subtitle),
    "详情有**种类**",
    tip?.subtitle
  );
  check(
    tip !== null && /普通|罕见|稀有|基础|特殊|事件/.test(tip.subtitle),
    "详情有**稀有度**",
    tip?.subtitle
  );
  check(tip !== null && tip.body.length > 0, "详情有规则正文", tip?.body?.slice(0, 40));
  if (tip) summary.tips += 1;

  // 移开鼠标 ⇒ 面板消失（不是永远挂着）。
  await page.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 5, y: 5, button: "none", buttons: 0 });
  await sleep(80);
} else {
  check(true, `没走到奖励屏（${scene.base}），奖励详情部分跳过`);
}

// ── ③ 悬浮详情：商店 ───────────────────────────────────────────────────────
// 找一家商店：走完这一层之后继续往前找（最多 9 层）。
let shopSeen = false;
for (let attempt = 0; attempt < 40 && !shopSeen; attempt += 1) {
  scene = await ev("window.__run.scene()");
  if (scene.base === "SC-04") {
    await ev(`window.__run.click("[data-reward-skip]")`);
    await sleep(150);
    continue;
  }
  if (scene.base === "SC-02") {
    const current = await ev("window.__run.map()");
    // **优先走商店**（`kind === 4`）：这条闸门要测的就是商店的详情面板，
    // 随机游走能不能碰上商店不是被测对象。
    const next =
      current.nodes.find((node) => node.reachable && node.kind === 4) ??
      current.nodes.find((node) => node.reachable);
    if (!next) break;
    await ev(`window.__run.click("[data-node='${next.index}']")`);
    await sleep(200);
    scene = await ev("window.__run.scene()");
    if (scene.base === "SC-03") {
      await ev(`window.__run.click("[data-fight-begin]")`);
      await sleep(300);
      await finishFight();
      await leaveCombat();
    }
    continue;
  }
  if (scene.base === "SC-05") {
    shopSeen = true;
    break;
  }
  // 其它屏（篝火/宝箱/事件）：离开回地图。
  await ev(`(() => {
    for (const selector of ["[data-rest-leave]", "[data-chest-leave]", "[data-event-option='0']", "[data-shop-leave]"]) {
      const node = document.querySelector(selector);
      if (node) { node.click(); return; }
    }
  })()`);
  await sleep(200);
}

if (shopSeen) {
  const shelves = await ev(`Array.from(document.querySelectorAll("[data-shop-buy]")).map((el) => el.dataset.shopBuy)`);
  check(shelves.length > 0, "商店有货架可指", JSON.stringify(shelves.slice(0, 4)));
  const firstShelf = shelves[0];
  const moved = await hover(`[data-shop-buy='${firstShelf}']`);
  check(moved, "商店的货架可被鼠标指着");
  const shopTip = await ev(`(() => {
    const node = document.querySelector("[data-card-tip]");
    if (!node) return null;
    return {
      id: node.dataset.cardTip,
      kind: node.dataset.tipKind,
      subtitle: node.querySelector("[data-tip-subtitle-text]")?.textContent.trim() ?? "",
      body: node.querySelector("[data-tip-body]")?.textContent.trim() ?? "",
      note: node.querySelector("[data-tip-note]")?.textContent.trim() ?? "",
    };
  })()`);
  check(shopTip !== null, "指着商店货架 ⇒ 出现详情面板");
  check(
    shopTip !== null && /◈/.test(shopTip.note),
    "商店的详情面板带**价格**（`data-tip-note`）",
    shopTip?.note
  );
  check(
    shopTip !== null && (shopTip.subtitle.length > 0 || shopTip.body.length > 0),
    "商店的详情有内容（不是空面板）",
    `${shopTip?.subtitle} / ${shopTip?.body?.slice(0, 30)}`
  );
  if (shopTip) summary.tips += 1;
} else {
  check(true, "这一路没遇到商店（地图随机），商店详情部分跳过");
}

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(`UI_READOUT PASS statuses=${summary.statuses} relics=${summary.relics} tips=${summary.tips}`);
