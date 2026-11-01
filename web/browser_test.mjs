// A **real browser** regression, with no dependencies.
//
// Why not Playwright: `web/` is deliberately zero-build, and Playwright would pull a second copy of
// Chromium (~150 MB). Chrome is already installed, and Node 22 has a built-in `WebSocket`, so the
// whole driver is: a static server (node:http), a headless Chrome (CDP), and a script evaluated in
// the page. That is enough for what this file asserts -- **key text must appear**, no pixels.
//
// What it covers (the flows that kept breaking by hand):
//   * the tower blessing is offered and taking one settles the run;
//   * the map refuses an unreachable node **and says why**;
//   * a fight starts, a card is played, and the battle log names the card and its effect;
//   * the top bar shows `幕 N` and tracks the fight's health;
//   * an unaffordable card is marked `unaffordable` once the energy is gone;
//   * Shift+click opens the card detail.
//
// Run: node web/browser_test.mjs   (exit 0 and `BROWSER_TEST PASS` = green)

import { openPage } from "./cdp.mjs";

// ---- the browser (see cdp.mjs: static server + headless Chrome + CDP) -------------------------
// The query carries **debug** because the potion scenario (§150) pins a seed through RD_DEBUG.
const page = await openPage({
  query: "browser-test&debug",
  gate: "BROWSER_TEST",
  waitFor: 'Boolean(window.ex && document.querySelector("#nodePanel [data-panel-action]"))',
});
const { evaluate, fail } = page;
const report = await evaluate(`(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const panel = () => document.getElementById("nodePanel");
  const text = (el) => el.innerText.replace(/\\s+/g, " ").trim();
  const logLines = () => document.getElementById("log").innerText.split("\\n").filter((l) => l.trim());
  const out = {};
  // The observation comes through a buffer, not a getter (same idiom as index.html).
  const buf = ex.rd_env_scratch_buf();
  const cell = (index) => {
    ex.rd_env_observe_into(buf);
    return new Int32Array(ex.memory.buffer, buf, ex.rd_env_observe_len())[index];
  };

  // (a) the blessing is a choice, with a name rather than an id
  out.blessings = [...panel().querySelectorAll("[data-panel-action]")]
    .map((b) => text(b))
    .filter(Boolean);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  // a card blessing owes a pick; take it so the run can move
  if (ex.rd_run_pending() === 7) {
    const pick = panel().querySelector("[data-panel-action]");
    if (pick) { pick.click(); await sleep(0); }
    const card = document.querySelector("#modalBody [data-pick]");
    if (card) { card.click(); await sleep(0); }
  }
  out.afterBlessing = { pending: ex.rd_run_pending(), floor: ex.rd_run_observe(0) };

  // (b) an unreachable node: refuses and says why
  const unlit = [...document.querySelectorAll("#mapbox g.node:not(.reachable):not(.here)")][0];
  if (unlit) {
    unlit.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await sleep(0);
  }
  out.refusal = text(document.getElementById("msg"));

  // (c) walk into a fight and start it
  const lit = [...document.querySelectorAll("#mapbox g.node.reachable")];
  if (lit.length) {
    lit[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await sleep(0);
  }
  const fight = panel().querySelector("[data-panel-action]");
  if (fight) { fight.click(); await sleep(0); }
  out.fight = { inFight: !document.getElementById("handPanel").hidden, energy: cell(8) };

  // (d) Shift+click a card: the detail modal must name it and show its text
  const card = document.querySelector("#hand button.card");
  if (card) {
    card.dispatchEvent(new MouseEvent("click", { bubbles: true, shiftKey: true }));
    await sleep(0);
    out.card = {
      open: !document.getElementById("modal").hidden,
      title: document.getElementById("modalTitle").innerText.trim(),
      body: text(document.getElementById("modalBody")).slice(0, 60),
    };
    // Close it the way a **player** does (§151). The old line assigned hidden = true from the
    // driver, which is why nobody noticed that the modal had no way out at all.
    const closer = document.getElementById("modalClose");
    if (closer) closer.click();
    await sleep(0);
    out.card.closed = document.getElementById("modal").hidden;
  }

  // (e) play every affordable card, then look at the log and the top bar
  for (let i = 0; i < 6; i++) {
    const next = [...document.querySelectorAll("#hand button.card:not([disabled])")][0];
    if (!next) break;
    next.click();
    await sleep(0);
    const target = document.querySelector("#enemies [data-target-slot]");
    if (target) { target.click(); await sleep(0); }
  }
  out.log = logLines().slice(-3);
  out.topBar = text(document.getElementById("runStats"));
  out.energyAfter = cell(8);
  out.unaffordable = document.querySelectorAll("#hand button.card.unaffordable").length;

  // (f) **A potion must be usable from the belt** (§150). This is the scenario that was missing:
  // a handler that throws is a dead button, and nothing above clicked one. It found a real
  // regression -- renderTopBar had a local named act (ex.rd_run_act()), which shadowed the page's
  // act(call, label) helper, so the button threw TypeError: act is not a function.
  //
  // The seed is pinned because a potion drop is 40%: this checks the **wiring**, not the drop.
  // If a content change ever moves the drop, pick another seed with a comment.
  const POTION_SEED = 12;
  const finishFight = async () => {
    for (let step = 0; step < 80; step++) {
      const inFight = !document.getElementById("handPanel").hidden;
      if (!inFight) break;
      const next = document.querySelector("#hand button.card:not([disabled])");
      if (next) {
        next.click();
        await sleep(0);
        const target = document.querySelector("#enemies [data-target-slot]");
        if (target) { target.click(); await sleep(0); }
      } else {
        document.getElementById("endTurn").click();
        await sleep(0);
      }
    }
  };
  const walkIntoFight = async () => {
    for (let step = 0; step < 20; step++) {
      if (!document.getElementById("handPanel").hidden) return true;
      const lit = [...document.querySelectorAll("#mapbox g.node.reachable")];
      if (!lit.length) return false;
      lit[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await sleep(0);
      const first = panel().querySelector("[data-panel-action]");
      if (first) first.click();
      await sleep(0);
      if (document.getElementById("handPanel").hidden) {
        const leave = [...panel().querySelectorAll("[data-panel-action]")]
          .find((b) => b.innerText.includes("离开"));
        if (leave) { leave.click(); await sleep(0); }
      }
    }
    return !document.getElementById("handPanel").hidden;
  };

  window.RD_DEBUG.startWithSeed(POTION_SEED);
  await sleep(0);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  if (ex.rd_run_pending() === 7) {
    panel().querySelector("[data-panel-action]").click();
    await sleep(0);
    const pick = document.querySelector("#modalBody [data-pick]");
    if (pick) { pick.click(); await sleep(0); }
  }
  await walkIntoFight();
  await finishFight();
  out.potionBeltBefore = ex.rd_run_potion_count();
  if (ex.rd_run_pending() === 4) {
    const row = [...panel().querySelectorAll(".shop-item")].find((r) => r.innerText.includes("药水"));
    if (row) {
      const takeButton = row.querySelector("[data-panel-action]");
      if (takeButton) { takeButton.click(); await sleep(0); }
    }
    const skip = [...panel().querySelectorAll("[data-panel-action]")].pop();
    if (skip) { skip.click(); await sleep(0); }
  }
  out.potionInBelt = ex.rd_run_potion_count();
  out.potionBeltHtml = document.getElementById("relicChips").innerHTML;
  await walkIntoFight();
  out.potionFight = !document.getElementById("handPanel").hidden;
  out.potionHasUse = Boolean(document.querySelector("[data-use-potion]"));
  const useButton = document.querySelector("[data-use-potion]");
  if (useButton) {
    // Call the handler **directly** so a throw is visible here instead of vanishing into the
    // event dispatcher (that is exactly how the regression above stayed invisible).
    try {
      useButton.onclick();
      out.potionThrew = null;
    } catch (error) {
      out.potionThrew = String(error);
    }
    await sleep(0);
  }
  out.potionAfter = ex.rd_run_potion_count();
  out.potionBeltAfter = document.getElementById("relicChips").innerHTML;

  // (h) **§161.3: the card-choice picker.** Elixir and Gambler's Brew do not resolve when drunk --
  // they ask a question, and the kernel's action table is empty until it is answered. Every part of
  // that sentence is a separate way to be broken, and all of them are invisible without a browser.
  out.choiceSeed = 31;
  window.RD_DEBUG.startWithSeed(out.choiceSeed);
  await sleep(0);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  if (ex.rd_run_pending() === 7) {
    panel().querySelector("[data-panel-action]").click();
    await sleep(0);
    const pick = document.querySelector("#modalBody [data-pick]");
    if (pick) { pick.click(); await sleep(0); }
  }
  out.choiceFight = await walkIntoFight();
  out.choiceGranted = window.RD_DEBUG.givePotion("elixir");
  out.choiceBelt = ex.rd_run_potion_count();
  // The 用 button of the **last** belt slot, which is the Elixir we just put there.
  // No nested template literal here: the whole block is already inside one, and a second pair of
  // backticks ends it. (That exact trap has now been hit three times in this file -- FACT.md §2b.)
  const elixirButton =
    document.querySelector('[data-use-potion="' + (out.choiceBelt - 1) + '"]');
  out.choiceHasUse = Boolean(elixirButton);
  out.choiceModalBefore = document.getElementById("modal").hidden;
  if (elixirButton) {
    // Call the handler **directly**: a throw inside an event handler never reaches the caller
    // (dispatchEvent swallows it into window.onerror), which is exactly how §150 stayed invisible.
    try {
      elixirButton.onclick();
      out.choiceThrew = null;
    } catch (error) {
      out.choiceThrew = String(error);
    }
    await sleep(0);
  }
  out.choicePending = ex.rd_env_choice_pending();
  out.choiceKind = ex.rd_env_choice_kind();
  out.choiceModalOpen = !document.getElementById("modal").hidden;
  out.choiceTitle = text(document.getElementById("modalTitle"));
  out.choiceOptions = document.querySelectorAll("#modalBody [data-choice]").length;
  out.choiceEnvActions = ex.rd_env_action_count();
  // The modal must not be dismissable: an unanswered question with an empty action table is a
  // page with no way forward.
  document.getElementById("modalClose").click();
  await sleep(0);
  out.choiceStillOpen = !document.getElementById("modal").hidden;
  // Tick one option through the **DOM button**, then confirm through the DOM button.
  const exhaustBefore = ex.rd_env_pile_len(2);
  const first = document.querySelector("#modalBody [data-choice]");
  if (first) { first.click(); await sleep(0); }
  out.choiceTicked = first ? first.dataset.ticked : null;
  const choiceConfirm = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
  out.choiceHasConfirm = Boolean(choiceConfirm);
  if (choiceConfirm) {
    try {
      choiceConfirm.onclick();
      out.choiceConfirmThrew = null;
    } catch (error) {
      out.choiceConfirmThrew = String(error);
    }
    await sleep(0);
    await sleep(0);
  }
  out.choicePendingAfter = ex.rd_env_choice_pending();
  out.choiceExhausted = ex.rd_env_pile_len(2) - exhaustBefore;
  out.choiceEnvActionsAfter = ex.rd_env_action_count();

  // (i) **§161.4: the card comes back free, and the screen says so.**
  // Liquid Memories takes a card out of the discard pile into the hand and prices **that copy** at
  // zero. Three separate things have to agree: the picker is a mandatory one-pick question, the
  // observation's cost column reads 0 (that is what the player sees), and the kernel really charges
  // nothing. Plus one thing that must NOT happen: gracefully resolving without a pick.
  out.lmFight = !document.getElementById("handPanel").hidden;
  out.lmGranted = window.RD_DEBUG.givePotion("liquid_memories");
  // Make sure the discard pile is not empty: play whatever is affordable first, then drink.
  for (let guard = 0; guard < 8; guard++) {
    const next = document.querySelector("#hand button.card:not([disabled])");
    if (!next) break;
    next.click();
    await sleep(0);
    const target = document.querySelector("#enemies [data-target-slot]");
    if (target) { target.click(); await sleep(0); }
  }
  out.lmDiscards = ex.rd_env_pile_len(1);
  const lmButton = document.querySelector(
    '[data-use-potion="' + (ex.rd_run_potion_count() - 1) + '"]');
  out.lmHasUse = Boolean(lmButton);
  if (lmButton) {
    try { lmButton.onclick(); out.lmThrew = null; } catch (error) { out.lmThrew = String(error); }
    await sleep(0);
  }
  out.lmPending = ex.rd_env_choice_pending();
  out.lmKind = ex.rd_env_choice_kind();
  out.lmTitle = text(document.getElementById("modalTitle"));
  const lmConfirm = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
  out.lmConfirmDisabledEmpty = lmConfirm ? lmConfirm.disabled : null;
  // A mandatory choice: pressing confirm with nothing ticked must be refused **by the kernel**, so
  // the question survives. (The button is disabled too -- this checks the layer underneath it.)
  const lmRefusal = ex.rd_env_choice_confirm();
  out.lmRefusedEmpty = lmRefusal;
  out.lmStillPending = ex.rd_env_choice_pending();
  const lmOption = document.querySelector("#modalBody [data-choice]");
  if (lmOption) { lmOption.click(); await sleep(0); }
  const lmConfirm2 = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
  out.lmConfirmEnabled = lmConfirm2 ? !lmConfirm2.disabled : null;
  if (lmConfirm2) { lmConfirm2.onclick(); await sleep(0); await sleep(0); }
  out.lmPendingAfter = ex.rd_env_choice_pending();
  // The hand block is MAX_HAND_SLOTS x 4 starting at OFF_HAND, and +1 inside a slot is the
  // **printed** cost that the page shows. If that column still says 2 while the kernel charges 0,
  // the player is being lied to -- which is what this reads.
  out.lmHandCosts = [];
  for (let slot = 0; slot < Math.min(cell(10), 10); slot++) {
    out.lmHandCosts.push(cell(OFF_HAND + slot * 4 + 1));
  }
  out.lmFreeShown = out.lmHandCosts.filter((cost) => cost === 0).length;
  // And the kernel charges what the screen showed: play the free one, energy must not move.
  const lmEnergyBefore = cell(8);
  const freeSlot = out.lmHandCosts.indexOf(0);
  let playedFree = false;
  if (freeSlot >= 0) {
    for (let tries = 0; tries < ex.rd_env_action_count(); tries++) {
      if (ex.rd_env_action_kind(tries) !== 0 || ex.rd_env_action_arg(tries, 0) !== freeSlot) continue;
      playedFree = ex.rd_env_step(tries) === 0;
      break;
    }
  }
  out.lmPlayedFree = playedFree;
  out.lmEnergyKept = cell(8) === lmEnergyBefore;

  // (j) **§161.5: three candidates.** Attack Potion offers three *definitions* that do not exist as
  // cards yet. The picker renders them through the same pile exports (zone 3), so the two things
  // worth checking are that the three faces are really there and that the sentence says where they
  // came from -- kind alone cannot tell this from Liquid Memories.
  out.apGranted = window.RD_DEBUG.givePotion("attack_potion");
  out.apFight = !document.getElementById("handPanel").hidden;
  const apButton = document.querySelector(
    '[data-use-potion="' + (ex.rd_run_potion_count() - 1) + '"]');
  out.apHasUse = Boolean(apButton);
  if (apButton) {
    try { apButton.onclick(); out.apThrew = null; } catch (error) { out.apThrew = String(error); }
    await sleep(0);
  }
  out.apPending = ex.rd_env_choice_pending();
  out.apSource = ex.rd_env_choice_source();
  out.apKind = ex.rd_env_choice_kind();
  out.apTitle = text(document.getElementById("modalTitle"));
  out.apOptions = document.querySelectorAll("#modalBody [data-choice]").length;
  // Every face must be a real attack with a title -- a definition that the picker cannot name
  // would render as an empty button.
  out.apFaces = [...document.querySelectorAll("#modalBody [data-choice]")]
    .map((el) => text(el)).filter((label) => label.length > 2);
  const cardsBefore = (() => {
    const buf = ex.rd_env_scratch_buf();
    ex.rd_env_observe_into(buf);
    return new Int32Array(ex.memory.buffer, buf, ex.rd_env_observe_len())[10];
  })();
  const apOption = document.querySelector("#modalBody [data-choice]");
  if (apOption) { apOption.click(); await sleep(0); }
  const apConfirm = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
  if (apConfirm) {
    try { apConfirm.onclick(); out.apConfirmThrew = null; } catch (error) { out.apConfirmThrew = String(error); }
    await sleep(0);
    await sleep(0);
  }
  out.apPendingAfter = ex.rd_env_choice_pending();
  {
    const buf = ex.rd_env_scratch_buf();
    ex.rd_env_observe_into(buf);
    const obsNow = new Int32Array(ex.memory.buffer, buf, ex.rd_env_observe_len());
    out.apHandAfter = obsNow[10];
    out.apCosts = [];
    for (let slot = 0; slot < Math.min(obsNow[10], 10); slot++) {
      out.apCosts.push(obsNow[OFF_HAND + slot * 4 + 1]);
    }
  }
  out.apHandGrew = out.apHandAfter === cardsBefore + 1;
  out.apFreeShown = out.apCosts.filter((cost) => cost === 0).length;

  // (k) **§161.9: the one-line archive.**
  window.RD_DEBUG.startWithSeed(4321, 0);
  await sleep(0);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  if (ex.rd_run_pending() === 7) {
    panel().querySelector("[data-panel-action]").click();
    await sleep(0);
    const pick = document.querySelector("#modalBody [data-pick]");
    if (pick) { pick.click(); await sleep(0); }
  }
  // Walk two nodes so the saved run is not the state a fresh start would give -- and **settle**
  // them: the archive refuses while a fight is live (a save that drops the fight would restore the
  // node with the enemies at full health). The first version archived mid-fight and the gate said
  // "存不了 · 战斗中没有存档", which is the refusal working, not the archive failing.
  const settleAll = async () => {
    for (let guard = 0; guard < 400; guard++) {
      if (!document.getElementById("handPanel").hidden) {
        // A card that needs a target **arms** the panels; every later card click is ignored until
        // that target is picked (the same trap the act-1 slice documents). Finish the aim first.
        const aim = document.querySelector("#enemies [data-target-slot]");
        if (aim) {
          aim.click();
          await sleep(0);
          continue;
        }
        const card = document.querySelector("#hand button.card:not([disabled])");
        if (card) {
          card.click();
          await sleep(0);
          continue;
        }
        document.getElementById("endTurn").click();
        await sleep(0);
        continue;
      }
      const button = panel().querySelector("[data-panel-action]:not([disabled])");
      if (!button) return true;
      const label = text(button);
      button.click();
      await sleep(0);
      if (/离开|跳过/.test(label)) return true;
    }
    return false;
  };
  for (let hop = 0; hop < 2; hop++) {
    const lit = [...document.querySelectorAll("#mapbox g.node.reachable")];
    if (!lit.length) break;
    // Only walk a node that is **not** a fight: this scenario is about the archive, and a fight
    // costs a hundred clicks and cannot be archived anyway.
    const view = window.RD_DEBUG.view();
    const calm = lit.find((node) => {
      const kind = Number(node.dataset.kind ? 0 : 0);
      return node.dataset.kind !== "combat" && node.dataset.kind !== "elite" && node.dataset.kind !== "boss";
    });
    (calm || lit[0]).dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await sleep(0);
    await settleAll();
  }
  await settleAll();
  out.archiveFloor = ex.rd_run_observe(0);
  out.archiveHp = ex.rd_run_observe(2);
  out.archiveGold = ex.rd_run_observe(4);
  out.archiveDeck = ex.rd_run_deck_count();
  out.archiveInFight = !document.getElementById("handPanel").hidden;
  out.archiveEnv = {
    done: ex.rd_env_done(), result: ex.rd_env_result(), inFight: out.archiveInFight,
    pending: ex.rd_run_pending(),
  };
  document.getElementById("archiveCopy").onclick();
  await sleep(0);
  const saved = document.getElementById("archiveBox").value;
  out.archiveText = saved.slice(0, 9);
  out.archiveLength = saved.length;
  out.archiveLines = saved.split(String.fromCharCode(10)).length;
  out.archiveNote = text(document.getElementById("archiveNote"));
  out.archiveRefusedInFight = out.archiveInFight ? saved.length : -1;

  // A fresh, different run: (4322) rather than (4321), so nothing can pass by accident.
  window.RD_DEBUG.startWithSeed(4322, 0);
  await sleep(0);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  if (ex.rd_run_pending() === 7) {
    panel().querySelector("[data-panel-action]").click();
    await sleep(0);
    const pick = document.querySelector("#modalBody [data-pick]");
    if (pick) { pick.click(); await sleep(0); }
  }
  out.archiveSeedAfterRestart = ex.rd_run_seed();

  // Paste and restore through the page's own button.
  document.getElementById("archiveBox").value = saved;
  document.getElementById("archiveRestore").onclick();
  await sleep(0);
  out.restoredSeed = ex.rd_run_seed();
  out.restoredFloor = ex.rd_run_observe(0);
  out.restoredHp = ex.rd_run_observe(2);
  out.restoredGold = ex.rd_run_observe(4);
  out.restoredDeck = ex.rd_run_deck_count();
  out.restoredNote = text(document.getElementById("archiveNote"));

  // One edited character must be **refused**, and the run must not move.
  const edited = saved.slice(0, 12) + (saved[12] === "A" ? "B" : "A") + saved.slice(13);
  document.getElementById("archiveBox").value = edited;
  document.getElementById("archiveRestore").onclick();
  await sleep(0);
  out.editedRefused = /被拒/.test(text(document.getElementById("archiveNote")));
  out.afterEditFloor = ex.rd_run_observe(0);
  out.afterEditSeed = ex.rd_run_seed();

  // …and the same run saved twice is the same string.
  document.getElementById("archiveCopy").onclick();
  await sleep(0);
  out.archiveStable = document.getElementById("archiveBox").value === saved;

  // §159: (seed, level) is the whole description of a run. Drive it through the **fields** the
  // player actually uses -- typing a level and pressing 开始 -- because a page whose level input is
  // not read is a dead affordance, and startWithSeed would have hidden that.
  // (No backticks in this comment: the whole block is already inside a template literal, and a
  // backtick here ends it -- which is how this section first failed to parse.)
  const asc = document.getElementById("ascInput");
  const seedField = document.getElementById("seedInput");
  if (asc && seedField) {
    seedField.value = "2222";
    asc.value = "14";
    document.getElementById("newRunBtn").onclick();
    await sleep(0);
  }
  out.ascLevel = ex.rd_run_ascension();
  out.ascSeed = ex.rd_run_seed();
  out.ascMaxHp = ex.rd_run_observe(3);
  // textContent + collapsed whitespace, not innerText: innerText of two adjacent <b> elements puts a
  // newline between them, so the readable assertion below would fail on a top bar that is correct.
  out.ascTopBar = document.getElementById("runStats").textContent.replace(/\s+/g, " ").trim();
  return out;
})()`);

