// ui_test.mjs -- assert what the page *displays*, not just that it parses.
//
//   node web/ui_test.mjs
//
// Gate 14 (`web/smoke.mjs`) proves the page's offsets tile and its script parses; it cannot see a
// wrong cell. This test loads the same `.wasm` the page loads, drives it, and asserts the values
// `web/ui_render.js` produces for those observations -- so `o[H.HP_MAX]` where `o[H.HP]` belongs
// is a red test instead of a green gate.
//
// It is deliberately **not** a DOM test: the describers are pure, so there is no DOM to fake.

import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const HERE = new URL("./", import.meta.url);
const fail = (message) => { console.error("UI_TEST FAIL: " + message); process.exit(1); };

// ---------------------------------------------------------------------------------------------
// Every node-panel state, as a **literal snapshot**. This is the payoff of `ui_panels.js`: the panel
// has ten states and each one is a pure function of data, so all ten can be asserted here without a
// browser. Before the refactor this file could only check "the page mentions the export".
//
// The rule for a new state: add a case to `RD_PANELS.describe`, add a row here. If the row is missing
// the state is simply untested, which `STATE_IDS` below makes visible.
// ---------------------------------------------------------------------------------------------

// ---------------------------------------------------------------------------------------------
// Load `ui_render.js` the way the browser would: run it, then read the global it defines.
// ---------------------------------------------------------------------------------------------
const source = await readFile(new URL("./ui_render.js", HERE), "utf8");
const context = vm.createContext({});
new vm.Script(source, { filename: "ui_render.js" }).runInContext(context);
const UI = context.RD_UI;
if (!UI) fail("ui_render.js did not define globalThis.RD_UI");

// `ui_panels.js` is the second pure module: the node panel's decisions, as data.
const panelsSource = await readFile(new URL("./ui_panels.js", HERE), "utf8");
new vm.Script(panelsSource, { filename: "ui_panels.js" }).runInContext(context);
const P = context.RD_PANELS;
if (!P) fail("ui_panels.js did not define RD_PANELS");

const BASE = {
  mode: "run", runOver: false, runOverWhy: "", cleared: false, act: 1, pending: 0, kind: -1,
  resolved: false, actionCount: 0, floor: 0, hp: 80, hpMax: 80, gold: 0, deckCount: 10,
  relicCount: 1, bossName: "Slime Boss", offers: [], shopCards: [], shopRelics: [],
  rewardCards: [], choices: [], rewardPotion: null,
};

const PANEL_STATES = [
  ["blessing", {
      ...BASE,
      pending: 6,
      offers: [
        { name: "治疗", gain: 1, gainAmount: 25, cost: 5, costAmount: 0 },
        { name: "财宝", gain: 2, gainAmount: 100, cost: 3, costAmount: 7 },
      ],
    }, ["choose_start", "choose_start"], ["治疗", "财宝"], "塔底"],
  ["fight", { ...BASE, kind: 1, actionCount: 1 }, ["begin_fight"], ["开始战斗"], "战斗节点"],
  ["fight settled", { ...BASE, kind: 1, resolved: true }, [], [], "已结算"],
  ["boss", { ...BASE, kind: 7, actionCount: 1 }, ["begin_fight"], ["开始战斗"], "Boss"],
  // §259: the campfire is a **bit mask** from the kernel now. `campfire: 63` = all six options
  // (Rest 1 | Smith 2 | Recall 4 | Lift 8 | Toke 16 | Dig 32).
  ["rest", { ...BASE, kind: 3, pending: 1, hpMax: 80, campfire: 63, giryaLifts: 1, restHeal: 24 },
    ["rest", "smith", "lift", "toke", "dig", "recall", "leave"],
    ["休息", "打铁", "举铁", "抽烟斗", "挖掘", "回想", "离开"], "篝火"],
  // The **falsifiable half**: with `Coffee Dripper` the kernel clears the Rest bit, and the page
  // must not draw a Rest button. A test that only checked the all-six case would keep passing if
  // the page ignored the mask and always rendered everything.
  ["rest without rest", {
      ...BASE, kind: 3, pending: 1, hpMax: 80, campfire: 2, giryaLifts: 0, restHeal: 24,
    }, ["smith", "leave"], ["打铁", "离开"], "篝火"],
  ["chest", { ...BASE, kind: 6, pending: 3 }, ["open_chest", "leave"], ["开箱", "离开"], "宝箱"],
  ["shop", { ...BASE, kind: 4, pending: 2, removePrice: 75, shopCards: [
      { id: "anger", title: "", chip: "", price: 50 }, { id: "uppercut", title: "", chip: "", price: -1 }],
      shopRelics: [{ id: "burning_blood", title: "", price: 150 }] },
    // The buys are **rows**, not footer buttons -- their actions are asserted below.
    ["remove_card", "leave"], ["删一张牌", "离开"], "商店"],
  ["reward", { ...BASE, kind: 1, pending: 4, rewardGold: 17, rewardCards: [
      { id: "anger", title: "Anger", chip: "" }, { id: "uppercut", title: "Uppercut", chip: "" }] },
    // The cards are rows too; only the skip is a footer button.
    ["skip_reward"], ["跳过"], "战斗奖励"],
  ["reward with potion", { ...BASE, kind: 1, pending: 4, rewardGold: 12,
      rewardCards: [{ id: "anger", title: "Anger", chip: "" }], rewardPotion: "fire_potion" },
    ["skip_reward"], ["跳过"], "药水"],
  // §155: an elite (or boss) also pays a **relic**, on its own row with its own button.
  ["reward with relic", { ...BASE, kind: 2, pending: 4, rewardGold: 30,
      rewardCards: [{ id: "anger", title: "Anger", chip: "" }], rewardRelic: "vajra" },
    ["skip_reward"], ["跳过"], "遗物"],
  ["event", { ...BASE, kind: 5, pending: 5, eventText: "old_shrine — A shrine",
      choices: [{ label: "Pray", effect: 1, amount: 15 }, { label: "Leave", effect: 5, amount: 0 }] },
    ["event_choice", "event_choice"], ["Pray", "Leave"], "未知房间"],
  // §279: 条件不成立的选项**不画**，而留下的那个按钮必须带**它自己的槽号** ——
  // 如果面板用"过滤后的下标"，这里的 `Leave`（槽 1）会变成一个打给槽 0 的按钮，
  // 而屏幕上完全正常。
  ["event with a locked option", { ...BASE, kind: 5, pending: 5,
      eventText: "forgotten_altar — An altar",
      choices: [
        { slot: 0, available: false, label: "Offer: Golden Idol", effect: 10, amount: 1, effects: [] },
        { slot: 1, available: true, label: "Sacrifice", effect: 4, amount: 5, effects: [] },
        { slot: 2, available: true, label: "Leave", effect: 5, amount: 0, effects: [] },
      ] },
    ["event_choice", "event_choice"], ["Sacrifice", "Leave"], "未知房间"],
  // §143: the two new event states. A deck-editing choice shows as a named effect (no amount), and
  // the pick phase names **which** edit is owed.
  ["event deck edit", { ...BASE, kind: 5, pending: 5, eventText: "ancient_writing — Glyphs",
      choices: [{ label: "Study", effect: 7, amount: 0 }, { label: "Leave", effect: 5, amount: 0 }] },
    ["event_choice", "event_choice"], ["Study", "Leave"], "未知房间"],
  ["event owes a pick", { ...BASE, kind: 5, pending: 8, eventNeeds: 2 },
    ["event_card"], ["选一张牌"], "升级哪一张牌"],
  ["cleared", { ...BASE, cleared: true, act: 3, kind: 7, floor: 16 },
    ["restart", "next_seed"], ["再打一局", "换一个 seed"], "第 3 幕通关"],
  ["run over", { ...BASE, runOver: true, runOverWhy: "倒了", floor: 7 },
    ["restart", "next_seed"], ["再来一局", "换一个 seed"], "结束了"],
  ["idle before start", { ...BASE }, [], [], "还没出发"],
  // §293：加牌问句（`orrery` = 5、`tiny_house` = 1）。三个候选是**行**，动作带内核的槽号；
  // 按钮是"跳过"，而**持有 `singing_bowl`** 时才多一个"+2 上限"。
  ["pickup add cards", { ...BASE, kind: 3, pending: 3, pickupAdd: 2, singingBowl: true,
      pickupOffer: [
        { slot: 0, title: "Strike" }, { slot: 1, title: "Bash" }, { slot: 2, title: "Anger" },
      ] },
    ["pickup_add_max_hp", "pickup_add_skip"], ["+2 上限", "跳过"], "挑一张牌加入牌组"],
];

