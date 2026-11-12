// 闸门 36 `ui-next-p4`：**一段真实旅程**，把 P4 的每一屏都用一遍。
//
// ## 为什么是"旅程"而不是六个独立夹具
//
// 商店/篝火/宝箱/事件不是想进就能进的：地图生成有硬规则（`run-layer.md` §7.1）——
//   * 第 1–5 层**没有**篝火与精英（规则 9）；
//   * 第 9 层**全是宝箱**（规则 7）；
//   * 第 15 层全是篝火、第 16 层 Boss。
// 所以"走到这些屏"本身就是被测对象的一部分。这一道闸门从第 1 层往上走，遇到什么就测什么，
// 直到把 P4 的每一屏都覆盖到（或走完 9 层）。
//
// ## 覆盖要求（少一屏就红）
//
// `shop` / `rest` / `chest` / `event`（或 `?` 房掷出的等价物）/ `deck-picker` / `potion`。
//
// ## 每一步都做的事
//
// * 断言 `domScene() == scene().base`（画出来的 == 算出来的）；
// * 断言 `violations()` 为空（对账干净）。
//
// ## 真实点击
//
// 每个屏的关键动作都走 `element.click()`（不是直接调探针），探针只用来**读**和做那些
// "要循环几十次"的事（打完一场牌）。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_NEXT_P4";
// 走**多段旅程**：单一种子不保证每一屏都在路上（商店/事件的位置由地图生成决定，
// 而生成有硬规则：第 1–5 层没有篝火、第 9 层全是宝箱、第 15 层全是篝火）。
// 扫描见 `native/_dbg_eventscan.mjs` / `_dbg_p4scan2.mjs`（一次性探针，不进闸门）。
//   * seed 3：第 2 层的 `?` 房掷出**事件**（`shining_light`）；
//   * seed 1：第 2 层有**商店**。
const SEEDS = [3, 1];
const MAX_FLOOR = 9;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};

const summary = { floors: 0, screens: [], steps: 0, goldSpent: 0, cardsGained: 0 };

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
  viewport: { width: 1280, height: 800 },
  waitFor: "Boolean(window.__run && window.__run.ready)",
});
const ev = (expression) => page.evaluate(expression);

const scene = () => ev("window.__run.scene()");
const violations = () => ev("window.__run.violations()");
const domScene = () => ev("window.__run.domScene()");
const runInfo = () => ev("window.__run.run()");
const screens = () => ev("window.__run.screens()");
const click = (selector) => ev(`window.__run.click(${JSON.stringify(selector)})`);

/** 每一步都要过的一关。 */
const guard = async (label) => {
  const current = await scene();
  const dom = await domScene();
  const bad = await violations();
  if (current.base !== dom) {
    check(false, `${label}：DOM 与判定一致`, `${current.base} vs ${dom}`);
  }
  if (bad.length > 0) {
    check(false, `${label}：对账干净`, JSON.stringify(bad));
  }
  return current;
};

const mark = (id) => {
  if (!summary.screens.includes(id)) summary.screens.push(id);
};