// ---- 4. the assertions ("key text must appear") -----------------------------------------------
const problems = [];
const want = (condition, why) => {
  if (!condition) problems.push(why);
};

want(report.blessings.length >= 2, `expected two blessings, got ${JSON.stringify(report.blessings)}`);
want(
  report.blessings.every((label) => !/^[a-z_]+$/.test(label)),
  `a blessing shows its raw id: ${JSON.stringify(report.blessings)}`
);
want(report.afterBlessing.pending === 0, `the blessing did not settle (pending ${report.afterBlessing.pending})`);
want(
  report.refusal.includes("走不过去"),
  `an unreachable node said ${JSON.stringify(report.refusal)}`
);
want(report.fight.inFight, "the fight did not start");
want(report.card?.open === true, "Shift+click did not open the card detail");
want((report.card?.body || "").length > 3, "the card detail has no text");
want(report.card?.closed === true, "the card detail cannot be closed by a click (§151)");
want(
  report.log.some((line) => line.includes("打出")),
  `the log does not name the card played: ${JSON.stringify(report.log)}`
);
want(
  /^幕 [0-9]/.test(report.topBar),
  `the top bar does not name the act: ${JSON.stringify(report.topBar)}`
);
want(
  report.energyAfter === 0 ? report.unaffordable > 0 : true,
  "with no energy left, no card is marked unaffordable"
);
// §150: the potion button must *do* something -- and a handler that throws counts as "did nothing".
want(report.potionInBelt === 1, `the reward did not hand over a potion (belt ${report.potionInBelt})`);
want(report.potionFight === true, "could not reach a second fight to use the potion in");
want(
  report.potionHasUse === true,
  "a potion in the belt offers no 用 button while in a fight"
);
want(report.potionThrew === null, `the potion button threw: ${report.potionThrew}`);
want(
  report.potionAfter === 0,
  `the potion was not consumed (still ${report.potionAfter} in the belt)`
);
want(
  !report.potionBeltAfter.includes("chip potion"),
  `the belt still shows the potion after using it: ${report.potionBeltAfter}`
);
// §159: typing a level and pressing 开始 must actually start **that** run.
want(report.ascLevel === 14, `the level input did not reach the kernel (got ${report.ascLevel})`);
want(report.ascSeed === 2222, `the seed input did not reach the kernel (got ${report.ascSeed})`);
want(
  report.ascMaxHp === 75,
  `A14 must set the maximum to 75, the run says ${report.ascMaxHp}`
);
want(
  /A14/.test(report.ascTopBar),
  `the top bar does not show the level: ${JSON.stringify(report.ascTopBar)}`
);

