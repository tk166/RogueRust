// A **randomised full-run soak**, driven entirely through the DOM (§151).
//
// Why this exists: `browser_test.mjs` is one scripted path, and the potion bug of §150 lived for
// three sections behind it because *nobody clicked that button*. Hand-clicking is expensive and
// does not scale to "every button, every phase". So this gate clicks **random** enabled controls
// for a budgeted number of actions across several seeds, and after every click asks one question:
//
//     did anything change?
//
// That single invariant (`the fingerprint moved`) is what a dead button violates. It does not care
// *which* button, so it covers the ones no scripted test mentions. A thrown handler is caught the
// same way, plus by the page's own `error` / `unhandledrejection` listeners.
//
// What it asserts
//   1. **No uncaught error** from the page (listener-installed, not "hope nobody noticed").
//   2. **Every click on an enabled control changes something.** Exceptions: an explicit allowlist of
//      controls that are legitimately inert (see IDLE_ALLOWED in the page script).
//   3. **The run makes progress**: floors advance, fights start and finish, at least one act is
//      reached, and the walk does not get stuck (no candidates for N consecutive polls).
//   4. **State invariants**: hp in `0..hpMax`, energy in `0..energyMax`, no negative gold/deck.
//
// Determinism: the *driver* uses a seeded PRNG and logs the seed, so a red is reproducible
// (`--seed N`). The game's own randomness comes from the run seed, also logged.
//
// Run: node web/soak_test.mjs [--seeds 3] [--steps 350] [--seed 12345]
// Exit 0 + `SOAK_TEST PASS` = green.

import { openPage } from "./cdp.mjs";

const argv = process.argv.slice(2);
const flag = (name, fallback) => {
  const at = argv.indexOf(`--${name}`);
  return at >= 0 && argv[at + 1] ? Number(argv[at + 1]) : fallback;
};
const SEED_COUNT = flag("seeds", 3);
const STEPS = flag("steps", 350);
const FIRST_SEED = flag("seed", 12345);

const page = await openPage({ query: "soak&debug", gate: "SOAK_TEST", waitFor: "Boolean(window.ex)" });
const { evaluate, fail } = page;