{
  // §155: the relic reward is a **row**, so the footer-button loop below cannot see it. Assert the
  // row's own action -- otherwise the relic would be drawn with a button that does nothing (§150).
  const withRelic = P.describe({ ...BASE, kind: 2, pending: 4, rewardGold: 30,
    rewardCards: [{ id: "anger", title: "Anger", chip: "" }], rewardRelic: "vajra" });
  const relicRow = (withRelic.rows || []).find((row) => String(row.label).includes("遗物"));
  if (!relicRow) fail("a reward with a relic draws no 遗物 row");
  if (String(relicRow.label).indexOf("vajra") < 0) {
    fail("the relic row does not name the relic: " + JSON.stringify(relicRow.label));
  }
  if (!relicRow.button || relicRow.button.action.kind !== "take_relic") {
    fail("the relic row's button is " + JSON.stringify(relicRow.button) + ", expected take_relic");
  }
  if (String(relicRow.button.label).indexOf("拿") < 0) {
    fail("the relic row's button says " + JSON.stringify(relicRow.button.label));
  }
  // ...and a normal fight must not draw one.
  const noRelic = P.describe({ ...BASE, kind: 1, pending: 4, rewardGold: 12,
    rewardCards: [{ id: "anger", title: "Anger", chip: "" }] });
  if ((noRelic.rows || []).some((row) => String(row.label).includes("遗物"))) {
    fail("a normal fight drew a relic row");
  }

  {
    // §293：加牌问句的**每一行**都必须带 `pickup_add_card` 与**内核的槽号**（数组下标会漂 ——
    // §161.8 的教训），而且没有 `singing_bowl` 时不许出现"+2 上限"（那是死按钮）。
    const withBowl = P.describe({ ...BASE, kind: 3, pickupAdd: 3, singingBowl: true,
      pickupOffer: [{ slot: 0, title: "Strike" }, { slot: 1, title: "Bash" }] });
    if ((withBowl.rows || []).length !== 2) {
      fail(`pickup add: ${withBowl.rows.length} rows, expected 2`);
    }
    withBowl.rows.forEach((row, index) => {
      const action = row.button && row.button.action;
      if (!action || action.kind !== "pickup_add_card") {
        fail(`pickup add row ${index} has action ${JSON.stringify(action)}`);
      }
      if (action.slot !== index) {
        fail(`pickup add row ${index} carries slot ${action.slot}, expected ${index}`);
      }
    });
    if (!withBowl.buttons.some((b) => b.action.kind === "pickup_add_max_hp")) {
      fail("pickup add with singing_bowl draws no +2 上限 button");
    }
    const withoutBowl = P.describe({ ...BASE, kind: 3, pickupAdd: 1, singingBowl: false,
      pickupOffer: [{ slot: 0, title: "Strike" }] });
    if (withoutBowl.buttons.some((b) => b.action.kind === "pickup_add_max_hp")) {
      fail("pickup add without singing_bowl still draws the +2 上限 button (a dead button)");
    }
    // 奖励屏上同理：`singing_bowl` 只在牌还在时才有那个按钮。
    const rewardWithBowl = P.describe({ ...BASE, kind: 2, pending: 4, rewardGold: 20,
      singingBowl: true, rewardCards: [{ id: "anger", title: "Anger", chip: "" }] });
    if (!rewardWithBowl.buttons.some((b) => b.action.kind === "take_max_hp_instead")) {
      fail("a reward with singing_bowl draws no max-HP button");
    }
    const rewardTaken = P.describe({ ...BASE, kind: 2, pending: 4, rewardGold: 20,
      singingBowl: true, rewardCards: [] });
    if (rewardTaken.buttons.some((b) => b.action.kind === "take_max_hp_instead")) {
      fail("a reward whose cards are gone still draws the max-HP button (a dead button)");
    }
  }

  // §320: the event's candidate list (`Pending::EventOffer` = 9). Its buttons live on the **rows**
  // (one per candidate), so `PANEL_STATES` -- which only describes top-level buttons -- cannot
  // express it. Two shapes are checked because the panel code is one: `The Library` offers 20,
  // `Sensory Stone` offers 3, and a panel that hard-codes either number must fail on the other.
  for (const count of [20, 3]) {
    const offer = [];
    for (let slot = 0; slot < count; slot++) {
      offer.push({ slot, id: `card_${slot}`, title: `Card ${slot}` });
    }
    const d = P.describe({ ...BASE, kind: 5, pending: 9, eventOffer: offer });
    if ((d.rows || []).length !== count) {
      fail(`offer(${count}): the panel shows ${(d.rows || []).length} rows`);
    }
    if (!d.title.includes(String(count))) {
      fail(`offer(${count}): the title "${d.title}" does not say how many there are`);
    }
    d.rows.forEach((row, index) => {
      if (!row.button || row.button.action.kind !== "event_offer_take") {
        fail(`offer(${count}) row ${index}: no take button`);
      }
      // ★ 槽号必须是**内核**给的那个（快照里的 `slot`），不是数组下标 —— 这里故意把
      // 槽号打乱，按下标取值的实现会红。
      if (row.button.action.slot !== offer[index].slot) {
        fail(`offer(${count}) row ${index}: slot ${row.button.action.slot}, expected ${offer[index].slot}`);
      }
      if (!String(row.label).includes(String(index))) {
        fail(`offer(${count}) row ${index}: label "${row.label}" is not the card's title`);
      }
    });
  }
  // 空候选：面板不该画出一张空桌子（那是一个"点了没反应"的屏）。
  {
    const d = P.describe({ ...BASE, kind: 5, pending: 9, eventOffer: [] });
    if ((d.rows || []).length !== 0) {
      fail("an empty offer draws rows out of nowhere");
    }
  }

  for (const [name, snapshot, kinds, labels, titlePart] of PANEL_STATES) {
    const d = P.describe(snapshot);
    const gotKinds = (d.buttons || []).map((b) => b.action.kind);
    if (gotKinds.join(",") !== kinds.join(",")) {
      fail(`panel "${name}": actions [${gotKinds}] but expected [${kinds}]`);
    }
    for (let i = 0; i < labels.length; i++) {
      if (!String(d.buttons[i].label).includes(labels[i])) {
        fail(`panel "${name}": button ${i} is "${d.buttons[i].label}", expected "${labels[i]}"`);
      }
    }
    // The whole visible text: a row label is as visible as the heading, and a state may
    // carry its information in either.
    const heading = [
      d.title,
      ...(d.lines || []),
      ...(d.rows || []).map((r) => `${r.label} ${r.value}`),
    ]
      .join(" ")
      .trim();
    if (!heading.includes(titlePart)) {
      fail(`panel "${name}": heading "${heading}" does not mention "${titlePart}"`);
    }
    // A button whose action the page cannot wire is a dead button; `PANEL_ACTIONS` is checked below.
    for (const b of d.buttons) {
      if (!b.action || typeof b.action.kind !== "string") {
        fail(`panel "${name}": a button has no action kind`);
      }
    }
  }
  // The two row-buttons of the shop are rows, not footer buttons: they must still carry actions.
  const shop = P.describe(PANEL_STATES.find((s) => s[0] === "shop")[1]);
  if (shop.rows.length !== 3) fail(`shop has ${shop.rows.length} rows, expected 3`);
  for (const row of shop.rows) {
    if (!row.button || !row.button.action || typeof row.button.action.kind !== "string") {
      fail("a shop row has no action");
    }
  }
  if (shop.rows[1].disabled !== true) fail("a sold-out shop row must be disabled");
  // Every tradable row must say **which card it is**, or shift+click has nothing to open -- this is
  // the wiring behind "buying was blind guessing" (`port-plan.md` §95).
  for (const row of shop.rows) {
    // Only the **card** rows are cards; a relic row has no card to describe.
    if (row.button.action.kind === "buy_card" && !row.card?.startsWith("shop:")) {
      fail("a shop card row has no card origin: " + row.card);
    }
  }
  for (const row of P.describe(PANEL_STATES.find((s) => s[0] === "reward")[1]).rows) {
    if (!row.card?.startsWith("reward:")) {
      fail("a reward row has no card origin: " + row.card);
    }
  }
  console.log(`  panels: ${PANEL_STATES.length} states, actions and headings agree`);
}



// The page must actually use it, or this whole file is testing dead code.
const page = await readFile(new URL("./index.html", HERE), "utf8");

// **A button the page cannot wire is a dead button.** The comment in the panel loop above claimed
// this was checked "below"; until §143 it was not -- `event_card` could have been added to
// `RD_PANELS` alone and the only symptom would be a throw on click, in the browser, for a player.
{
  const start = page.indexOf("const PANEL_ACTIONS");
  if (start < 0) fail("index.html has no PANEL_ACTIONS table");
  const end = page.indexOf("\n};", start);
  const body = page.slice(start, end < 0 ? page.length : end);
  const wired = new Set(
    [...body.matchAll(/^ {2}([a-z_]+) *:/gm)].map((m) => m[1])
  );
  if (wired.size < 10) fail(`PANEL_ACTIONS parsed as only ${wired.size} entries: ${[...wired]}`);
  const wanted = new Set();
  for (const [, snapshot] of PANEL_STATES) {
    const d = P.describe(snapshot);
    for (const b of [...(d.buttons || []), ...(d.rows || []).map((r) => r.button).filter(Boolean)]) {
      wanted.add(b.action.kind);
    }
  }
  // The states above are a sample; the row actions of a shop are the ones most likely to be missed.
  for (const kind of ["event_card", "blessing_card", "buy_card", "buy_relic", "take_card"]) {
    wanted.add(kind);
  }
  for (const kind of wanted) {
    if (!wired.has(kind)) {
      fail(`panel action "${kind}" is described by ui_panels.js but index.html cannot wire it`);
    }
  }
  console.log(`  panels: ${wanted.size} action kinds all wired in index.html`);
}