// §161.3: the card-choice picker, on the real DOM.
want(report.choiceFight === true, "could not reach a fight to open the card choice in");
want(report.choiceGranted === 0, `the debug potion grant failed (${report.choiceGranted})`);
want(report.choiceHasUse === true, "an Elixir on the belt offered no 用 button in a fight");
want(report.choiceThrew === null, `the Elixir button threw: ${report.choiceThrew}`);
want(report.choicePending === 1, `drinking Elixir opened no question (pending ${report.choicePending})`);
want(report.choiceKind === 1, `the question is not an exhaust (kind ${report.choiceKind})`);
want(report.choiceModalOpen === true, "the picker did not open");
want(/消耗/.test(report.choiceTitle || ""),
  `the picker does not say what it does: ${JSON.stringify(report.choiceTitle)}`);
want(report.choiceOptions >= 2,
  `the picker offered ${report.choiceOptions} cards, expected the whole hand`);
want(report.choiceEnvActions === 0,
  `the action table has ${report.choiceEnvActions} entries while a question is open`);
want(report.choiceStillOpen === true, "the picker closed with the question still open");
want(report.choiceTicked === "1", `clicking an option did not tick it (${report.choiceTicked})`);
want(report.choiceHasConfirm === true, "the picker has no confirm button");
want(report.choiceConfirmThrew === null, `confirm threw: ${report.choiceConfirmThrew}`);
want(report.choicePendingAfter === 0, "confirming did not answer the question");
want(report.choiceExhausted === 1, `confirming exhausted ${report.choiceExhausted} cards, expected 1`);
want(report.choiceEnvActionsAfter > 0, "the action table did not come back after the answer");