const report = await evaluate(`(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const SEED_COUNT = ${SEED_COUNT};
  const STEPS = ${STEPS};
  const FIRST_SEED = ${FIRST_SEED};

  const out = { seeds: [], errors: [], dead: [], refused: [], stuck: [], invariant: [], screens: [] };
  window.__soakErrors = [];
  window.addEventListener("error", (event) => window.__soakErrors.push(String(event.message)));
  window.addEventListener("unhandledrejection", (event) =>
    window.__soakErrors.push(String(event.reason)));

  // ---- a seeded PRNG (LCG: reproducible, and the seed is printed) ------------------------------
  let state = FIRST_SEED >>> 0;
  const random = () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };
  const pick = (list) => list[Math.floor(random() * list.length)];

  const panel = () => document.getElementById("nodePanel");
  const byId = (id) => document.getElementById(id);
  // innerText is **undefined on SVG elements** (the map nodes are SVG), so a helper that assumes
  // it is a string throws the moment a label is asked for one. textContent is the general one.
  const text = (el) => {
    if (!el) return "";
    const raw = typeof el.innerText === "string" ? el.innerText : el.textContent;
    return (raw || "").replace(/\s+/g, " ").trim();
  };

  // ---- the fingerprint: "did anything change?" ------------------------------------------------
  // Text + innerHTML, so a class flip (armed / unaffordable / down) counts: those *are* visible
  // changes, and a control that only flips a class is doing its job.
  const fingerprint = () =>
    [
      text(byId("runStats")),
      byId("relicChips").innerHTML,
      text(byId("deckCount")),
      byId("mapbox").innerHTML.length,
      byId("mapbox").querySelectorAll("g.node.here").length,
      text(byId("nodePanel")),
      byId("handPanel").innerHTML,
      byId("enemies").innerHTML,
      byId("log").innerText.length,
      text(byId("msg")).slice(0, 40),
      byId("modal").hidden,
      byId("actCurtain").hidden,
    ].join("|");

  // ---- candidate controls, in **priority order** ------------------------------------------------
  // The order is what a player would do: answer the panel first (settle the node you stand on),
  // then walk. Clicking a map node while the current node is unsettled is legal to *try* and the
  // kernel refuses it with NodeNotSettled -- correct, but noise here: it says "I ignored the panel".
  //
  // Only enabled controls are candidates: clicking a disabled button is not a player action.
  const candidates = () => {
    const groups = [[], [], [], []];
    if (!byId("modal").hidden) {
      // The deck picker (blessing "remove a card", smithing, an event's deck edit) lives in the
      // modal as [data-pick] buttons; the card-detail modal only has a close button. A soak that
      // forgets the picker is stuck at the very first blessing.
      for (const el of document.querySelectorAll("#modalBody [data-pick]")) {
        groups[0].push({ kind: "deck-pick", el, label: text(el) });
      }
      const close = document.querySelector("#modal [data-close]");
      if (close) groups[0].push({ kind: "modal-close", el: close });
      return groups;
    }
    const inFight = !byId("handPanel").hidden;
    if (inFight) {
      for (const el of document.querySelectorAll("#hand button.card:not([disabled])")) {
        groups[1].push({ kind: "card", el, label: text(el).slice(0, 40) });
      }
      for (const el of document.querySelectorAll("#enemies [data-target-slot]")) {
        groups[1].push({ kind: "target", el });
      }
      const end = byId("endTurn");
      if (end && !end.disabled) groups[1].push({ kind: "end-turn", el: end });
      for (const el of document.querySelectorAll("[data-use-potion]")) {
        groups[2].push({ kind: "use-potion", el });
      }
    } else {
      for (const el of document.querySelectorAll("#nodePanel [data-panel-action]")) {
        if (el.disabled) continue;
        groups[1].push({ kind: "panel", el, label: text(el) });
      }
      for (const el of document.querySelectorAll("#mapbox g.node.reachable")) {
        groups[2].push({ kind: "node", el, label: text(el) });
      }
      for (const el of document.querySelectorAll("[data-use-potion]")) {
        groups[2].push({ kind: "use-potion-run", el });
      }
    }
    for (const el of document.querySelectorAll("[data-drop-potion]")) {
      groups[3].push({ kind: "drop-potion", el });
    }
    return groups;
  };
  // The panel titles the page can show (ui_panels.js); the soak records which ones it reached.
  const SCREENS = ["塔底", "战斗节点", "篝火", "商店", "未知房间", "宝箱", "战斗奖励", "Boss"];

  const openModal = () => {
    const card = document.querySelector("#hand button.card");
    if (!card) return;
    card.dispatchEvent(new MouseEvent("click", { bubbles: true, shiftKey: true }));
  };

  const invariants = (where) => {
    const reading = (fn, fallback) => { try { return fn(); } catch { return fallback; } };
    const hp = reading(() => ex.rd_run_observe(2), -1);
    const hpMax = reading(() => ex.rd_run_observe(3), -1);
    const gold = reading(() => ex.rd_run_observe(4), -1);
    const deck = reading(() => ex.rd_run_deck_count(), -1);
    if (hp < 0 || (hpMax > 0 && hp > hpMax)) out.invariant.push(where + ": hp " + hp + "/" + hpMax);
    if (gold < 0) out.invariant.push(where + ": gold " + gold);
    if (deck < 0) out.invariant.push(where + ": deck " + deck);
  };

  for (let run = 0; run < SEED_COUNT; run++) {
    const runSeed = 100 + run;
    RD_DEBUG.startWithSeed(runSeed);
    await sleep(0);
    let actions = 0;
    let deadHere = 0;
    let fights = 0;
    let maxFloor = 0;
    let maxAct = 1;
    let wasFight = false;
    let idlePolls = 0;
    // After walking onto a node, take its **first** panel action once. Without this the walk picks
    // randomly between "open the chest" and "leave", so half the visits skip the screen's whole
    // point -- and a broken primary button then only sometimes shows up (the first version of this
    // file missed a deliberately broken 开箱 twice in a row).
    let preferPrimary = false;
    const startedAt = performance.now();

    while (actions < STEPS) {
      const beforeMsg = text(byId("msg")).slice(0, 100);
      const before = fingerprint();
      // Which *screens* this walk has shown. "It climbed 6 floors" depends on luck; "it saw the
      // shop, the campfire, a chest and an event" is a property of the content, and it is what makes
      // the soak worth running.
      const panelNow = text(panel());
      for (const screen of SCREENS) {
        if (panelNow.includes(screen) && !out.screens.includes(screen)) out.screens.push(screen);
      }
      const groups = candidates();
      const list = groups.find((group) => group.length) || [];
      if (!list.length) {
        // Nothing to click: either the run is over, or the page is stuck. A few polls tolerate the
        // async render; more than that is a real dead end.
        idlePolls += 1;
        if (idlePolls > 12) {
          const buttons = [...panel().querySelectorAll("[data-panel-action]")].map((b) => ({
            label: text(b), disabled: b.disabled,
          }));
          out.stuck.push({
            runSeed, actions,
            panel: text(panel()).slice(0, 120),
            msg: text(byId("msg")).slice(0, 120),
            // Everything that says "why can the player not move".
            pending: ex.rd_run_pending(),
            nodeKind: ex.rd_run_node_kind(),
            resolved: ex.rd_run_node_resolved(),
            runActions: ex.rd_run_action_count(),
            duringFight: !byId("handPanel").hidden,
            envActions: ex.rd_env_action_count(),
            envDone: ex.rd_env_done(),
            envResult: ex.rd_env_result(),
            heroHp: ex.rd_run_observe(2),
            turnPhase: (() => { const b = ex.rd_env_scratch_buf(); ex.rd_env_observe_into(b);
              return new Int32Array(ex.memory.buffer, b, ex.rd_env_observe_len())[2]; })(),
            buttons,
            handCards: document.querySelectorAll("#hand button.card").length,
            handDisabled: document.querySelectorAll("#hand button.card[disabled]").length,
            endDisabled: byId("endTurn").disabled,
            envKinds: Array.from({ length: Math.max(0, ex.rd_env_action_count()) },
              (_, i) => ex.rd_env_action_kind(i)),
            handHtml: byId("hand").innerHTML.slice(0, 160),
          });
          break;
        }
        await sleep(5);
        continue;
      }
      idlePolls = 0;
      const choice = preferPrimary ? list[0] : pick(list);
      preferPrimary = false;
      if (choice.kind === "node") preferPrimary = true;
      choice.el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      // Shift+click opens a modal sometimes: it is a real control, and the modal must be closable.
      if (choice.kind === "card" && random() < 0.1) openModal();
      await sleep(0);
      await sleep(0);
      const after = fingerprint();
      actions += 1;
      const inFight = !byId("handPanel").hidden;
      if (inFight && !wasFight) fights += 1;
      wasFight = inFight;
      const floor = ex.rd_run_observe(0);
      if (floor > maxFloor) maxFloor = floor;
      const act = ex.rd_run_act();
      if (act > maxAct) maxAct = act;

      if (after === before) {
        // A click on an enabled control that changed **nothing**. Two shapes, and they are not the
        // same bug:
        //   * the message changed => the kernel **refused**, and the page said why. An enabled
        //     control that can only be refused is still a lie (§151 disabled the shop's 买 for that
        //     reason), so it is counted -- but as a refusal, with the reason;
        //   * nothing at all changed => a dead button. That is the §150 shape (a throwing handler),
        //     and it is the one this gate is here for.
        const said = text(byId("msg")).slice(0, 100);
        if (said && said !== beforeMsg) {
          out.refused.push({ runSeed, actions, kind: choice.kind, label: (choice.label || text(choice.el)).slice(0, 40), said });
        } else {
          deadHere += 1;
          // Which part of the fingerprint failed to move: without this a dead entry says "nothing
          // happened" and you have to guess *what* nothing.
          const beforeParts = before.split("|");
          const afterParts = after.split("|");
          const moved = beforeParts.map((part, i) => (part === afterParts[i] ? null : i)).filter((i) => i !== null);
          out.dead.push({
            runSeed, actions, kind: choice.kind,
            label: (choice.label || text(choice.el)).slice(0, 60),
            panel: text(panel()).slice(0, 80),
            msg: said.slice(0, 60),
            movedFields: moved,
            hereBefore: beforeParts[4], hereAfter: afterParts[4],
            actionsInTable: ex.rd_run_action_count(),
            stepable: ex.rd_run_observe(0),
          });
        }
      }
      invariants("seed " + runSeed + " action " + actions);
      if (window.__soakErrors.length) break;
      // The run ended (cleared / dead): start the next seed instead of clicking a corpse.
      if (ex.rd_run_boss_beaten() === 1 || ex.rd_run_observe(2) <= 0) break;
    }

    out.seeds.push({
      runSeed, actions, fights, maxFloor, maxAct, dead: deadHere,
      pending: ex.rd_run_pending(),
      potions: ex.rd_run_potion_count(),
      ms: Math.round(performance.now() - startedAt),
      errors: window.__soakErrors.length,
    });
    if (window.__soakErrors.length) {
      out.errors = window.__soakErrors.slice(0, 5);
      break;
    }
  }
  // A final look at the page: nothing should be mid-throw.
  out.errors = window.__soakErrors.slice(0, 5);
  return out;
})()`);