// §136: the act transition is a **screen**. The page must own one, and a new act must show it.
for (const id of ["actCurtain", "curtainAct"]) {
  if (!page.includes('id="' + id + '"')) fail(`the act curtain is missing #${id}`);
}
if (!page.includes("showActCurtain(")) fail("nothing ever calls showActCurtain");
if (!page.includes('src="./ui_render.js"')) {
  fail("index.html does not load ui_render.js -- the describers below would be dead code");
}
if (!page.includes("RD_UI.describe(")) {
  fail("index.html loads ui_render.js but never calls RD_UI.describe() -- same problem, one step later");
}
// And the U2 surfaces: a pure function nobody calls is dead code, and the mutation sweep proved this
// needs saying -- deleting `appendLog(diff)` from the page left every assertion above green.
for (const [needle, why] of [
  ["RD_UI.animationPlan(", "the animation plan is computed and then never drawn"],
  ["appendLog(diff);", "the battle log is computed and then never shown"],
  ['id="log"', "there is no log panel for it to append to"],
  ['id="floats"', "there is no layer for the damage numbers to float in"],
  ["rd_env_card_title_len", "the card face would never show the content's title"],
  ["rd_env_card_text_len", "the card face would never show the content's description"],
  ["rd_env_card_kind(", "no card would say whether it is an attack or a skill"],
  ["RD_UI.actionFor(", "a drop would never consult the decision function"],
  ["RD_UI.soundPlan(", "the sound plan is computed and then never played"],
  ["rd_run_fight_begin(", "the page never starts a fight from the run"],
  ["rd_run_fight_end(", "a finished fight is never folded back into the run"],
  ["rd_run_begin_node(", "walking onto a node never asks what it needs"],
  ["rd_run_rest(", "the rest site has no button behind it"],
  ["rd_run_buy_card(", "the merchant cannot sell anything"],
  ["rd_run_take_card(", "the reward screen has no way to take the card"],
  ["rd_run_potion_count", "the page would show no potion belt"],
  ["rd_run_drop_potion(", "a potion could never be dropped"],
  ["rd_env_use_potion(", "a potion could never be used"],
  // `#msg` must have exactly **one** writer (`say`); the rule that was broken twice for `#nodePanel`.
  ["function say(", "the message strip has no single writer"],
  // §97: a card you cannot afford and an enemy that will hit are both *visible*, and a click that
  // cannot happen says why instead of doing nothing.
  ["unaffordable", "an unaffordable card would look the same as a playable one"],
  ["threat", "a threatening enemy would look the same as a harmless one"],
  ["只能走点亮的节点", "clicking an unreachable node would say nothing at all"],
  ["rd_run_start_offer_len", "the run would open with no blessing to choose"],
  ["rd_run_choose_start(", "the blessing could never be taken"],
  ["rd_run_event_text_len", "an unknown room would show no event"],
  ["rd_run_choose(", "an event choice could never be taken"],
  // Smith and removal are *choices*: a page that calls them with a literal 0 has turned them back
  // into "the first card". The picker's click path needs a real browser with a rest node (floor 15
  // is the only guaranteed one), so what is asserted here is the wiring: the page builds a picker
  // and calls both exports with the index it was handed.
  ["showDeckPicker(", "there is no card picker for smith or removal"],
  ["rd_run_smith(index)", "smith does not use the card the player picked"],
  ["rd_run_remove_card(index)", "card removal does not use the card the player picked"],
  ["rd_run_skip_reward(", "the reward screen cannot be declined"],
  ["rd_run_deck_title_len", "the deck panel would list ids instead of titles"],
  ["rd_env_pile_card_title_len", "the pile panels would list nothing"],
  ['id="mapbox"', "there is no map on the page"],
  ['id="nodePanel"', "there is no node panel for a rest site or a merchant"],
  ['addEventListener("pointerdown"', "the drag is never wired up"],
  ['addEventListener("pointerup"', "the drag is never wired up"],
]) {
  if (!page.includes(needle)) fail(`index.html does not use ${needle}: ${why}`);
}

// ---------------------------------------------------------------------------------------------
// The module, driven by the real fight.
// ---------------------------------------------------------------------------------------------
const bytes = await readFile(new URL("./rd_wasm.wasm", HERE));
const { instance } = await WebAssembly.instantiate(bytes, {});
const ex = instance.exports;

const OBS_LEN = ex.rd_env_observe_len();
const obs = () => new Int32Array(ex.memory.buffer, ex.rd_env_observe_buf(), OBS_LEN).slice();

// §146: an X-cost card must **print X**, not "0". The kernel reports `X_COST_DISPLAY` in the cost
// cell (a fixed cost of 0 would be a lie the player acts on: it looks free), and this pins that the
// page turns that cell into the letter -- and that the page's copy of the number equals the
// module's. The number is spelled in two places (`rd_wasm::X_COST_DISPLAY` and `ui_render.js`);
// this is the assertion that keeps them from drifting.
{
  const synthetic = obs();
  synthetic[UI.H.HAND] = 1;
  synthetic[UI.H.ENERGY] = 3;
  for (let i = 0; i < 4; i++) synthetic[UI.OFF_HAND + i] = -1;
  synthetic[UI.OFF_HAND] = 1;
  synthetic[UI.OFF_HAND + 1] = UI.X_COST_DISPLAY;
  synthetic[UI.OFF_HAND + 2] = 0;
  const cell = UI.describe(synthetic, [], { cardName: () => "Whirlwind" }, null).hand[0];
  if (cell.cost !== UI.X_COST_DISPLAY) fail(`an X-cost cell kept its raw cost ${cell.cost}`);
  if (cell.costText !== "X") fail(`an X-cost card must print "X", got "${cell.costText}"`);
  if (!cell.affordable) fail("an X-cost card is affordable whenever there is any energy");
  // The module's constant is the authority; if the page ever spelled a different number the check
  // above would still pass (both sides are the page), so compare against the Rust export's docs.
  if (UI.X_COST_DISPLAY !== -2) {
    fail(`ui_render.js spells X_COST_DISPLAY as ${UI.X_COST_DISPLAY}, rd_wasm uses -2`);
  }
  // ... and with no energy it is *still* playable at X = 0, which `affordable` must reflect:
  synthetic[UI.H.ENERGY] = 0;
  const broke = UI.describe(synthetic, [], { cardName: () => "Whirlwind" }, null).hand[0];
  if (broke.affordable) fail("0 energy makes X = 0, and X = 0 is not affordable");
  console.log('  x-cost           prints "X", affordable only with energy');
}