// §161.4: Liquid Memories -- the card comes back, free, and the screen agrees.
want(report.lmFight === true, "could not reach a fight for the Liquid Memories check");
want(report.lmGranted === 0, `the debug grant failed for liquid_memories (${report.lmGranted})`);
want(report.lmDiscards >= 1, "the discard pile is empty: Liquid Memories has nothing to offer");
want(report.lmHasUse === true, "Liquid Memories offered no 用 button");
want(report.lmThrew === null, `the Liquid Memories button threw: ${report.lmThrew}`);
want(report.lmPending === 1, `drinking it opened no question (pending ${report.lmPending})`);
want(report.lmKind === 3, `the question is not a take-into-hand (kind ${report.lmKind})`);
want(/弃牌堆/.test(report.lmTitle || ""),
  `the picker does not say where the card comes from: ${JSON.stringify(report.lmTitle)}`);
want(report.lmConfirmDisabledEmpty === true,
  "confirm is enabled with nothing ticked, but the question demands exactly one card");
want(report.lmRefusedEmpty === -2, `the kernel did not refuse an empty answer (${report.lmRefusedEmpty})`);
want(report.lmStillPending === 1, "an empty answer consumed the question");
want(report.lmConfirmEnabled === true, "confirm stayed disabled after ticking a card");
want(report.lmPendingAfter === 0, "confirming did not answer the question");
want(report.lmFreeShown >= 1,
  `no card in hand reads 0 after Liquid Memories (costs ${JSON.stringify(report.lmHandCosts)})`);