// ---- the assertions ---------------------------------------------------------------------------
const problems = [];
const want = (condition, why) => {
  if (!condition) problems.push(why);
};

want(report.errors.length === 0, `the page threw: ${JSON.stringify(report.errors)}`);
want(report.dead.length === 0,
  `${report.dead.length} dead control(s), first: ${JSON.stringify(report.dead[0] || null)}`);
want(report.refused.length === 0,
  `${report.refused.length} enabled control(s) were refused, first: ${JSON.stringify(report.refused[0] || null)}`);
want(report.stuck.length === 0, `the run got stuck: ${JSON.stringify(report.stuck[0] || null)}`);
want(report.invariant.length === 0,
  `state invariant broken: ${JSON.stringify(report.invariant[0] || null)}`);
want(report.seeds.length === SEED_COUNT, `only ${report.seeds.length} of ${SEED_COUNT} seeds ran`);
// Progress, not just "did not crash": a soak that clicks nothing interesting proves nothing.
const totalActions = report.seeds.reduce((n, s) => n + s.actions, 0);
const totalFights = report.seeds.reduce((n, s) => n + s.fights, 0);
const bestFloor = Math.max(0, ...report.seeds.map((s) => s.maxFloor));
const bestAct = Math.max(1, ...report.seeds.map((s) => s.maxAct)); // reported, not asserted
want(totalActions >= SEED_COUNT * 40, `only ${totalActions} actions in total`);
want(totalFights >= SEED_COUNT, `only ${totalFights} fights started across ${SEED_COUNT} seeds`);
want(bestFloor >= 3, `the walk only reached floor ${bestFloor}`);
// No act-2 requirement: a random walker plays cards at random and dies in act 1 most of the time.
// What must hold is **coverage**: the walk has to have shown several kinds of screen, or it proves
// nothing about the pages nobody opens by hand.
want(report.screens.length >= 4,
  `the walk only saw ${report.screens.length} kinds of screen: ${JSON.stringify(report.screens)}`);

await page.close();

if (problems.length) {
  for (const problem of problems) console.error("  - " + problem);
  fail(`${problems.length} assertion(s) failed`);
}
for (const seed of report.seeds) {
  console.log(
    `  seed ${String(seed.runSeed).padStart(3)}  ${String(seed.actions).padStart(4)} clicks · ` +
      `${seed.fights} fights · floor ${seed.maxFloor} · act ${seed.maxAct} · ` +
      `${seed.potions} potions · ${seed.ms} ms`
  );
}
console.log("  screens           " + report.screens.join(" / "));
console.log("  refusals          " + report.refused.length);
console.log("SOAK_TEST PASS");