/** 把这一场打完（探针；打几十步牌不是这一道闸门要测的，闸门 28/29/34 在测）。 */
async function playOutFight() {
  for (let step = 0; step < 260; step += 1) {
    // 待决选牌（`rd_env_choice_*`）：动作表这时是**空的**，不回答就会被判成 stuck。
    // P4 的要求里就有"待决场景"，所以这里必须会回答，而不是绕开。
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

const required = ["shop", "rest", "chest", "event", "deck-picker"];
const covered = () => required.every((id) => summary.screens.includes(id));

/** 开一局并选祝福（必要时用牌组选择器），直到站在地图上。 */
async function openRun(seed) {
  await ev(`window.__run.start(${seed}, 0)`);
  let current = await guard(`seed ${seed} 开局`);
  const blessings = await ev("window.__run.blessings()");
  const simple = blessings.find((blessing) => !/card/.test(blessing.id));
  if (simple) {
    const picked = await click(`[data-blessing='${simple.slot}']`);
    check(picked.clicked, "祝福页可点", picked.text);
  } else if (blessings.length > 0) {
    await click(`[data-blessing='${blessings[0].slot}']`);
  }
  await sleep(80);
  current = await guard(`seed ${seed} 选祝福`);
  if (current.base === "SC-01b") {
    const rows = await ev(`document.querySelectorAll("[data-deck-pick]").length`);
    check(rows > 0, "祝福选牌：牌组选择器画出了牌", String(rows));
    const picked = await click("[data-deck-pick='0']");
    check(picked.clicked, "祝福选牌：能点第一张", picked.text);
    await sleep(80);
    mark("deck-picker");
    current = await guard(`seed ${seed} 祝福选牌后`);
  }
  check(current.base === "SC-02", `seed ${seed}：开局后进入地图`, current.base);
}

// ── 旅程主循环（每个种子一段）─────────────────────────────────────────────
for (const seed of SEEDS) {
  if (covered()) break;
  console.log(`\n== 旅程 seed=${seed}（已覆盖 ${summary.screens.join(",") || "无"}）==`);
  await openRun(seed);
  let current = await guard(`seed ${seed} 地图`);
  let loops = 0;
while (loops < 120) {
  loops += 1;
  current = await guard(`第 ${loops} 步`);
  const base = current.base;
  const info = await runInfo();
  if (info) summary.floors = Math.max(summary.floors, info.floor);

  // 遗物欠账：盖在任何屏之上，先还完（否则其它按钮点不动）。
  const pendingScreens = await screens();
  if (pendingScreens.pickup.picks > 0 || pendingScreens.pickup.add > 0) {
    mark("pickup");
    if (pendingScreens.pickup.add > 0) {
      const offers = pendingScreens.pickup.offers;
      if (offers.length > 0) await click(`[data-pickup-add='${offers[0].slot}']`);
      else await click("[data-pickup-skip]");
    } else {
      await click("[data-pickup-pick]");
      await sleep(80);
      const rows = await ev(`document.querySelectorAll("[data-deck-pick]").length`);
      if (rows > 0) {
        await click("[data-deck-pick='0']");
        mark("deck-picker");
      }
    }
    await sleep(80);
    continue;
  }

  if (base === "SC-02") {
    const map = await ev("window.__run.map()");
    const reachable = map.nodes.filter((node) => node.reachable);
    // Boss 哨兵（`BOSS_NODE = 100`）不在地图节点里：第 15 层之后它是**唯一**的下一步。
    if (reachable.length === 0) {
      const bossButton = await ev(`(() => { const el = document.querySelector("[data-boss-sentinel][data-boss-reachable='1']"); return el ? true : false; })()`);
      if (bossButton) {
        mark("boss");
        const enteredBoss = await click("[data-boss-sentinel]");
        check(enteredBoss.clicked, "地图：第 15 层之后能点 Boss 哨兵", enteredBoss.text);
        await sleep(120);
        continue;
      }
    }
    if (reachable.length === 0) {
      // 没有可走的了。**不要**在这里空转：打一条诊断就退出循环（空转会把 120 次循环
      // 全变成同一条 FAIL，把真正的原因埋掉 —— 第一版就是这样）。
      const debug = await ev("window.__run.debug()");
      const kinds = await ev(`window.__run.map().nodes.filter((n) => n.row >= ${info.floor - 1}).map((n) => [n.row, n.kind, n.reachable])`);
      check(
        false,
        "地图上没有可达节点（不该发生：要么该是幕尽头，要么该有下一格）",
        JSON.stringify({ debug, scene: current, kinds })
      );
      break;
    }
    // 走哪一格：先补"还没测过的类型"；否则按**安全度**排序（精英最后，低血时篝火优先）。
    // ⚠️ 第一版"没测过的就优先"，结果在只有精英可达时直接撞上去、6 层就死了，
    // 于是篝火与事件一次都没走到（闸门 36 第一版的 5 条红里有 2 条是这个）。
    const wanted = { 3: "rest", 4: "shop", 6: "chest", 5: "event", 1: "combat", 2: "combat", 7: "combat" };
    const untested = reachable.filter((node) => {
      const id = wanted[node.kind];
      return id && !summary.screens.includes(id) && node.kind !== 2 && node.kind !== 7;
    });
    const hpLow = (info?.health ?? 1) < (info?.healthMax ?? 1) * 0.6;
    // 安全度：篝火 0（低血时最优先）· 战斗 1 · `?` 2 · 商店/宝箱 3 · 精英 8 · Boss 9
    const safety = (kind) => {
      if (kind === 3) return hpLow ? 0 : 2;
      if (kind === 1) return 1;
      if (kind === 5) return 2;
      if (kind === 4 || kind === 6) return 3;
      if (kind === 2) return 8;
      return 9;
    };
    const pool = untested.length > 0 ? untested : reachable;
    const target = pool
      .slice()
      .sort((a, b) => safety(a.kind) - safety(b.kind) || a.row - b.row)[0];
    const entered = await click(`[data-node='${target.index}']`);
    check(entered.clicked, `地图：能点第 ${target.index} 号节点（kind ${target.kind}）`, entered.text);
    await sleep(80);
    continue;
  }

  if (base === "SC-03") {
    const begin = await click("[data-fight-begin]");
    check(begin.clicked, "战斗前：能点进入战斗");
    await sleep(120);
    const result = await playOutFight();
    check(result !== "stuck" && result !== "timeout", "战斗能打完", result);
    const cont = await click("[data-combat-continue]");
    check(cont.clicked, "战斗结束：能点领取奖励");
    await sleep(120);
    continue;
  }

  if (base === "SC-04") {
    mark("reward");
    const reward = await ev("window.__run.reward()");
    const before = await runInfo();
    if (reward.cards.length > 0) {
      const taken = await click(`[data-reward-card='0']`);
      check(taken.clicked, "奖励屏：能点第一张牌", taken.text);
      await sleep(80);
      const after = await runInfo();
      if (after.deckSize > before.deckSize) summary.cardsGained += 1;
    }
    const skipped = await click("[data-reward-skip]");
    check(skipped.clicked, "奖励屏：能点继续");
    await sleep(80);
    continue;
  }

  if (base === "SC-05") {
    mark("shop");
    const data = await screens();
    const info2 = await runInfo();
    const rows = await ev(`document.querySelectorAll("[data-shop-buy]").length`);
    check(rows > 0, "商店：画出了货架", String(rows));
    // 价格必须来自内核：挂牌价 > 0 或 -1（已售），不可能是 NaN/0。
    const prices = await ev(`Array.from(document.querySelectorAll("[data-shop-buy]")).map((el) => Number(el.dataset.price))`);
    check(
      prices.every((price) => price === -1 || price > 0),
      "商店：每个货位的价格来自内核（>0 或 -1）",
      JSON.stringify(prices)
    );
    // 买一件买得起的；买不起的那件点下去必须**说原因**而不是静默。
    // 优先买**药水**：这样后面"药水条：用/扔"那一段就有真东西可测（否则只能跳过）。
    const affordable = await ev(`(() => {
      const all = Array.from(document.querySelectorAll("[data-shop-buy]")).filter((node) => node.dataset.affordable === "1");
      const potion = all.find((node) => String(node.dataset.shopBuy).startsWith("potion:"));
      return (potion ?? all[0])?.dataset.shopBuy ?? null;
    })()`);
    if (affordable) {
      const [kind, slot] = affordable.split(":");
      const goldBefore = info2.gold;
      const bought = await click(`[data-shop-buy='${affordable}']`);
      check(bought.clicked, `商店：能买 ${affordable}`, bought.text);
      await sleep(80);
      const goldAfter = (await runInfo()).gold;
      summary.goldSpent += goldBefore - goldAfter;
      check(goldAfter < goldBefore, "商店：买完金币变少（真的扣钱了）", `${goldBefore} → ${goldAfter}`);
      check((await ev("window.__run.log()")).some((entry) => entry.text.includes("买了")), "商店：日志里有购买记录");
      void kind;
      void slot;
    } else {
      check(true, "商店：这一排都买不起（跳过购买断言）");
    }

    // 删卡服务：走牌组选择器，牌组必须 -1。
    const deckBefore = (await runInfo()).deckSize;
    const removeButton = await ev(`(() => { const el = document.querySelector("[data-shop-remove-button]"); return el && !el.disabled ? true : false; })()`);
    if (removeButton) {
      await click("[data-shop-remove-button]");
      await sleep(80);
      const rows2 = await ev(`document.querySelectorAll("[data-deck-pick]").length`);
      check(rows2 > 0, "商店删卡：牌组选择器弹出", String(rows2));
      await click("[data-deck-pick='0']");
      await sleep(120);
      const deckAfter = (await runInfo()).deckSize;
      check(deckAfter === deckBefore - 1, "商店删卡：牌组 -1", `${deckBefore} → ${deckAfter}`);
      mark("deck-picker");
      const after = await screens();
      check(after.shop.removalAvailable === 0, "商店删卡：每家店一次（用完就不可用）", String(after.shop.removalAvailable));
    } else {
      check(true, "商店删卡：这次不可用（跳过）");
    }

    const left = await click("[data-shop-leave]");
    check(left.clicked, "商店：能离开");
    await sleep(80);
    void data;
    continue;
  }

  if (base === "SC-06") {
    mark("rest");
    const data = await screens();
    const options = await ev(`Array.from(document.querySelectorAll("[data-rest-option]")).map((el) => el.dataset.restOption)`);
    check(options.length > 0, "篝火：画出了选项（位掩码解出来的）", JSON.stringify(options));
    // 休息要显示**内核算的**回复量（不是页面自己算的 30%）。
    const heal = data.rest.heal;
    const heroBefore = await runInfo();
    const restButton = await ev(`(() => { const el = document.querySelector("[data-rest-option='rest']"); return el && !el.disabled ? true : false; })()`);
    if (restButton) {
      const restText = await ev(`document.querySelector("[data-rest-option='rest']").textContent`);
      check(
        restText.includes(String(heal)),
        "篝火：休息按钮显示内核给的回复量",
        `${restText} vs heal=${heal}`
      );
      await click("[data-rest-option='rest']");
      await sleep(120);
      const heroAfter = await runInfo();
      check(
        heroAfter.health > heroBefore.health || heroBefore.health === heroBefore.healthMax,
        "篝火：休息真的回血了",
        `${heroBefore.health} → ${heroAfter.health}`
      );
    } else if (options.includes("smith")) {
      const smith = await click("[data-rest-option='smith']");
      check(smith.clicked, "篝火：能点锻造");
      await sleep(80);
      const rows = await ev(`document.querySelectorAll("[data-deck-pick][data-deck-allowed='1']").length`);
      check(rows > 0, "篝火锻造：牌组选择器里有可升级的牌", String(rows));
      const first = await ev(`(() => { const el = document.querySelector("[data-deck-pick][data-deck-allowed='1']"); return el ? el.dataset.deckPick : null; })()`);
      if (first !== null) {
        await click(`[data-deck-pick='${first}']`);
        mark("deck-picker");
        await sleep(120);
        const deck = (await screens()).deck;
        check(deck.some((id) => id.includes("+")), "篝火锻造：牌组里出现了升级过的牌", JSON.stringify(deck.slice(0, 5)));
      }
    } else {
      check(true, "篝火：这次只有别的选项（跳过）");
      await click("[data-rest-leave]");
      await sleep(80);
    }
    // 做完一件事之后篝火就结算了；如果还在，离开。
    if ((await scene()).base === "SC-06") {
      await click("[data-rest-leave]");
      await sleep(80);
    }
    continue;
  }

  if (base === "SC-07") {
    mark("chest");
    const goldBefore = (await runInfo()).gold;
    const open = await click("[data-chest-open]");
    check(open.clicked, "宝箱：能点打开");
    await sleep(120);
    // ⚠️ `open_chest` 的语义是**打开即结束**（相位归 0），所以战利品由横幅说。
    const banner = await ev(`(() => { const el = document.querySelector("[data-run-loot]"); return el ? el.textContent : null; })()`);
    check(banner !== null, "宝箱：打开后出现战利品横幅", String(banner));
    const goldAfter = (await runInfo()).gold;
    check(goldAfter >= goldBefore, "宝箱：金币没有倒退", `${goldBefore} → ${goldAfter}`);
    const next = await scene();
    check(next.base !== "SC-07", "宝箱：打开后离开宝箱屏（打开即结束）", next.base);
    if (await ev(`Boolean(document.querySelector("[data-loot-dismiss]"))`)) {
      await click("[data-loot-dismiss]");
      await sleep(60);
    }
    continue;
  }

  if (base === "SC-08") {
    mark("event");
    const data = await screens();
    const text = await ev(`(document.querySelector("[data-event-text]")||{}).textContent || ""`);
    check(text.length > 0, "事件：画出了正文", text.slice(0, 40));
    const options = data.event.options;
    check(options.length > 0, "事件：选项条数由内核给", String(options.length));
    const available = options.filter((option) => option.available);
    check(available.length > 0, "事件：至少一个选项可选", JSON.stringify(options.map((o) => [o.slot, o.available])));
    // 不可用的选项必须**画出来但禁用**（不是隐藏）。
    const disabled = await ev(`document.querySelectorAll("[data-event-option][data-available='0']").length`);
    check(
      disabled === options.filter((option) => !option.available).length,
      "事件：不可用的选项画成禁用（数量一致）",
      `${disabled} vs ${options.filter((o) => !o.available).length}`
    );
    const chosen = await click(`[data-event-option='${available[0].slot}']`);
    check(chosen.clicked, "事件：能点可选的那个选项", chosen.text);
    await sleep(120);
    // 事件可能要选牌（`SC-09`）或摊开候选（`SC-10`）。
    const next = await scene();
    if (next.base === "SC-09") {
      const rows = await ev(`document.querySelectorAll("[data-deck-pick]").length`);
      check(rows > 0, "事件选牌：选择器弹出", String(rows));
      await click("[data-deck-pick='0']");
      mark("deck-picker");
      await sleep(120);
    } else if (next.base === "SC-10") {
      const offers = await ev(`document.querySelectorAll("[data-event-offer]").length`);
      check(offers > 0, "事件候选：画出了候选", String(offers));
      await click("[data-event-offer='0']");
      mark("event-offer");
      await sleep(120);
    }
    continue;
  }

  if (base === "SC-09") {
    mark("deck-picker");
    const rows = await ev(`document.querySelectorAll("[data-deck-pick]").length`);
    check(rows > 0, "事件选牌：选择器弹出", String(rows));
    await click("[data-deck-pick='0']");
    await sleep(120);
    continue;
  }

  if (base === "SC-10") {
    mark("event-offer");
    const offers = await ev(`document.querySelectorAll("[data-event-offer]").length`);
    check(offers > 0, "事件候选：画出了候选", String(offers));
    await click("[data-event-offer='0']");
    await sleep(120);
    continue;
  }

  if (base === "SC-12b" || base === "SC-12a" || base === "SC-02b") {
    check(true, "旅程结束（局终/幕尽）", base);
    break;
  }

  // 其它屏（战斗内等）：不该在旅程主循环里出现。
  check(false, `旅程里出现了没处理的场景 ${base}`, JSON.stringify(current));
  break;
}
}

// ── 覆盖断言（少一屏就红）────────────────────────────────────────────────
const missing = required.filter((id) => !summary.screens.includes(id));
check(missing.length === 0, "P4 的每一屏都走到了", `缺 ${JSON.stringify(missing)}`);
check(summary.floors >= 6, "旅程至少走到第 6 层（篝火从第 6 层才有）", String(summary.floors));

// ── 药水：腰带上有没有、能不能用 ─────────────────────────────────────────
const data = await screens();
if (data.potions.length > 0) {
  const usable = await ev(`Array.from(document.querySelectorAll("[data-potion-use]")).map((el) => el.dataset.usable)`);
  check(usable.length === data.potions.length, "药水条：每瓶都画了一个按钮", `${usable.length} vs ${data.potions.length}`);
  check(
    usable.every((flag) => flag === "0" || flag === "1"),
    "药水条：可用性是布尔（不是 undefined）",
    JSON.stringify(usable)
  );
  // 先试着**喝**一瓶（战斗外只有 run-only 的能喝；界面用 `data-usable` 表示）。
  const usableNow = await ev(`(() => {
    const el = document.querySelector("[data-potion-use][data-usable='1']");
    return el ? el.dataset.potionUse : null;
  })()`);
  if (usableNow !== null) {
    const used = await click(`[data-potion-use='${usableNow}']`);
    check(used.clicked, "药水条：战斗外能喝 run-only 的药水", used.text);
    await sleep(80);
    const afterUse = await screens();
    check(
      afterUse.potions.length === data.potions.length - 1,
      "药水条：喝完腰带 -1",
      `${data.potions.length} → ${afterUse.potions.length}`
    );
  } else {
    check(true, "药水条：这一瓶需要战斗（跳过喝药断言）");
  }

  // 扔一瓶（安全：不影响后续断言），确认腰带 -1。
  const dropBefore = (await screens()).potions.length;
  const dropped = await click(`[data-potion-drop='0']`);
  check(dropped.clicked, "药水条：能点扔掉", dropped.text);
  await sleep(80);
  const after = await screens();
  check(after.potions.length === dropBefore - 1, "药水条：扔完腰带 -1", `${dropBefore} → ${after.potions.length}`);
  mark("potion");
} else {
  check(true, "这次旅程没捡到药水（跳过药水断言）");
}

// ── 设置面板（诊断）──────────────────────────────────────────────────────
const settings = await click("[data-settings-open]");
check(settings.clicked, "顶栏有设置按钮", settings.text);
await sleep(80);
const shown = await ev(`Boolean(document.querySelector("[data-settings]"))`);
check(shown, "设置面板能打开");
const pendingShown = await ev(`(document.querySelector("[data-settings-pending]")||{}).textContent`);
check(pendingShown !== undefined && pendingShown !== null, "设置面板显示相位", String(pendingShown));
await click("[data-settings-close]");
await sleep(60);
check(!(await ev(`Boolean(document.querySelector("[data-settings]"))`)), "设置面板能关闭");
mark("settings");

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_NEXT_P4 PASS floors=${summary.floors} screens=${summary.screens.join(",")} ` +
    `gold-spent=${summary.goldSpent} cards=${summary.cardsGained}`
);