// ---------------------------------------------------------------------------------------------
// **The battle log must not lie.** `diffObservations` is what the log is made of, and it is pure --
// but it is fed by two observation vectors, so a stale `before` produced a log line for damage that
// happened *outside* the step (reported by hand: "bash 打出后英雄受到 7 点伤害", where the 7 was the
// tower blessing's cost).
//
// The invariant needs **no hand-written expectation**, which is the point: for every step of a real
// fight, the health changes the log *claims* must equal the health changes the two vectors actually
// show. An event without a change (phantom) and a change without an event (silent) both fail.
//
// ⚠️ **What it cannot catch, measured.** Freezing the baseline (\efore\ never advancing -- the exact
// bug that was reported) does **not** turn this red, because both sides of the comparison use the same
// frozen pair. A stale baseline is caught by the *Rust* test
// \_fight_starts_at_the_runs_health_and_the_observation_agrees\, which compares the published vector
// against the run's own health -- an **independent** truth. This check earns its keep on a different
// failure: the diff reading the wrong cells (an offset bug) or inventing an event.
// ---------------------------------------------------------------------------------------------
{
  const HERO_HP = 4;
  const HERO_ENERGY = 8;
  const ENEMIES = 11;
  const ENEMY_BASE = 17; // `ui_render.js`'s OFF_ENEMY (4 slots x 8)
  const reflect = UI.diffObservations;

  const claimed = (events, side, slot) =>
    events
      .filter((e) => e.side === side && (slot === undefined || e.slot === slot))
      .filter((e) => e.kind === "damage" || e.kind === "heal")
      .reduce((sum, e) => sum + (e.kind === "heal" ? e.amount : -e.amount), 0);

  ex.rd_env_reset();
  let before = obs();
  let checked = 0;
  let played = 0;
  for (let step = 0; step < 24 && ex.rd_env_done() === 0; step++) {
    // A card if one is playable (kind 0); otherwise the end-turn entry of the action table.
    let action = -1;
    let endTurn = -1;
    for (let i = 0; i < ex.rd_env_action_count(); i++) {
      const kind = ex.rd_env_action_kind(i);
      if (kind === 0 && action < 0) action = i;
      if (kind === 1) endTurn = i;
    }
    const wasEndTurn = action < 0;
    if (wasEndTurn) action = endTurn;
    if (action < 0) break;
    if (!wasEndTurn) played++;

    const verdict = ex.rd_env_step(action);
    const after = obs();
    if (verdict >= 0) {
      const { events } = reflect(before, after, wasEndTurn);
      const trail = events
        .map((e) => e.kind + ':' + (e.side || '-') + ':' + (e.slot ?? '-') + ':' + (e.amount ?? e.spent ?? ''))
        .join(' ');

      const heroClaimed = claimed(events, 'hero');
      const heroActual = after[HERO_HP] - before[HERO_HP];
      if (heroClaimed !== heroActual) {
        fail(
          'step ' + step + ' (' + (wasEndTurn ? 'end turn' : 'card') + '): log claims hero ' +
            heroClaimed + ' HP, vectors moved ' + heroActual + ' [' + before[HERO_HP] + ' -> ' +
            after[HERO_HP] + '] events: ' + trail
        );
      }

      const slots = Math.max(before[ENEMIES], after[ENEMIES]);
      for (let slot = 0; slot < slots; slot++) {
        const hp = ENEMY_BASE + slot * 8 + 1;
        const said = claimed(events, 'enemy', slot);
        const moved = after[hp] - before[hp];
        if (said !== moved) {
          fail(
            'step ' + step + ': log claims enemy ' + slot + ' ' + said + ' HP, vectors moved ' +
              moved + ' [' + before[hp] + ' -> ' + after[hp] + '] events: ' + trail
          );
        }
      }

      const spent = events
        .filter((e) => e.kind === 'energy')
        .reduce((n, e) => n + e.spent, 0);
      if (spent > 0 && before[HERO_ENERGY] - after[HERO_ENERGY] < spent) {
        fail('step ' + step + ': log claims ' + spent + ' energy spent, the pool fell less');
      }
      checked++;
    }
    before = after;
  }
  if (checked < 5) fail('only ' + checked + ' steps checked; the invariant needs a real fight');
  if (played === 0) fail('no card was ever played; the invariant would never see a card\'s log');
  console.log('  battle log        ' + checked + ' steps, claimed == actual for hero and every enemy');
}


function text(lenOf, intoOf, index) {
  const n = lenOf(index);
  if (n <= 0) return "";
  const ptr = ex.rd_env_scratch_buf();
  intoOf(index, ptr);
  return new TextDecoder().decode(new Uint8Array(ex.memory.buffer, ptr, n).slice());
}
const io = {
  heroName: () => "hero",
  cardName: (slot) => text(ex.rd_env_card_name_len, ex.rd_env_card_name_into, slot),
  enemyName: (slot) => text(ex.rd_env_enemy_name_len, ex.rd_env_enemy_name_into, slot),
  intentText: (slot) => text(ex.rd_env_intent_len, ex.rd_env_intent_into, slot),
};
function actions() {
  const out = [];
  for (let i = 0; i < ex.rd_env_action_count(); i++) {
    out.push({ index: i, kind: ex.rd_env_action_kind(i),
               arg0: ex.rd_env_action_arg(i, 0), arg1: ex.rd_env_action_arg(i, 1) });
  }
  return out;
}
const view = (aiming) => UI.describe(obs(), actions(), io, aiming);

/// The `io` the log wants: definition slot -> name, resolvable for cards currently in hand.
const logIo = () => ({
  cardNameOfDefinition: (definitionSlot) => {
    for (let slot = 0; slot < obs()[UI.H.HAND]; slot++) {
      if (obs()[UI.OFF_HAND + slot * 4 + 2] === definitionSlot) {
        return io.cardName(slot);
      }
    }
    return "";
  },
});

/// Every printed quantity must equal the observation's own cell, at `where` (for the message).
/// Callers put this after anything that changes what is on screen -- a constant that looks right
/// at one moment fails at the next.
function assertCellsMatchObservation(where) {
  const o = obs();
  const v = view();
  const eq = (got, want, what) => {
    if (got !== want) fail(`${where}: ${what} shows ${got}, the observation says ${want}`);
  };
  eq(v.hero.hp, o[UI.H.HP], "hero hp");
  eq(v.hero.hpMax, o[UI.H.HP_MAX], "hero max hp");
  eq(v.hero.energy, o[UI.H.ENERGY], "hero energy");
  eq(v.hero.energyMax, o[UI.H.ENERGY_MAX], "hero max energy");
  eq(v.hero.block, o[UI.H.BLOCK], "hero block");
  eq(v.hero.handCount, o[UI.H.HAND], "hero hand count");
  eq(v.hero.piles.draw, o[UI.OFF_PILES], "draw pile count");
  eq(v.hero.piles.discard, o[UI.OFF_PILES + 2], "discard pile count");
  eq(v.hero.piles.exhaust, o[UI.OFF_PILES + 3], "exhaust pile count");
  eq(v.status.round, o[UI.H.ROUND], "round");
  eq(v.status.turn, o[UI.H.TURN], "turn");
  eq(v.status.phase, o[UI.H.PHASE], "phase");
  for (const e of v.enemies) {
    const base = UI.OFF_ENEMY + e.slot * 8;
    eq(e.alive, o[base] === 1, `enemy ${e.slot} alive`);
    eq(e.hp, o[base + 1], `enemy ${e.slot} hp`);
    eq(e.hpMax, o[base + 2], `enemy ${e.slot} max hp`);
    eq(e.block, o[base + 3], `enemy ${e.slot} block`);
    eq(e.intentKind, o[base + 5], `enemy ${e.slot} intent kind`);
    eq(e.intentDamage, o[base + 6] >= 0 ? o[base + 6] : null, `enemy ${e.slot} intent damage`);
    eq(e.statusCount, o[base + 7], `enemy ${e.slot} status count`);
  }
  return v;
}

if (ex.rd_env_reset() !== 0) fail("rd_env_reset() != 0");

// ---------------------------------------------------------------------------------------------
// 1. A fresh fight: the page must show the hero and the enemies from the observation, and the
//    ONE action available is "end turn". Every expected number here is a fact about this content
//    (`enc_small_slimes` = acid_slime_m 28 + spike_slime_s 10), so a wrong cell cannot pass.
// ---------------------------------------------------------------------------------------------
{
  const before = assertCellsMatchObservation("fresh fight");
  const hero = before.hero;
  if (hero.hp !== 80 || hero.hpMax !== 80) fail(`fresh hero shows ${hero.hp}/${hero.hpMax}, expected 80/80`);
  // NOTE: at full health `hp === hpMax`, so **this** assertion cannot tell the two cells apart --
  // reading the wrong one still prints 80/80. The discriminating checks are the ones after damage
  // lands (hero below, and the struck enemy below); they are why this test can fail at all.
  if (hero.energy !== 3 || hero.energyMax !== 3) fail(`energy shows ${hero.energy}/${hero.energyMax}`);
  if (hero.block !== 0) fail(`block shows ${hero.block}`);
  // Turn 1 is already under way at combat start (StS behaviour; see the note in smoke.mjs).
  if (hero.handCount !== 5) fail(`hand shows ${hero.handCount} cards at combat start, expected 5`);
  if (before.hand.length !== 5) fail(`hand list has ${before.hand.length} entries, expected 5`);
  if (hero.statuses.length !== 0) fail("hero shows statuses it does not have");

  if (before.enemies.length !== 2) fail(`enemies list has ${before.enemies.length} entries, expected 2`);
  const [slime, spike] = before.enemies;
  if (slime.name !== "acid_slime_m" || slime.hp !== 28 || slime.hpMax !== 28) {
    fail(`enemy 0 shows ${slime.name} ${slime.hp}/${slime.hpMax}, expected acid_slime_m 28/28`);
  }
  if (spike.name !== "spike_slime_s" || spike.hp !== 10) {
    fail(`enemy 1 shows ${spike.name} ${spike.hp}, expected spike_slime_s 10`);
  }
  if (!slime.alive || !spike.alive) fail("a fresh enemy is marked not alive");
  // The intent column is the content's own answer, and both are attacks with a printed number.
  for (const e of before.enemies) {
    if (e.intentLabel !== "Attack") fail(`${e.name} intent label is ${e.intentLabel}, expected Attack`);
    if (e.intentDamage === null || e.intentDamage <= 0) fail(`${e.name} intent damage is ${e.intentDamage}`);
    if (e.intentText === "—") fail(`${e.name} has no intent text`);
  }
  // The one action on a fresh fight is end turn (`rd-wasm`'s own rule), and the page must show it
  // as available -- a page that greys the button out would never start a game.
  if (!before.endTurn.available) fail("end turn is not offered on a fresh fight");
  // The index is whatever the action table says -- it leads with play actions now that turn 1 has
  // begun, so pinning it to 0 would pin the old empty-hand start state.
  if (before.endTurn.actionIndex < 0) fail(`end turn has no action index (${before.endTurn.actionIndex})`);
  if (before.status.done) fail("a fresh fight is already over");
  if (before.status.resultName !== "Ongoing") fail(`result shows ${before.status.resultName}`);
}