want(report.lmPlayedFree === true, "the free card is not playable");
want(report.lmEnergyKept === true,
  "playing the free card spent energy: the screen said 0 and the kernel took more");

// §161.5: three offered candidates, one card created, and it is free.
want(report.apFight === true, "could not reach a fight for the Attack Potion check");
want(report.apGranted === 0, `the debug grant failed for attack_potion (${report.apGranted})`);
want(report.apHasUse === true, "Attack Potion offered no 用 button");
want(report.apThrew === null, `the Attack Potion button threw: ${report.apThrew}`);
want(report.apPending === 1, `drinking it opened no question (pending ${report.apPending})`);
want(report.apSource === 2, `the source is not "offered" (source ${report.apSource})`);
want(report.apKind === 3, `the question is not a take-into-hand (kind ${report.apKind})`);
want(/候选/.test(report.apTitle || ""),
  `the picker does not say the cards are candidates: ${JSON.stringify(report.apTitle)}`);
want(report.apOptions === 3, `the picker offered ${report.apOptions} cards, expected 3`);
want(report.apFaces.length === 3,
  `only ${report.apFaces.length} of the three candidates rendered a name`);
want(report.apConfirmThrew === null, `confirm threw: ${report.apConfirmThrew}`);
want(report.apPendingAfter === 0, "confirming did not answer the question");
want(report.apHandGrew === true, "the hand did not grow by exactly one card");
want(report.apFreeShown >= 1,
  `no card reads 0 after the Attack Potion (costs ${JSON.stringify(report.apCosts)})`);