// ---------------------------------------------------------------------------------------------
// 2. End the turn: the hand must appear, and **the page's preview must equal the damage that
//    actually lands**. This is the one assertion that ties the rendered numbers to the engine.
// ---------------------------------------------------------------------------------------------
let previewed;
{
  const before = view();
  previewed = before.enemies.reduce((sum, e) => sum + (e.intentDamage || 0), 0);
  const hpBefore = before.hero.hp;
  if (ex.rd_env_step(before.endTurn.actionIndex) !== 0) fail("end-turn step rejected");

  const after = assertCellsMatchObservation("after the first end turn");
  const lost = hpBefore - after.hero.hp;
  if (after.hero.hp >= hpBefore) fail("ending the turn dealt the hero no damage at all");
  if (previewed !== lost) {
    fail(`the page previewed ${previewed} damage but the hero lost ${lost} -- the intent column lies`);
  }
  if (!(after.hero.hp < after.hero.hpMax)) {
    fail(`hero shows ${after.hero.hp}/${after.hero.hpMax} after taking ${lost} damage -- ` +
         `the current-health cell is reading the maximum`);
  }
  if (after.hero.hpMax !== 80) fail(`hero max health moved to ${after.hero.hpMax} when current health did`);
  if (after.hero.handCount !== 5) fail(`hand shows ${after.hero.handCount}, expected 5`);
  if (after.hand.length !== 5) fail(`hand list has ${after.hand.length} entries, expected 5`);

  // Every hand row: a real cost, a name that is not a placeholder, and a playability flag that
  // agrees with the action table (this is the ABI's affordability gate showing through).
  for (const card of after.hand) {
    if (card.cost < 0 || card.cost > 3) fail(`card ${card.slot} shows cost ${card.cost}`);
    if (!card.name || card.name.startsWith("def#")) {
      fail(`card ${card.slot} has no name (shows "${card.name}") although the module can name it`);
    }
    if (card.playable && card.targetSlots.length === 0) {
      fail(`card ${card.slot} is playable but names no action`);
    }
    if (card.affordable !== (card.cost <= after.hero.energy)) {
      fail(`card ${card.slot} affordability disagrees with the energy shown`);
    }
  }
  if (!after.hand.some((card) => card.playable)) fail("no card in the opening hand is playable");
}

// ---------------------------------------------------------------------------------------------
// 3. Target selection: a playable card with two live enemies must offer both slots and must NOT
//    take the fast path, because "always aim at the first enemy" was a real bug here.
// ---------------------------------------------------------------------------------------------
{
  const before = view();
  // An **attack**, not merely any two-target card: `defend` also comes back with one action per
  // live enemy slot (the ABI over-specifies the target and a non-targeted program ignores it),
  // so picking "the first two-target card" picks a card that deals no damage and the assertions
  // below would be about nothing. Measured, not assumed: that is exactly what the first version
  // of this test did.
  const multi = before.hand.find(
    (card) => card.playable && card.targetSlots.length === 2 && /strike|bash/.test(card.name));
  if (!multi) fail("no attack offers two targets while both enemies are alive");
  if (multi.directActionIndex !== -1) {
    fail(`card ${multi.slot} has two targets but would be played directly (index ${multi.directActionIndex})`);
  }
  // Strike it, then require current HP to move and maximum HP not to. This is the enemy half of
  // the "current vs max" pair; the fresh state (28/28) cannot distinguish them either.
  const victim = before.enemies.find((e) => e.alive && e.hp > 0);
  const itsSlot = victim.slot;
  const itsMax = victim.hpMax;
  const itsHp = victim.hp;
  if (!multi.targetSlots.includes(itsSlot)) fail("a playable card cannot reach a live enemy");
  const hitAction = ex.rd_env_action_count() && (() => {
    // Find the concrete action for (that card, that enemy) rather than assuming an index.
    for (let i = 0; i < ex.rd_env_action_count(); i++) {
      if (ex.rd_env_action_kind(i) === 0 &&
          ex.rd_env_action_arg(i, 0) === multi.slot &&
          ex.rd_env_action_arg(i, 1) === itsSlot) return i;
    }
    return -1;
  })();
  if (hitAction < 0) fail("no action names that (card, enemy) pair");
  if (ex.rd_env_step(hitAction) !== 0) fail("playing the card was rejected");
  {
    const hit = view();
    const struck = hit.enemies.find((e) => e.slot === itsSlot);
    if (struck.hp >= itsHp) fail(`the struck enemy still shows ${struck.hp} HP, was ${itsHp}`);
    if (struck.hpMax !== itsMax) fail(`the struck enemy's max HP moved to ${struck.hpMax}`);
    if (struck.hp === struck.hpMax) fail("the struck enemy shows current == max again");
  }

  const armed = view({ hand: multi.slot });
  const showing = armed.hand.find((card) => card.slot === multi.slot);
  if (!showing.armed) fail("the armed card is not marked as armed");
  if (showing.note !== "选一个敌人") fail(`an armed card's note is "${showing.note}"`);
  if (!showing.note.includes("选一个敌人")) fail("armed note lost");
}

// ---------------------------------------------------------------------------------------------
// 3b. The enemy status-count cell. The page prints `obs[base+7]` (ALL statuses on the combatant);
//     it must not print `statuses.length`, which counts only the five tracked axes. A constant 0
//     here passed every other assertion in this file -- measured, not feared: mutation M7 below
//     was green until this block existed.
{
  const o = obs();
  const current = view();
  let checked = 0;
  for (const e of current.enemies) {
    const raw = o[UI.OFF_ENEMY + e.slot * 8 + 7];
    if (e.statusCount !== raw) {
      fail(`enemy ${e.slot} status count shows ${e.statusCount}, the observation says ${raw}`);
    }
    if (e.statuses.length > e.statusCount) {
      fail(`enemy ${e.slot} lists ${e.statuses.length} statuses but the cell says ${e.statusCount}`);
    }
    for (const listed of e.statuses) {
      const axis = UI.STATUS_AXES.indexOf(listed.label);
      const cell = o[UI.OFF_ENEMY_STATUS + e.slot * 5 + axis];
      if (axis < 0 || cell !== listed.stacks) {
        fail(`enemy ${e.slot} lists ${listed.label} ${listed.stacks}, the observation says ${cell}`);
      }
      if (listed.stacks === 0) fail(`enemy ${e.slot} lists ${listed.label} with 0 stacks`);
    }
    checked++;
  }
  if (checked === 0) fail("no enemy status cell was checked");
}

// 3c. And a case where the count is NOT zero: content's `bash` applies 2 Vulnerable, so playing it
//     must make the target's status cell non-zero and put `vuln` in the list. Without a non-zero
//     instance, "the cell equals the observation" could hold for a page that always prints 0.
//     The fight is deterministic (`rd_env_reset` uses a fixed seed), so the turn hunt below either
//     always finds bash or always does not -- it cannot be flaky.
{
  let bash = null;
  for (let guard = 0; guard < 20 && bash === null; guard++) {
    const current = view();
    bash = current.hand.find(
      (c) => c.playable && /bash/.test(c.name) && c.targetSlots.length > 0) || null;
    if (bash) break;
    if (!current.endTurn.available) break;
    if (ex.rd_env_step(current.endTurn.actionIndex) !== 0) fail("end-turn step rejected hunting for bash");
  }
  if (!bash) fail("bash never became playable -- cannot check that a status shows up");
  const targetSlot = bash.targetSlots[0];
  let action = -1;
  for (let i = 0; i < ex.rd_env_action_count(); i++) {
    if (ex.rd_env_action_kind(i) === 0 && ex.rd_env_action_arg(i, 0) === bash.slot &&
        ex.rd_env_action_arg(i, 1) === targetSlot) action = i;
  }
  if (action < 0) fail("no action names (bash, its target)");
  const energyBefore = view().hero.energy;
  if (ex.rd_env_step(action) !== 0) fail("playing bash was rejected");
  const after = assertCellsMatchObservation("after playing bash");
  if (bash.cost > 0) {
    if (!(after.hero.energy < after.hero.energyMax)) {
      fail(`energy shows ${after.hero.energy}/${after.hero.energyMax} after paying ${bash.cost} -- ` +
           `the energy cell is reading the maximum`);
    }
    if (after.hero.energy !== energyBefore - bash.cost) {
      fail(`energy went ${energyBefore} -> ${after.hero.energy} for a cost-${bash.cost} card`);
    }
  }
  const struck = after.enemies.find((e) => e.slot === targetSlot);
  const rawCell = obs()[UI.OFF_ENEMY + targetSlot * 8 + 7];
  if (rawCell < 1) fail("bash applied no status to its target at all");
  if (struck.statusCount !== rawCell) {
    fail(`after bash the status cell shows ${struck.statusCount}, the observation says ${rawCell}`);
  }
  if (!struck.statuses.some((s) => s.label === "vuln" && s.stacks > 0)) {
    fail("vulnerable is missing from the target's status list after bash");
  }
}

// 4. A rule that must not drift: the describers never invent a number. Every quantity they print
//    is either a cell of the observation or a null. Checked on the hand, where the risk is a
//    placeholder cost or a fabricated target slot.
// ---------------------------------------------------------------------------------------------
{
  const o = obs();
  const current = view();
  const seen = new Set();
  for (const card of current.hand) {
    const base = UI.OFF_HAND + card.slot * 4;
    if (card.cost !== o[base + 1]) fail(`card ${card.slot} cost is not the observation's cell`);
    if (card.definitionSlot !== o[base + 2]) fail(`card ${card.slot} definition slot is not the cell`);
    for (const slot of card.targetSlots) {
      if (slot < 0 || slot >= UI.MAX_ENEMY_SLOTS) fail(`card ${card.slot} names target slot ${slot}`);
      if (!current.enemies[slot] || !current.enemies[slot].alive) {
        fail(`card ${card.slot} names target slot ${slot}, which is not a live enemy`);
      }
    }
    seen.add(card.cost);
  }
  if (seen.size === 0) fail("no hand card was checked at all");
}

// 5. `status.done` is derived from the observation; the ABI also exposes `rd_env_done()`. They
//    must agree at every point of a fight, or the page and the rest of the world disagree about
//    whether it is over.
{
  let steps = 0;
  for (; steps < 200; steps++) {
    const derived = UI.describeStatus(obs()).done;
    const asked = ex.rd_env_done() === 1;
    if (derived !== asked) fail(`step ${steps}: observation says done=${derived}, rd_env_done()=${asked}`);
    if (asked) break;
    const current = view();
    const next = current.endTurn.available
      ? current.endTurn.actionIndex
      : (current.hand.find((c) => c.playable) || {}).directActionIndex;
    const anyPlay = (() => {
      for (let i = 0; i < ex.rd_env_action_count(); i++) if (ex.rd_env_action_kind(i) === 0) return i;
      return -1;
    })();
    const choice = anyPlay >= 0 ? anyPlay : next;
    if (choice === undefined || choice < 0) fail(`no legal action at step ${steps}`);
    if (ex.rd_env_step(choice) !== 0) fail(`step ${steps} rejected`);
  }
  const finalDerived = UI.describeStatus(obs()).done;
  if (!finalDerived) fail(`the fight did not end within 200 steps (stopped at ${steps})`);
  const end = assertCellsMatchObservation("at the end of the fight");
  if (end.status.resultName !== "Victory") {
    fail(`the fight ended as ${end.status.resultName}, expected Victory`);
  }
  if (end.enemies.some((e) => e.alive)) {
    fail("the fight is won but an enemy is still marked alive");
  }
  if (end.enemies.some((e) => e.hp > 0)) fail("a downed enemy still shows positive HP");
}

// ---------------------------------------------------------------------------------------------
// 6. The step diff -- "what just happened", which is what the animation and the log are built on.
//    Every assertion here is against the real fight, so a diff that reports a made-up number fails.
// ---------------------------------------------------------------------------------------------
{
  const before = obs().slice();
  // A refused step changes nothing, so it must produce no events: an animation for nothing is
  // exactly the kind of lie this layer exists to prevent.
  const refused = UI.diffObservations(before, before, false);
  if (refused.events.length !== 0) fail(`a no-op diff produced ${refused.events.length} events`);
  if (UI.logLines(refused, logIo()).length !== 0) fail("a no-op diff produced log lines");
  if (UI.animationPlan(refused, view()).length !== 0) {
    fail("a no-op diff produced an animation plan");
  }
}

// Everything above has already played this fight to its end, so the diff blocks below start from a
// fresh one. Stated explicitly because "the state is whatever the previous block left behind" is
// exactly how a test ends up asserting something it did not mean to.
if (ex.rd_env_reset() !== 0) fail("reset before the diff blocks failed");

{
  // The end-turn step that follows the reset: the hero is hit for exactly the previewed damage.
  const preview = view().enemies.reduce((sum, e) => sum + (e.intentDamage || 0), 0);
  const before = obs().slice();
  const hpBefore = before[UI.H.HP];
  if (ex.rd_env_step(view().endTurn.actionIndex) !== 0) fail("end-turn step rejected");
  const diff = UI.diffObservations(before, obs(), true);

  if (diff.hero.hpLost !== preview) {
    fail(`the diff says the hero lost ${diff.hero.hpLost}, the intents previewed ${preview}`);
  }
  const hits = diff.hits.filter((h) => h.side === "hero");
  if (hits.length !== 1) fail(`${hits.length} hero damage events, expected one`);
  if (hits[0].amount !== preview) fail(`the hero damage event says ${hits[0].amount}`);
  // Block is *cleared* at the end of a turn, and that must not be reported as damage absorbed --
  // the two are indistinguishable from the vectors alone, which is why the diff needs to know
  // which kind of step it is looking at.
  if (hits[0].blocked !== 0) fail(`an end-turn step reported ${hits[0].blocked} blocked`);
  // `drawn` used to be pinned to a literal 5, which was only true while the hand started empty
  // (0 -> 5 = five new slots). Turn 1 now begins at combat start, so the hand is full **before** the
  // end-turn too and the diff can only see the slots that actually changed -- the identity of the
  // cards, not their count. The honest check is that the diff's number is the one the two vectors
  // imply: `hand_after = hand_before + drawn - left`.
  const handAfter = obs()[UI.H.HAND];
  if (handAfter !== 5) fail(`after an end-turn the hand is ${handAfter}, expected 5`);
  const left = (diff.events.find((e) => e.kind === "leftHand") || { count: 0 }).count;
  const implied = Math.max(0, handAfter - before[UI.H.HAND] + left);
  if (diff.drawn !== implied) {
    fail(`the diff says ${diff.drawn} cards were drawn; the vectors imply ${implied}`);
  }
  if (diff.hero.hpLost + hpBefore !== before[UI.H.HP] + preview) {
    fail("the damage does not add up");
  }
  const lines = UI.logLines(diff, logIo());
  if (!lines.some((l) => l.includes("英雄 −" + preview))) {
    fail(`no damage line in ${JSON.stringify(lines)}`);
  }
  // The line names the count the diff saw, not a literal: with a full hand before the end-turn the
  // diff can only report the slots that changed (see the note on `drawn` above).
  if (!lines.some((l) => l.includes("抽 " + diff.drawn + " 张"))) {
    fail(`no draw line in ${JSON.stringify(lines)}`);
  }
  const plan = UI.animationPlan(diff, view());
  if (!plan.some((p) => p.effect === "float" && p.at === "hero" && p.text === `-${preview}`)) {
    fail(`no damage float in ${JSON.stringify(plan)}`);
  }
  if (!plan.some((p) => p.effect === "shake" && p.at === "hero")) fail("no shake for the hero hit");
}

{
  // Playing an attack: the enemy loses exactly the damage, and the energy falls by the cost.
  const current = view();
  const attack = current.hand.find(
    (c) => c.playable && c.targetSlots.length > 0 && /strike|bash/.test(c.name));
  if (!attack) fail("no attack in hand to diff");
  const targetSlot = attack.targetSlots[0];
  let action = -1;
  for (let i = 0; i < ex.rd_env_action_count(); i++) {
    if (ex.rd_env_action_kind(i) === 0 && ex.rd_env_action_arg(i, 0) === attack.slot &&
        ex.rd_env_action_arg(i, 1) === targetSlot) action = i;
  }
  if (action < 0) fail("no action for the attack");
  const before = obs().slice();
  const hpBefore = before[UI.OFF_ENEMY + targetSlot * 8 + 1];
  if (ex.rd_env_step(action) !== 0) fail("playing the attack was rejected");
  const diff = UI.diffObservations(before, obs(), false);

  const hit = diff.hits.find((h) => h.side === "enemy" && h.slot === targetSlot);
  if (!hit) fail(`no enemy damage event in ${JSON.stringify(diff.hits)}`);
  if (hit.amount <= 0) fail("the enemy took no damage");
  if (hpBefore - hit.amount !== obs()[UI.OFF_ENEMY + targetSlot * 8 + 1]) {
    fail("the reported damage does not match the health cell");
  }
  if (diff.hero.energySpent !== attack.cost) {
    fail(`the diff says ${diff.hero.energySpent} energy was spent, the card costs ${attack.cost}`);
  }
  if (diff.leftHand.length !== 1) fail(`${diff.leftHand.length} cards left the hand, expected 1`);
  // The reading order: the card leaves, then the cost, then the damage -- not the order the vector
  // happens to be walked in.
  const lines = UI.logLines(diff, logIo());

  if (!/打出 .*→ .*耗 \d+ 能量.*敌人 \d+ −\d+/.test(lines.join(" "))) {
    fail(`expected a leave/cost/damage trio, got ${JSON.stringify(lines)}`);
  }
  {
    const one = lines.join(" ");
    const leave = one.indexOf("打出 ");
    const cost = one.indexOf("耗 ");
    const hit = one.indexOf("敌人 0 −");
    if (!(leave >= 0 && cost > leave && hit > cost)) {
      fail(`expected leave < cost < damage inside one line, got ${JSON.stringify(lines)}`);
    }
  }
  const plan = UI.animationPlan(diff, view());
  if (!plan.some((p) => p.effect === "float" && p.at === `enemy:${targetSlot}`)) {
    fail("no float on the struck enemy");
  }
}