// §161.9: the one-line archive, through the page's own buttons.
want(
  report.archiveInFight === false,
  `an archive was taken mid-fight (env ${JSON.stringify(report.archiveEnv)})`
);
want(
  (report.archiveText || "").startsWith("RDA1-"),
  `the archive does not start with RDA1- (${JSON.stringify(report.archiveText)})`
);
want(report.archiveLength > 100, `the archive is suspiciously short (${report.archiveLength})`);
want(report.archiveLines === 1, `the archive is ${report.archiveLines} lines, expected one`);
want(/已复制|剪贴板/.test(report.archiveNote || ""),
  `copy said nothing useful: ${JSON.stringify(report.archiveNote)}`);
want(report.archiveSeedAfterRestart === 4322,
  `the restart did not change the seed (${report.archiveSeedAfterRestart})`);
want(report.restoredSeed === 4321, `restore gave seed ${report.restoredSeed}, expected 4321`);
want(report.restoredFloor === report.archiveFloor,
  `floor ${report.restoredFloor} != ${report.archiveFloor}`);
want(report.restoredHp === report.archiveHp, `hp ${report.restoredHp} != ${report.archiveHp}`);
want(report.restoredGold === report.archiveGold,
  `gold ${report.restoredGold} != ${report.archiveGold}`);