{
  // A card that grants Block: the diff reports the gain, and the *end of that turn* reports the
  // clear rather than absorbed damage. This is the one case the observation cannot tell apart, so
  // it is the one worth pinning.
  let guard = 0;
  let defend = null;
  while (guard++ < 12 && !defend) {
    const current = view();
    defend = current.hand.find((c) => c.playable && /defend/.test(c.name)) || null;
    if (defend || !current.endTurn.available) break;
    if (ex.rd_env_step(current.endTurn.actionIndex) !== 0) fail("end-turn step rejected");
  }
  if (!defend) fail("never drew a defend to check block handling");
  const before = obs().slice();
  let action = -1;
  for (let i = 0; i < ex.rd_env_action_count(); i++) {
    if (ex.rd_env_action_kind(i) === 0 && ex.rd_env_action_arg(i, 0) === defend.slot) action = i;
  }
  if (action < 0) fail("no action for defend");
  if (ex.rd_env_step(action) !== 0) fail("playing defend was rejected");
  const gain = UI.diffObservations(before, obs(), false);
  if (gain.hero.blockGained <= 0) fail("defend reported no block gained");
  if (gain.hero.absorbed !== 0) fail("a fresh block gain reported absorbed damage");

  const beforeEnd = obs().slice();
  const blockHeld = beforeEnd[UI.H.BLOCK];
  if (!(blockHeld > 0)) fail(`expected to be holding block, holding ${blockHeld}`);
  const endAction = view().endTurn;
  if (!endAction.available) fail("cannot end the turn to check the block clear");
  if (ex.rd_env_step(endAction.actionIndex) !== 0) fail("end-turn step rejected");
  const cleared = UI.diffObservations(beforeEnd, obs(), true);
  if (cleared.hero.blockCleared !== blockHeld) {
    fail(`the end-turn step says ${cleared.hero.blockCleared} block cleared, held ${blockHeld}`);
  }
  if (cleared.hero.absorbed !== 0) fail("the end-turn clear was reported as absorbed damage");
}

{
  // Slide the fight to its end and check the two terminal events: the death of an enemy, and the
  // result. A diff that never reports `down` would animate a corpse.
  let seenDown = false;
  let seenResult = false;
  let guard = 0;
  while (guard++ < 400 && ex.rd_env_done() === 0) {
    const before = obs().slice();
    let action = -1;
    for (let i = 0; i < ex.rd_env_action_count(); i++) {
      if (ex.rd_env_action_kind(i) === 0) { action = i; break; }
    }
    if (action < 0) action = view().endTurn.actionIndex;
    if (action < 0) break;
    const wasEndTurn = ex.rd_env_action_kind(action) === 1;
    if (ex.rd_env_step(action) !== 0) fail(`step ${guard} rejected`);
    const diff = UI.diffObservations(before, obs(), wasEndTurn);
    if (diff.deaths.length) seenDown = true;
    if (diff.events.some((e) => e.kind === "result")) seenResult = true;
  }
  if (ex.rd_env_done() !== 1) fail("the fight did not finish");
  if (!seenDown) fail("no enemy death was ever reported by the diff");
  if (!seenResult) fail("the end of the fight produced no result event");
}

// ---------------------------------------------------------------------------------------------
// 7. Dropping a card on a target. The pointer plumbing is browser-only; the *decision* is here.
// ---------------------------------------------------------------------------------------------
// The block above played the fight to its end; a hand to drop cards from needs a fresh one, and
// this time the hand has to exist, so the reset is followed by one end-turn (which draws).
if (ex.rd_env_reset() !== 0) fail("reset before the drop block failed");
if (ex.rd_env_step(view().endTurn.actionIndex) !== 0) fail("the opening end-turn was rejected");

{
  const current = view();
  const options = UI.playOptions(actions());

  // A card that cannot be played accepts no drop at all.
  const dead = current.hand.find((card) => !card.playable);
  if (dead) {
    if (UI.actionFor(options, dead.slot, 0) !== -1) fail("an unplayable card accepted a drop");
    if (UI.actionFor(options, dead.slot, -1) !== -1) fail("an unplayable card accepted a drop in space");
  }

  // A two-target attack: the drop must name the enemy, and dropping on nothing must do nothing.
  const aimed = current.hand.find((card) => card.playable && card.targetSlots.length === 2);
  if (!aimed) fail("no two-target card to test dropping with");
  const [first, second] = aimed.targetSlots;
  const a = UI.actionFor(options, aimed.slot, first);
  const b = UI.actionFor(options, aimed.slot, second);
  if (a < 0 || b < 0) fail("a legal drop on a live enemy was refused");
  if (a === b) fail("dropping on two different enemies resolved to the same action");
  if (UI.actionFor(options, aimed.slot, -1) !== -1) {
    fail("dropping a two-target card on empty space picked a target anyway");
  }
  if (UI.actionFor(options, aimed.slot, 99) !== -1) fail("a drop on a nonexistent slot was accepted");
  // And the actions must be real: they index the action table, and both play the same card.
  const table = actions();
  if (table[a].kind !== UI.ACTION_PLAY || table[b].kind !== UI.ACTION_PLAY) {
    fail("a resolved drop is not a play action");
  }
  if (table[a].arg0 !== aimed.slot || table[b].arg0 !== aimed.slot) {
    fail("a resolved drop plays the wrong hand slot");
  }
  if (table[a].arg1 !== first || table[b].arg1 !== second) {
    fail("a resolved drop sends the wrong target");
  }

  // A single-option card ignores where it was dropped.
  const single = current.hand.find(
    (card) => card.playable && card.targetSlots.length === 1 && card.directActionIndex >= 0);
  if (single) {
    const anywhere = [sameSlot(), 0, -1, 99];
    for (const spot of anywhere) {
      if (UI.actionFor(options, single.slot, spot) !== single.directActionIndex) {
        fail(`a single-option card did not resolve for a drop at ${spot}`);
      }
    }
  }

  // `dropSlots` says which enemies light up: the reachable ones, and none for a single-option card.
  const lit = UI.dropSlots(options, aimed.slot);
  if (lit.length !== aimed.targetSlots.length) fail("dropSlots disagrees with targetSlots");
  if (!lit.every((slot) => aimed.targetSlots.includes(slot))) fail("dropSlots invented a slot");
  if (UI.dropSlots(options, aimed.slot).some((slot) => slot < 0)) {
    fail("dropSlots offered a negative slot as a drop target");
  }

  function sameSlot() { return aimed.slot; }
}

// ---------------------------------------------------------------------------------------------
// 8. Sound: which cues a step asks for, as ids. No files, and no calls from the pure layer.
// ---------------------------------------------------------------------------------------------
{
  const before = obs().slice();
  const silent = UI.soundPlan(UI.diffObservations(before, before, false));
  if (silent.length !== 0) fail(`a no-op step asked for ${silent.length} sounds`);

  if (ex.rd_env_reset() !== 0) fail("reset before the sound block failed");
  const preview = view().enemies.reduce((sum, e) => sum + (e.intentDamage || 0), 0);
  const snap = obs().slice();
  if (ex.rd_env_step(view().endTurn.actionIndex) !== 0) fail("end-turn step rejected");
  const diff = UI.diffObservations(snap, obs(), true);
  const plan = UI.soundPlan(diff);
  if (preview > 0 && !plan.includes("hit-hero")) fail(`no hero hit cue in ${JSON.stringify(plan)}`);
  if (!plan.includes("draw")) fail(`no draw cue in ${JSON.stringify(plan)}`);
  if (!plan.includes("turn")) fail(`no turn cue in ${JSON.stringify(plan)}`);

  // A finished fight asks for exactly one sound: the end of the fight is not a pile-up of hits.
  const result = UI.soundPlan({ result: 1, events: [{ kind: "result" }], hits: [{ side: "enemy" }] });
  if (result.length !== 1 || result[0] !== "victory") {
    fail(`the end of a fight asked for ${JSON.stringify(result)}`);
  }
  const defeat = UI.soundPlan({ result: 2, events: [{ kind: "result" }], hits: [] });
  if (defeat[0] !== "defeat") fail("a defeat asked for the wrong cue");
}