want(report.restoredDeck === report.archiveDeck,
  `deck ${report.restoredDeck} != ${report.archiveDeck}`);
want(report.editedRefused === true, "an edited archive was accepted");
want(report.afterEditFloor === report.restoredFloor,
  "a refused restore moved the run anyway (that is the worse bug)");
want(report.afterEditSeed === 4321, "a refused restore changed the seed");
want(report.archiveStable === true, "the same run produced two different archives");

await page.close();


if (problems.length) {
  for (const problem of problems) console.error("  - " + problem);
  fail(`${problems.length} assertion(s) failed`);
}
console.log("  blessings         " + report.blessings.join(" / "));
console.log("  refusal           " + report.refusal);
console.log("  card detail       " + report.card.title + " · " + report.card.body);
console.log("  log               " + report.log[report.log.length - 1]);
console.log("  top bar           " + report.topBar);
console.log("  energy/unafford.  " + report.energyAfter + " / " + report.unaffordable);
console.log("  archive env       " + JSON.stringify(report.archiveEnv || null));
console.log("  archive           " + report.archiveText + "… · " +
  report.archiveLength + " chars · " + report.archiveLines + " line(s) · restored floor " +
  report.restoredFloor + " hp " + report.restoredHp + " gold " + report.restoredGold +
  " · edited refused " + report.editedRefused);
console.log("  attack potion     " + report.apTitle + " · " + report.apOptions +
  " option(s) · hand +1 " + report.apHandGrew + " · free shown " + report.apFreeShown);
console.log("  liquid memories   " + report.lmTitle + " · " + report.lmFreeShown +
  " free card(s) · empty answer refused " + report.lmRefusedEmpty +
  " · free play kept energy " + report.lmEnergyKept);
console.log("  card choice       " + report.choiceTitle + " · " + report.choiceOptions +
  " option(s) · ticked " + report.choiceTicked + " · exhausted " + report.choiceExhausted +
  " · table " + report.choiceEnvActions + " -> " + report.choiceEnvActionsAfter);
console.log("  potion            belt " + report.potionInBelt + " -> " + report.potionAfter +
  (report.potionThrew ? " · THREW " + report.potionThrew : ""));
console.log("BROWSER_TEST PASS");