console.log("UI_RENDER PASS");
console.log(`  describe()        ${view().hand.length} hand cells, ${view().enemies.length} enemies, ` +
            `${UI.STATUS_AXES.length} status axes`);
console.log(`  preview vs real   ${previewed} damage previewed, and the hero lost exactly that`);
console.log(`  target picking    a two-target card is not played directly (index -1)`);
console.log(`  current vs max    distinguished on the hero after damage and on a struck enemy`);
console.log(`  enemy statuses    count cell == obs[base+7], and bash makes it non-zero`);
// ---------------------------------------------------------------------------------------------
// §345: display names -- `prettifyId` / `displayName` / the replacement table.
//
// 这一层是**纯函数**，所以它能在 Node 里被钉住：内核给 id，屏幕上的名字由这里决定
// （规避版权等用途正是靠那张表）。三条：美化规则、优先级、替换表真的能覆盖内核名。
// ---------------------------------------------------------------------------------------------
{
  const cases = [
    ["entropic_brew", "Entropic Brew"],
    ["acid_slime_m", "Acid Slime M"],
    ["defend+", "Defend+"],
    ["standard.constricted", "Constricted"],
    ["slime_boss", "Slime Boss"],
    ["", ""],
    [null, ""],
  ];
  for (const [input, want] of cases) {
    const got = UI.prettifyId(input);
    if (got !== want) fail(`prettifyId(${JSON.stringify(input)}) = ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
  }

  // 优先级：替换表 > 内核名 > 美化 id。
  const plain = UI.displayName("entropic_brew", "");
  if (plain !== "Entropic Brew") fail(`displayName without a kernel name: ${plain}`);
  const withKernel = UI.displayName("entropic_brew", "Entropic Brew (content)");
  if (withKernel !== "Entropic Brew (content)") {
    fail(`the kernel/content name must win over the prettifier: ${withKernel}`);
  }
  // ★ 替换表必须能**覆盖**内核名 —— 否则"屏幕上的名字与内核不同"这件事做不到。
  UI.NAMES["slime_boss"] = "胶质巨像";
  try {
    const replaced = UI.displayName("slime_boss", "Slime Boss");
    if (replaced !== "胶质巨像") {
      fail(`the replacement table must override the kernel name, got ${replaced}`);
    }
  } finally {
    delete UI.NAMES["slime_boss"];
  }
  // 空 id 不编名字（`""` 是"没有"，不是"未命名"）。
  if (UI.displayName("", "Some Name") !== "Some Name") fail("an empty id must fall through");
  if (UI.displayName("", "") !== "") fail("two empties must stay empty");
}

// ---------------------------------------------------------------------------------------------
// §347: the scene table is executable -- `classifyScene` + one fixture per scene.
//
// 18 个场景各一份夹具，每个断言三件事：命中预期的那一个、**恰好命中一个**（覆盖层例外）、
// 以及 `SCENES` 的顺序被字面量钉住。少一个夹具 = 那个场景从来没被验证过。
// ---------------------------------------------------------------------------------------------
{
  const scene = (s) => P.classifyScene({ ...BASE, ...s });

  // 期望顺序：与 `ui-state-model.md` §1 的表格逐行对应（**顺序即语义**）。
  const ORDER = [
    "SC-00", "SC-03b", "SC-11a", "SC-11b", "SC-12b", "SC-12a",
    "SC-01", "SC-01b", "SC-09", "SC-10", "SC-04", "SC-08", "SC-07", "SC-05", "SC-06",
    "SC-03", "SC-02b", "SC-02",
  ];
  const got = P.SCENES.map((entry) => entry.id);
  if (JSON.stringify(got) !== JSON.stringify(ORDER)) {
    fail(`SCENES order drifted:\n  got  ${JSON.stringify(got)}\n  want ${JSON.stringify(ORDER)}`);
  }

  // 一份夹具每个场景。字段只写**这个场景需要**的那些（其余从 BASE 来）。
  const FIXTURES = [
    ["SC-00", { noRun: true, pending: -1 }],
    ["SC-03b", { inFight: true, kind: 1, actionCount: 1 }],
    ["SC-11a", { pending: 4, pickupPicks: 2, rewardCards: [{ slot: 0, id: "anger", title: "Anger", chip: "" }] }],
    ["SC-11b", { pending: 4, pickupAdd: 2, pickupOffer: [{ slot: 0, title: "Anger" }] }],
    ["SC-12b", { runOver: true, runOverWhy: "第 3 层战败" }],
    ["SC-12a", { cleared: true, kind: 7 }],
    ["SC-01", { pending: 6, offers: [{ name: "治疗", gain: 1, gainAmount: 25, cost: 5, costAmount: 0 }] }],
    ["SC-01b", { pending: 7, blessingNeeds: 2 }],
    ["SC-09", { pending: 8, eventNeeds: 1 }],
    ["SC-10", { pending: 9, eventOffer: [{ slot: 0, id: "anger", title: "Anger" }] }],
    ["SC-04", { pending: 4, rewardCards: [{ slot: 0, id: "anger", title: "Anger", chip: "" }] }],
    ["SC-08", { pending: 5, eventText: "一块石头", choices: [{ slot: 0, label: "拿", effect: 2, amount: 10 }] }],
    ["SC-07", { pending: 3, kind: 6 }],
    ["SC-05", { pending: 2, kind: 4, shopCards: [] }],
    ["SC-06", { pending: 1, kind: 3, campfire: 3, restHeal: 24 }],
    ["SC-03", { kind: 1, actionCount: 1 }],
    ["SC-02b", { kind: 3, actionCount: 0 }],
    ["SC-02", { kind: 4, actionCount: 2 }],
  ];

  const seen = new Set();
  for (const [want, overrides] of FIXTURES) {
    const snapshot = { ...BASE, ...overrides };
    const hit = P.classifyScene(snapshot);
    if (hit !== want) fail(`scene fixture ${want} classified as ${hit}`);
    seen.add(want);

    const matches = P.scenesMatching(snapshot);
    if (matches.length === 0) fail(`scene fixture ${want} matched nothing`);
    if (matches[0] !== want) fail(`scene fixture ${want}: first match is ${matches[0]}`);
    // 覆盖层按定义叠在别的屏上 ⇒ 与底屏共命中是**对的**；其余必须唯一。
    if (!P.isOverlay(want)) {
      if (matches.length !== 1) {
        fail(`scene fixture ${want} matched ${JSON.stringify(matches)} -- base scenes must be unique`);
      }
    } else if (matches.length < 2) {
      fail(`overlay ${want} must also match the screen underneath, got ${JSON.stringify(matches)}`);
    }
  }

  // 覆盖：`SCENES` 里每一个 id 都要有夹具（少一个 = 那个场景从没被验证过）。
  for (const id of ORDER) {
    if (!seen.has(id)) fail(`no fixture for scene ${id}`);
  }
  if (seen.size !== P.SCENES.length) {
    fail(`fixtures ${seen.size} != scenes ${P.SCENES.length}`);
  }

  // `describe()` 与分类器必须一致：18 个夹具都要画出一份**有内容**的面板描述
  // （除了"战斗/地图"那几屏 —— 它们由 `render()` / `renderMap()` 画，节点面板只是兜底）。
  for (const [want, overrides] of FIXTURES) {
    const described = P.describe({ ...BASE, ...overrides });
    if (!described || typeof described !== "object" || !Array.isArray(described.buttons)) {
      fail(`scene fixture ${want}: describe() did not return a panel description`);
    }
    if (want === "SC-02b" && !(described.buttons || []).some((b) => b.action.kind === "end_act")) {
      fail("SC-02b must offer `end_act`");
    }
    if (want === "SC-03" && !(described.buttons || []).some((b) => b.action.kind === "begin_fight")) {
      fail("SC-03 must offer `begin_fight`");
    }
  }
}

console.log(`  scene table       classifyScene: 18 fixtures, base scenes unique, overlays stack`);
console.log(`  display names     prettifyId rules; table > kernel name > prettified id`);
console.log(`  cell-for-cell     every printed quantity == its observation cell, at 5 moments`);
console.log(`  energy below max  checked after paying a cost (the only moment they differ)`);
console.log(`  downed enemies    none alive once the fight is won`);
console.log(`  done agreement    observation-derived == rd_env_done() at every step to the end`);
console.log(`  step diff          damage == the intents previewed; energy == the card cost`);
console.log(`  block vs clear     a block gain, then the end-of-turn clear (not "absorbed")`);
console.log(`  terminal events    an enemy death and the result are both reported`);
console.log(`  dropping a card   two targets => two actions; empty space => nothing`);
console.log(`  sound cues        no-op silent; a hit/draw/turn each ask for their own; one cue at the end`);
console.log(`  page wiring       one page: run + fight, deck/pile panels, node panels, drag`);
console.log(`  run <-> fight     started by rd_run_fight_begin, folded back by rd_run_fight_end`);
console.log("  ⚠️  no DOM: the markup layer is still only checked by eye in a browser.");
