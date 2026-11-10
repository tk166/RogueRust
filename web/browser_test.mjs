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

  // (l) **§279: a locked option is not drawn.** 'forgotten_altar' 的第一个选项是条件选项
  // （要持有金像）。这一屏的判据是**DOM**：内核说不可选，页面上就不能有那个按钮 ——
  // 画出来的死按钮比藏起来少一条路更糟。反面（可选的那个**必须**画出来）用同一个屏幕的
  // 按钮数对上：4 个选项、1 个锁着 ⇒ 3 个按钮。
  window.RD_DEBUG.startWithSeed(4321, 0);
  await sleep(0);
  out.condOpened = window.RD_DEBUG.startAnEvent("forgotten_altar");
  out.condKind = ex.rd_run_node_kind();
  out.condPending = ex.rd_run_pending();
  out.condOptions = ex.rd_run_event_option_count();
  out.condAvailable = [];
  for (let slot = 0; slot < out.condOptions; slot++) {
    out.condAvailable.push(ex.rd_run_event_option_available(slot));
  }
  out.condButtons = [...panel().querySelectorAll("[data-panel-action]")].map((el) => text(el));
  out.condLockedDrawn = out.condButtons.some((label) => /Golden Idol/.test(label));
  // 点一个**锁着**的槽：内核必须拒（-2），而且屏幕不能变（事件还开着、选项还在）。
  out.condRefused = ex.rd_run_choose(0);
  out.condPendingAfterRefusal = ex.rd_run_pending();
  await sleep(0);

  // (l2) **§287: [Destroy] 只在牌组里有"单次 >=10 伤害"的牌时出现。**
  // 起始牌组最好的单次是 bash 的 8，所以这一屏必须画 **2** 个按钮（[Pray] 与 [Leave]），
  // [Destroy] 不在 DOM 里。内核那一侧的两侧（bash+ 在 / strike 不在）由
  // rd-core 的 the_unknown_room_events_are_readable 用真实镜像钉着。
  window.RD_DEBUG.startWithSeed(4321, 0);
  await sleep(0);
  out.wingOpened = window.RD_DEBUG.startAnEvent("wing_statue");
  out.wingOptions = ex.rd_run_event_option_count();
  out.wingAvailable = [];
  for (let slot = 0; slot < out.wingOptions; slot++) {
    out.wingAvailable.push(ex.rd_run_event_option_available(slot));
  }
  out.wingButtons = [...panel().querySelectorAll("[data-panel-action]")].map((el) => text(el));
  out.wingDestroyDrawn = out.wingButtons.some((label) => /Destroy/.test(label));
  // 点那个被藏起来的槽：内核必须拒（-2），屏幕不变。
  out.wingRefused = ex.rd_run_choose(1);
  out.wingPendingAfter = ex.rd_run_pending();
  await sleep(0);

  // (l3) **§293: the "pick a card to add" question (orrery / tiny_house / singing_bowl).**
  // A Shop-rarity and a Boss-rarity relic are exactly the two a seed will not hand you, so the
  // page's debug surface grants them -- the same reason givePotion exists.
  // (No backticks in this block: it is inside a template literal.)
  window.RD_DEBUG.startWithSeed(4321, 0);
  await sleep(0);
  out.addGranted = window.RD_DEBUG.giveRelic("orrery");
  out.addOwed = ex.rd_run_pickup_add();
  out.addOffer = ex.rd_run_pickup_offer_count();
  await sleep(0);
  // The panel must be the add-cards one, with one row per offered card and a slot that matches.
  out.addRows = [...panel().querySelectorAll("[data-panel-action]")]
    .map((el) => text(el));
  out.addHeading = text(panel()).slice(0, 40);
  // 点第一行：牌组 +1、欠账 -1（这是"面板真的能操作内核"的那一步）。
  const deckBefore = ex.rd_run_deck_count();
  if (out.addRows.length > 0) {
    panel().querySelectorAll("[data-panel-action]")[0].click();
    await sleep(0);
  }
  out.addDeckGrew = ex.rd_run_deck_count() - deckBefore;
  out.addOwedAfter = ex.rd_run_pickup_add();

  // singing_bowl：+2 上限的按钮**只在持有那件遗物时**才画（否则是死按钮）。
  window.RD_DEBUG.startWithSeed(4321, 0);
  await sleep(0);
  window.RD_DEBUG.giveRelic("orrery");
  await sleep(0);
  out.addButtonsNoBowl = [...panel().querySelectorAll("[data-panel-action]")].map((el) => text(el));
  window.RD_DEBUG.giveRelic("singing_bowl");
  await sleep(0);
  out.addButtonsWithBowl = [...panel().querySelectorAll("[data-panel-action]")].map((el) => text(el));
  const maxBefore = ex.rd_run_observe(3);
  const bowlBtn = [...panel().querySelectorAll("[data-panel-action]")]
    .find((el) => /上限/.test(text(el)));
  if (bowlBtn) { bowlBtn.click(); await sleep(0); }
  out.addMaxHpGrew = ex.rd_run_observe(3) - maxBefore;
  out.addOwedAfterBowl = ex.rd_run_pickup_add();

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
  // 164: the replay, through the page's own buttons -- on a run that has **steps** (the two hops
  // above), because a zero-step script would make every assertion below vacuous.
  document.getElementById("scriptExport").onclick();
  await sleep(0);
  const script = document.getElementById("scriptBox").value;
  out.scriptHead = script.slice(0, 9);
  out.scriptSteps = script.split(";").filter((part) => part.length > 0).length - 1;
  out.scriptExportNote = text(document.getElementById("scriptNote"));
  out.scriptFloorBefore = ex.rd_run_observe(0);
  document.getElementById("scriptReplay").onclick();
  await sleep(0);
  out.scriptReplayNote = text(document.getElementById("scriptNote"));
  out.scriptFloorAfter = ex.rd_run_observe(0);
  out.scriptSeedAfter = ex.rd_run_seed();
  out.scriptChecked = ex.rd_run_replay_checked();

  // Tamper the **second** record's hash: the page must name that step, not just "failed".
  const parts = script.split(";");
  // §235: 这一段原来是直接 parts[2].split(",")，脚本变短时会抛 TypeError: reading 'slice'
  // —— 一个看不出原因的崩溃。现在把"记录不够"变成一个读得懂的断言：数一数有几条。
  out.scriptRecords = parts.length;
  if (parts.length > 2) {
    const cells = parts[2].split(",");
    if (cells.length > 3) {
      cells[3] = cells[3].slice(0, 15) + (cells[3].slice(15) === "0" ? "1" : "0");
      parts[2] = cells.join(",");
    }
  }
  document.getElementById("scriptBox").value = parts.join(";");
  document.getElementById("scriptReplay").onclick();
  await sleep(0);
  out.scriptTamperNote = text(document.getElementById("scriptNote"));
  out.scriptTamperDiverged = ex.rd_run_replay_diverged();
  out.scriptTamperChecked = ex.rd_run_replay_checked();

  // An empty box must not start a run and must not say "passed".
  document.getElementById("scriptBox").value = "";
  document.getElementById("scriptReplay").onclick();
  await sleep(0);
  out.scriptEmptyNote = text(document.getElementById("scriptNote"));

  // 166: a script from **another content build** must be refused before step 1, and the page must show
  // both fingerprints. The pin lives in the head's 5th field of RDR1,S,seed,asc,pin.
  out.contentPin = text(document.getElementById("contentPin"));
  const headParts = script.split(";")[0].split(",");
  out.scriptPin = headParts[4];
  const otherContent = script.split(";");
  otherContent[0] = [headParts[0], headParts[1], headParts[2], headParts[3], "deadbeef"].join(",");
  document.getElementById("scriptBox").value = otherContent.join(";");
  document.getElementById("scriptReplay").onclick();
  await sleep(0);
  out.contentMismatchNote = text(document.getElementById("scriptNote"));
  out.contentMismatchChecked = ex.rd_run_replay_checked();
  out.contentMismatchSeed = ex.rd_run_seed();

  // Put the run **back** on the recorded path: the tampered replay stopped at step 2, so the archive
  // below would otherwise be taken from an earlier floor.
  document.getElementById("scriptBox").value = script;
  document.getElementById("scriptReplay").onclick();
  await sleep(0);
  out.scriptBackFloor = ex.rd_run_observe(0);

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
  // 164: a restored run's script starts at its **archive**, not at (seed, level) -- the restored
  // state is not on the "played from the start" timeline. Zero steps is the right answer here: the
  // run *is* the archive, and replaying it proves that the head round-trips.
  document.getElementById("scriptExport").onclick();
  await sleep(0);
  const restoredScript = document.getElementById("scriptBox").value;
  out.scriptArchiveHead = restoredScript.startsWith("RDR1,A,RDA1-");
  out.scriptArchiveSteps = restoredScript.split(";").filter((part) => part.length > 0).length - 1;
  document.getElementById("scriptReplay").onclick();
  await sleep(0);
  out.scriptArchiveNote = text(document.getElementById("scriptNote"));
  out.scriptArchiveSeed = ex.rd_run_seed();
  out.scriptArchiveFloor = ex.rd_run_observe(0);


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

  // ---- §203: act-2 / act-3 content, fought for real ---------------------------------------------
  // The act-1 slice can only reach act 2 by **winning an act** (~30 nodes plus a boss), and act 3
  // needs a second win. A gate that waits for that is a coin toss that fails on unrelated content
  // changes, so the page exposes a debug "fight this encounter now" (RD_DEBUG.fightEncounter,
  // built through the same build_session_at the run uses). What these two drive is exactly what
  // the act-1 slice cannot: the **enemy panel** against summons and self-removal.
  //
  // (No backticks in this block: it is inside a template literal.)
  const enemySlots = () => {
    const panelEl = document.getElementById("enemies");
    // One entry per painted enemy: the panel gives each a data-enemy-panel ordinal.
    const shown = [...panelEl.querySelectorAll("[data-enemy-panel]")];
    return shown.map((el) => (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40));
  };
  /// §345：每个面板的**敌人 id**（内核给的那个）。显示名是显示层的事，判据只关心身份 ——
  /// 原来按"面板文本的第一个词"取名字，在页面开始印显示名（"Bronze Orb"）之后分不出谁是谁。
  const enemyIds = () => {
    const panelEl = document.getElementById("enemies");
    return [...panelEl.querySelectorAll("[data-enemy-panel]")]
      .map((el) => el.getAttribute("data-enemy-id") || "");
  };
  // Only ever click the page's own button. Stepping the ABI directly was the first attempt and it
  // **desynced** the page from the session: the end-turn button is disabled exactly while an enemy
  // is acting, so stepping anyway ran a second END_TURN on top of a turn the page had not painted --
  // and the panel then showed one fight's health with another fight's names.
  const fightFor = async (rounds) => {
    for (let step = 0; step < rounds; step++) {
      if (ex.rd_env_done() !== 0) break;
      if (document.getElementById("handPanel").hidden) break; // the fight left the screen
      const end = document.getElementById("endTurn");
      if (end && !end.disabled) end.click();
      await sleep(0);
      await sleep(0);
    }
  };

  out.act2 = {};
  if (typeof window.RD_DEBUG.fightEncounter === "function") {
    const verdict = window.RD_DEBUG.fightEncounter("enc_bronze_automaton");
    out.act2.build = verdict;
    out.act2.error = verdict === 0 ? "" : lastError();
    if (verdict === 0) {
      out.act2.opening = enemySlots();
      // The boss summons two orbs on its first turn: the panel has to **grow**, and the new
      // entries have to be distinguishable (the page keys them by slot, the kernel by id).
      await fightFor(6);
      out.act2.after = enemySlots();
      out.act2.afterIds = enemyIds();
      out.act2.threw = lastError();
    }
  }

  out.act3 = {};
  if (typeof window.RD_DEBUG.fightEncounter === "function") {
    const verdict = window.RD_DEBUG.fightEncounter("enc_reptomancer");
    out.act3.build = verdict;
    out.act3.error = verdict === 0 ? "" : lastError();
    if (verdict === 0) {
      out.act3.opening = enemySlots();
      // Daggers explode and leave the fight (§200/§201): the panel must lose an entry, which is
      // the one thing a page can get wrong even when the kernel is right (a stale render keeps
      // painting the dead one).
      let left = out.act3.opening.length;
      for (let step = 0; step < 60; step++) {
        if (ex.rd_env_done() !== 0) break;
        await fightFor(1);
        const now = enemySlots();
        if (now.length && now.length < left) {
          left = now.length;
          out.act3.after = now;
          break;
        }
      }
      out.act3.openingCount = out.act3.opening.length;
      out.act3.leftCount = left;
      out.act3.errorEnd = lastError();
      // Why the loop stopped: "no dagger left" and "the fight ended" need different fixes, and a
      // bare count cannot tell them apart.
      out.act3.done = ex.rd_env_done();
      out.act3.result = ex.rd_env_result();
      out.act3.hp = (() => {
        const buf = ex.rd_env_scratch_buf();
        ex.rd_env_observe_into(buf);
        return new Int32Array(ex.memory.buffer, buf, ex.rd_env_observe_len())[4];
      })();
      out.act3.inFight = !document.getElementById("handPanel").hidden;
      out.act3.msg = (document.getElementById("msg").textContent || "").replace(/\s+/g, " ").slice(0, 120);
    }
  }

  // §203: put the page back on the run screen. The pointer section below drives **real** mouse
  // events at the run UI, and a page left in fight mode has no seed field to type into -- the
  // first version of this block made nine unrelated pointer assertions fail exactly that way.
  debugFight = false;
  setMode("run");
  renderMap();
  renderNode();
  renderTopBar();

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

// 164: the replay, through the page's own buttons.
want(report.scriptHead === "RDR1,S,43", `the script head is ${JSON.stringify(report.scriptHead)}`);
want(report.scriptSteps > 0, `the exported script has ${report.scriptSteps} step(s)`);
want(report.scriptBackFloor === report.scriptFloorBefore,
  `replaying the good script did not return to floor ${report.scriptFloorBefore} ` +
  `(it went to ${report.scriptBackFloor})`);
want(/已导出/.test(report.scriptExportNote || ""),
  `export said nothing useful: ${JSON.stringify(report.scriptExportNote)}`);
want(/回放通过/.test(report.scriptReplayNote || ""),
  `replay did not pass: ${JSON.stringify(report.scriptReplayNote)}`);
want(report.scriptChecked === report.scriptSteps,
  `verified ${report.scriptChecked} of ${report.scriptSteps} step(s)`);
want(report.scriptFloorAfter === report.scriptFloorBefore && report.scriptSeedAfter === 4321,
  `the replay did not land on the same run (floor ${report.scriptFloorAfter}, seed ${report.scriptSeedAfter})`);
want(report.scriptTamperDiverged === 2,
  `a tampered step 2 was reported as step ${report.scriptTamperDiverged}`);
want(report.scriptTamperChecked === 1,
  `${report.scriptTamperChecked} step(s) verified before the tampered one, expected 1`);
want(/第 2 步/.test(report.scriptTamperNote || ""),
  `the page did not name the diverging step: ${JSON.stringify(report.scriptTamperNote)}`);
want(/框是空的/.test(report.scriptEmptyNote || ""),
  `an empty script was not refused: ${JSON.stringify(report.scriptEmptyNote)}`);
// 166: the content fingerprint is on the page, in the script head, and a foreign build is refused
// **before** any step runs (a script that diverges at step 5 also returns non-zero -- and by then the
// run has already been changed).
want(/^内容 [0-9a-f]{8}$/.test(report.contentPin || ""),
  `the page's content pin reads ${JSON.stringify(report.contentPin)}`);
want(report.scriptPin === report.contentPin.replace("内容 ", ""),
  `the script head's pin ${JSON.stringify(report.scriptPin)} is not the page's ` +
  JSON.stringify(report.contentPin));
want(/内容版本不同/.test(report.contentMismatchNote || ""),
  `a foreign content was not refused: ${JSON.stringify(report.contentMismatchNote)}`);
want((report.contentMismatchNote || "").indexOf("deadbeef") >= 0 &&
  (report.contentMismatchNote || "").indexOf(report.scriptPin) >= 0,
  "the refusal did not name both content builds: " + JSON.stringify(report.contentMismatchNote));
want(report.contentMismatchChecked === 0,
  `${report.contentMismatchChecked} step(s) were applied before the content was checked`);

// …and a **restored** run's script starts at its archive. This is the half that keeps a restore from
// silently poisoning the journal: the restored state is not on the "played from the start" timeline.
want(report.scriptArchiveHead === true,
  "a restored run's script did not start at its archive");
want(report.scriptArchiveSteps === 0,
  `a restored run's script claims ${report.scriptArchiveSteps} step(s), expected 0 before playing on`);
want(/回放通过/.test(report.scriptArchiveNote || ""),
  `replaying an archive-headed script failed: ${JSON.stringify(report.scriptArchiveNote)}`);
want(report.scriptArchiveSeed === 4321 && report.scriptArchiveFloor === report.restoredFloor,
  `the archive-headed replay landed on seed ${report.scriptArchiveSeed} floor ${report.scriptArchiveFloor}`);

// §165: the **same** page, pressed with real pointer events (CDP `Input.dispatchMouseEvent`).
//
// Everything above dispatches synthetic `MouseEvent`s from inside the page, which skips hit-testing:
// a control that a modal covers, or that is scrolled out of view, still "clicks" for the test and is
// dead for the player. So this section (a) types a seed, (b) presses 开始, (c) settles the blessing
// through the panels the player actually uses, (d) proves that a real click **on the map** while a
// modal is up is swallowed by the backdrop, and (e) walks into a node and presses a card.
const pointer = {};
// One observation reader for this section: `rd_env_observe_buf()` is the page's own source, so this
// cannot drift from what the UI shows (index 8 = energy, 0 = round, 1 = turn).
const readCell = async (index) =>
  page.evaluate(
    "(() => { const ptr = ex.rd_env_observe_buf(); const n = ex.rd_env_observe_len();" +
      " const o = new Int32Array(ex.memory.buffer, ptr, n); return o[" + index + "]; })()"
  );
const settle = () => new Promise((resolve) => setTimeout(resolve, 50));
/**
 * Poll a page expression until it equals `want` (or the budget runs out).
 *
 * `settle()` is a **fixed** 50 ms sleep while the page re-renders on its own schedule: under a loaded
 * machine that is occasionally too short, which made this section fail once inside the acceptance
 * gate and pass when run on its own. Waiting for the **state** instead of the clock removes the whole
 * class -- the assertion after it can no longer race the render.
 */
const waitFor = async (expression, want, budgetMs = 3000) => {
  const until = Date.now() + budgetMs;
  let seen;
  for (;;) {
    seen = await page.evaluate(expression);
    if (seen === want || Date.now() > until) return seen;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
};
/** Click the first of several selectors that exists; report which one took it. */
const clickFirst = async (selectors) => {
  for (const selector of selectors) {
    const box = await page.clickSelector(selector, 0);
    if (!box.missing && !box.empty) return { ...box, selector: selector };
  }
  return { missing: true, tried: selectors };
};
const reachableKinds = () =>
  page.evaluate(
    "[...document.querySelectorAll('#mapbox g.node.reachable')].map(function (n) {" +
      " return n.dataset.kind; })"
  );

/**
 * Type a seed, press 开始, and settle the blessing -- all with real pointer events.
 *
 * The blessing is `pending` 6 (choose one of two offers) then 7 (the offer owes a **deck pick**),
 * which the panel turns into a button that opens the picker in the modal. So the loop alternates:
 * a picker row if one is on screen, otherwise the panel's own button.
 */
async function realStart(seed, trail) {
  const typed = await page.typeInto("#seedInput", seed);
  const start = await page.clickSelector("#newRunBtn");
  await settle();
  const pending0 = await waitFor("ex.rd_run_pending()", 6);
  let clicks = 0;
  let stuck = -1;
  while (clicks < 8) {
    const pending = await page.evaluate("ex.rd_run_pending()");
    if (pending === 0 || pending === 4 || pending === 8) break;
    let hit = await clickFirst(["#modalBody [data-pick]", "#nodePanel [data-pick]"]);
    if (hit.missing) {
      hit = await clickFirst(["#nodePanel [data-panel-action]", "#modalBody [data-panel-action]"]);
    }
    clicks += 1;
    if (hit.missing) {
      stuck = pending;
      break;
    }
    if (trail) trail.push(pending + ":" + (hit.selector.indexOf("data-pick") >= 0 ? "pick" : "panel"));
    await settle();
  }
  return {
    typedValue: typed.value,
    typedHits: typed.hits,
    startHits: start.hits,
    startCover: start.coverTag,
    seedAfterStart: await page.evaluate("ex.rd_run_seed()"),
    pending0: pending0,
    clicks: clicks,
    stuck: stuck,
    pending: await page.evaluate("ex.rd_run_pending()"),
    kinds: await reachableKinds(),
  };
}

{
  // A combat node at floor 1 is what makes the card half of this section runnable; whether one is
  // reachable is a property of the seed, so try a few (bounded) rather than trusting one.
  const seeds = ["777", "778", "779", "780", "781", "782", "783", "784"];
  let attempt = null;
  pointer.tried = [];
  for (const seed of seeds) {
    const trail = [];
    attempt = await realStart(seed, trail);
    pointer.tried.push(seed + ":" + (attempt.kinds.join(",") || "-"));
    if (attempt.pending === 0 && attempt.kinds.some((kind) => kind === "combat")) break;
    if (attempt.stuck >= 0) break;
  }
  pointer.typed = attempt.typedValue;
  pointer.seed = attempt.seedAfterStart;
  pointer.seedAfterStart = attempt.seedAfterStart;
  pointer.typedHits = attempt.typedHits;
  pointer.startHits = attempt.startHits;
  pointer.startCover = attempt.startCover;
  pointer.pendingAfterStart = attempt.pending0;
  pointer.blessingClicks = attempt.clicks;
  pointer.blessingStuck = attempt.stuck;
  pointer.pendingAfterBlessing = attempt.pending;
  pointer.kinds = attempt.kinds;
  pointer.mapNodesAll = await page.evaluate("document.querySelectorAll('#mapbox g.node').length");
  pointer.modalOpen = false;

  // (d) the falsifiable half: open a modal, then press a map node with a **real** click. The modal's
  // backdrop is on top, so the click must be swallowed -- `dispatchEvent` would have walked the run.
  // Opened through the debug hook because a deck view is otherwise reached from inside a run state
  // this test does not need to reproduce; the click under test is the map node, not the opener.
  await page.evaluate("RD_DEBUG.showDeckPicker ? (RD_DEBUG.showDeckPicker('real click', function () {}), 1) : 0");
  await settle();
  pointer.modalOpen = await waitFor("!document.getElementById('modal').hidden", true);
  // A **probe** here, not `clickSelector`: `clickSelector` waits until the target is hit-testable,
  // which is the opposite of what this line is asking. We want the map node's coordinates and who is
  // on top of them -- then a real click at exactly that point, which the modal must swallow.
  const covered = await page.probe("#mapbox g.node.reachable", 0);
  pointer.mapCoveredHits = covered.hits;
  pointer.mapCover = covered.coverTag || (covered.missing ? "no reachable node" : null);
  pointer.mapCovered = covered.hits === false;
  // 同一坐标、真输入：弹窗必须把它吃掉（不是"等它可点"，那会变成另一条测试）。
  if (!covered.missing && !covered.empty) await page.clickAt(covered.x, covered.y);
  await settle();
  pointer.floorWhileModalUp = await page.evaluate("ex.rd_run_observe(0)");
  pointer.pendingWhileModalUp = await page.evaluate("ex.rd_run_pending()");
  // ⚠️ 这一枪可能**落在背景上**，而背景点击正是 §151 的三种出口之一 ⇒ 弹窗自己关掉。
  // 所以"关掉了吗"不能当作 × 的证据：两条判据必须从各自确定的前提出发。
  pointer.modalStillOpen = !(await page.evaluate("document.getElementById('modal').hidden"));

  // 第二条判据：重新打开一次，让弹窗处于**确定打开**的状态，再真点 ×。
  await page.evaluate("RD_DEBUG.showDeckPicker ? (RD_DEBUG.showDeckPicker('close me', function () {}), 1) : 0");
  pointer.reopened = await waitFor("!document.getElementById('modal').hidden", true);
  const closed = await page.clickSelector("#modalClose");
  pointer.closeHits = closed.hits;
  // 记下"到底谁在上面"——一条只说"被盖住了"的失败信息让人只能猜。
  pointer.closeCover = closed.coverTag;
  pointer.closeBox = [Math.round(closed.x), Math.round(closed.y),
    Math.round(closed.width), Math.round(closed.height)];
  if (closed.hits !== true) {
    // 失败时把现场留下：只说"被盖住了"让人只能猜，而这条已经猜错两次了。
    pointer.closeLayout = await page.evaluate(`(() => {
      const rect = function (el) {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return [Math.round(r.width), Math.round(r.height), s.display, s.visibility];
      };
      return {
        modalHidden: document.getElementById("modal").hidden,
        modal: rect(document.getElementById("modal")),
        box: rect(document.querySelector(".modal-box")),
        close: rect(document.getElementById("modalClose")),
        bodyChildren: document.getElementById("modalBody").children.length,
        scrollY: Math.round(window.scrollY),
        docHeight: Math.round(document.documentElement.scrollHeight),
        viewport: [window.innerWidth, window.innerHeight],
      };
    })()`);
  }
  await settle();
  pointer.modalClosed = await waitFor("document.getElementById('modal').hidden", true);

  // (e) walk into the first reachable node, for real.
  // Prefer a combat: the card half below needs one, and a calm node would silently skip it.
  const combatIndex = await page.evaluate(
    "[...document.querySelectorAll('#mapbox g.node.reachable')]" +
      ".findIndex(function (n) { return n.dataset.kind === 'combat'; })"
  );
  const node = await page.clickSelector(
    "#mapbox g.node.reachable", combatIndex >= 0 ? combatIndex : 0);
  pointer.combatIndex = combatIndex;
  pointer.nodeHits = node.hits;
  await settle();
  pointer.floorAfterNode = await waitFor("ex.rd_run_observe(0)", 1);
  pointer.inFightAfterNode = await page.evaluate("!document.getElementById('handPanel').hidden");
  // Walking into a fight is **two** real clicks: the map node asks the kernel to move, and the
  // node panel's own button starts the combat. A test that stopped after the first click would
  // think the fight never happened and skip the card half silently.
  if (!pointer.inFightAfterNode) {
    const begin = await clickFirst(["#nodePanel [data-panel-action]"]);
    pointer.beginHits = begin.missing ? null : begin.hits;
    pointer.beginSelector = begin.selector || null;
    await settle();
    pointer.inFightAfterNode = await waitFor(
      "!document.getElementById('handPanel').hidden", true);
  }

  // If that was a fight, press a card -- the single most important button in the game -- then
  // 结束回合. The card may want a target, so an armed card is followed by a real click on an enemy.
  pointer.energyBefore = await readCell(8);
  // Which card is first? A failure here used to say only "did not spend energy", which cannot
  // distinguish "the card was 0-cost" from "the click never played anything".
  pointer.cardLabel = await page.evaluate(
    "(document.querySelector('#hand button.card:not([disabled])') || {}).innerText || null");
  pointer.handCount = await page.evaluate(
    "document.querySelectorAll('#hand button.card').length");
  const card = await page.clickSelector("#hand button.card:not([disabled])", 0);
  pointer.cardHits = card.hits;
  pointer.cardMissing = !!card.missing;
  pointer.cardCover = card.cover || null;
  pointer.cardBox = card.box || null;
  await settle();
  pointer.energyAfter = await readCell(8);
  if (pointer.cardHits && pointer.energyAfter === pointer.energyBefore) {
    // ⚠️ This used to be `#enemies .enemy`, which matches **nothing** -- the page's class is
    // `enemy-panel`. It stayed green only because the first playable card happened to be a
    // self-targeted Defend (one click plays it, so the armed branch never ran). §258: the act-1
    // pool gained a second encounter, the first card became a Strike, and the dead selector showed
    // up. `[data-target-slot]` is the page's own "this one is aimable" marker.
    const enemy = await page.clickSelector("#enemies [data-target-slot]", 0);
    pointer.enemyHits = enemy.hits;
    await settle();
    pointer.energyAfterTarget = await readCell(8);
  }
  const end = await page.clickSelector("#endTurn");
  pointer.endTurnHits = end.hits;
  await settle();
  pointer.roundAfterEnd = await readCell(0);
  pointer.cardsAfterEnd = await page.evaluate("document.querySelectorAll('#hand button.card').length");
}
report.pointer = pointer;

// §305 放在**最后**：这一段结束时页面停在战斗中（`pointer` 段需要它停在别处，反过来也一样），
// 而它之后没有别的段落再读页面了 —— 只有 `page.close()`。
report.eye = await evaluate(`(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const panel = () => document.getElementById("nodePanel");
  const text = (el) => el.innerText.replace(/\s+/g, " ").trim();
  const out = {};
  // §305: frozen_eye 是视图，不是状态。
  // 同一份状态两种视图：没有遗物时抽牌堆面板**有序**（看得出有哪些牌、看不出顺序），
  // 有遗物时**等于**内核的顺序。两件事都要读 DOM —— 内核那侧只说明"标志是 0/1"，
  // 而"页面对标志做了什么"只有这里能钉。
  window.RD_DEBUG.startWithSeed(97, 0);
  await sleep(0);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  if (ex.rd_run_pending() === 7) {
    panel().querySelector("[data-panel-action]").click();
    await sleep(0);
    const pick = document.querySelector("#modalBody [data-pick]");
    if (pick) { pick.click(); await sleep(0); }
  }
  const litNodes = [...document.querySelectorAll("#mapbox g.node.reachable")];
  if (litNodes.length) {
    litNodes[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await sleep(40);
  }
  const fightButton = panel().querySelector("[data-panel-action]");
  if (fightButton) { fightButton.click(); await sleep(80); }
  out.eyeInFight = !document.getElementById("handPanel").hidden;

  // 内核的真顺序（页面的 pileId(0, i) 与它同源）。
  const kernelOrder = () => {
    const ids = [];
    for (let index = 0; index < ex.rd_env_pile_len(0); index++) {
      const len = ex.rd_env_pile_card_id_len(0, index);
      const at = ex.rd_env_scratch_buf();
      ex.rd_env_pile_card_id_into(0, index, at);
      ids.push(new TextDecoder().decode(new Uint8Array(ex.memory.buffer, at, len)));
    }
    return ids;
  };
  const shownOrder = () => {
    document.getElementById("drawBtn").onclick();
    const rows = [...document.querySelectorAll("#modalBody .card")]
      .map((el) => el.getAttribute("data-card-id"));
    document.getElementById("modalClose").click();
    return rows;
  };

  out.eyeFlagBefore = ex.rd_env_frozen_eye();
  out.eyeKernelBefore = kernelOrder();
  out.eyeShownBefore = shownOrder();
  // "有序"：按 id 排，与内核顺序**不同**（内核顺序是洗过的）。
  out.eyeSortedBefore = JSON.stringify(out.eyeShownBefore) ===
    JSON.stringify([...out.eyeKernelBefore].sort());
  out.eyeDiffersBefore = JSON.stringify(out.eyeShownBefore) !==
    JSON.stringify(out.eyeKernelBefore);
  out.eyeGranted = window.RD_DEBUG.giveRelic("frozen_eye");
  out.eyeFlagAfter = ex.rd_env_frozen_eye();
  out.eyeKernelAfter = kernelOrder();
  out.eyeShownAfter = shownOrder();
  out.eyeMatchesAfter = JSON.stringify(out.eyeShownAfter) ===
    JSON.stringify(out.eyeKernelAfter);
  out.eyePileUnchanged = JSON.stringify(out.eyeKernelBefore) ===
    JSON.stringify(out.eyeKernelAfter);
  // 这一段单独跑（在 pointer 之后），所以不用担心弹窗影响别人；仍然关掉，免得 §305 自己漏一个出口。
  document.getElementById("modalClose").click();
  await sleep(20);
  out.eyeModalEnd = document.getElementById("modal").hidden;


  return out;
})()`);

await page.close();


want(report.pointer.typed === "777",
  `typing a seed into #seedInput gave ${JSON.stringify(report.pointer.typed)}`);
want(report.pointer.typedHits === true, "the seed field was covered by something");
want(report.pointer.startHits === true,
  `the 开始 button was covered by ${JSON.stringify(report.pointer.startCover)}`);
want(report.pointer.seedAfterStart === 777,
  `a real click on 开始 started seed ${report.pointer.seedAfterStart}`);
want(report.pointer.pendingAfterStart === 6,
  `a fresh run asks something other than the blessing (pending ${report.pointer.pendingAfterStart})`);
want(report.pointer.mapNodesAll > 0, "the map was never rendered");
want(report.pointer.pendingAfterBlessing === 0,
  `the blessing never settled after ${report.pointer.blessingClicks} real click(s) ` +
  `(pending ${report.pointer.pendingAfterBlessing}, first click on ${JSON.stringify(report.pointer.blessingSelector)})`);
want(report.pointer.kinds.length > 0,
  "no node became reachable after the blessing (tried " + JSON.stringify(report.pointer.tried) + ")");
// ⚠️ The falsifiable half: with a modal up, a **real** click on a map node must land on the backdrop.
// A synthetic `dispatchEvent` would have "worked" and hidden exactly the bug this section exists for.
want(report.pointer.modalOpen === true, "the deck modal did not open");
want(report.pointer.mapCovered === true,
  `a map node was clickable through the modal (top element ${JSON.stringify(report.pointer.mapCover)})`);
want(report.pointer.floorWhileModalUp === 0,
  `a real click through the modal moved the run (floor ${report.pointer.floorWhileModalUp})`);
want(report.pointer.reopened === true, "the second open did not take (nothing to close)");
// The backdrop click may have closed the modal (§151's own way out); either way the *run* must not
// have moved, and the deliberate second open is what tests the × button.
want(report.pointer.closeHits === true,
  `the modal's close button was covered by ${JSON.stringify(report.pointer.closeCover)} ` +
  `at ${JSON.stringify(report.pointer.closeBox)} · layout ` +
  `${JSON.stringify(report.pointer.closeLayout || null)}`);
want(report.pointer.modalClosed === true, "a real click on × did not close the modal");
want(report.pointer.nodeHits === true, "the map node was covered after the modal closed");
want(report.pointer.floorAfterNode === 1,
  `a real click on a map node went to floor ${report.pointer.floorAfterNode}`);
if (report.pointer.inFightAfterNode) {
  want(report.pointer.cardMissing === false, "the hand had no enabled card in a fight");
  want(report.pointer.cardHits === true, "the first playable card was covered");
  const spent = report.pointer.energyAfter !== report.pointer.energyBefore ||
    report.pointer.energyAfterTarget !== report.pointer.energyBefore;
  want(spent, `pressing a card did not spend energy (${report.pointer.energyBefore} -> ` +
    `${report.pointer.energyAfter}/${report.pointer.energyAfterTarget}); card ` +
    `${JSON.stringify(report.pointer.cardLabel)} of ${report.pointer.handCount} in hand, ` +
    `hit=${report.pointer.cardHits} cover=${JSON.stringify(report.pointer.cardCover)} ` +
    `box=${JSON.stringify(report.pointer.cardBox)}, enemy click ${report.pointer.enemyHits}, ` +
    `round after end ${report.pointer.roundAfterEnd}`);
  want(report.pointer.endTurnHits === true, "结束回合 was covered");
  want(report.pointer.roundAfterEnd > 0,
    `结束回合 did not leave the round (round ${report.pointer.roundAfterEnd})`);
} else {
  // Not a fight: the card half is inapplicable, and saying so beats a silently skipped assertion.
  console.log("  pointer           " + JSON.stringify(report.pointer));
}

// §203: act-2 / act-3 content, asserted. The three claims are the ones the act-1 slice cannot make:
// a summon **appears** on the panel, a self-removal **disappears** from it, and neither path throws.
const act2 = report.act2 || {};
const act3 = report.act3 || {};
want(act2.build === 0, `act 2: the automaton fight did not build (${act2.build}) ${act2.error || ""}`);
want((act2.opening || []).length === 1,
  `act 2: the orbs are \`Spawn: false\`, so the fight opens with the boss alone; got ${JSON.stringify(act2.opening)}`);
want((act2.after || []).length === 3,
  `act 2: the boss must summon two orbs (panel ${JSON.stringify(act2.after)})`);
want(!act2.threw, `act 2: a step threw: ${act2.threw}`);
// §205: a summoned combatant has to be **named**. It is not in the fight plan (only the boss is), so
// the name has to come from the live combatant -- before this, both orbs painted as "enemy #1/#2"
// and nothing in the suite noticed, because "3 entries" was the whole assertion.
// §345：查 **id**（`data-enemy-id`），不查显示名的第一个词 —— 显示名由显示层的映射表决定，
// 判据关心的是"这一格确实有身份"（原来是按面板文本的第一个词，页面一印显示名就分不清了）。
const summonedIds = act2.afterIds || [];
want(summonedIds.filter((id) => id === "bronze_orb").length === 2,
  `act 2: both summoned orbs must carry the id bronze_orb; got ${JSON.stringify(summonedIds)}`);
want(!summonedIds.some((id) => id === "" || id === null),
  `act 2: a summoned enemy still has no id: ${JSON.stringify(summonedIds)}`);
want(act3.build === 0, `act 3: the reptomancer fight did not build (${act3.build}) ${act3.error || ""}`);
want((act3.opening || []).length === 3,
  `act 3: boss + two preset daggers; got ${JSON.stringify(act3.opening)}`);
want(typeof act3.leftCount === "number" && act3.leftCount < 3,
  `act 3: a dagger must explode and leave the panel (before ${act3.openingCount}, ` +
  `after ${act3.leftCount}; done ${act3.done} result ${act3.result} hp ${act3.hp} ` +
  `inFight ${act3.inFight} msg ${JSON.stringify(act3.msg)})`);
want(!act3.errorEnd, `act 3: a step threw: ${act3.errorEnd}`);

// §287：`Wing Statue` 的 `[Destroy]` —— 起始牌组的单次最高是 8 ⇒ 它必须**不**被画出来，
// 另外两个（`[Pray]` / `[Leave]`）必须照着画。
want(report.wingOpened === 0, `§287: \`wing_statue\` did not open (${report.wingOpened})`);
want(report.wingOptions === 3, `§287: expected 3 options, got ${report.wingOptions}`);
want(JSON.stringify(report.wingAvailable) === JSON.stringify([1, 0, 1]),
  `§287: availability must be [1,0,1] on the starting deck, got ` +
  `${JSON.stringify(report.wingAvailable)}`);
want(report.wingButtons.length === 2,
  `§287: 3 options with 1 locked must draw **2** buttons, got ` +
  `${report.wingButtons.length} ${JSON.stringify(report.wingButtons)}`);
want(!report.wingDestroyDrawn,
  `§287: \`[Destroy]\` is drawn although the deck's best hit is 8: ` +
  `${JSON.stringify(report.wingButtons)}`);
want(report.wingRefused === -2,
  `§287: clicking the hidden \`[Destroy]\` must be refused with -2, got ${report.wingRefused}`);
want(report.wingPendingAfter === 5,
  `§287: a refused click must leave the event open, pending ${report.wingPendingAfter}`);

// §293：加牌问句 —— 面板真的出现、行带内核槽号、点了真的加牌、+2 上限只在有遗物时画。
want(report.addGranted === 0, `§293: giveRelic(orrery) failed (${report.addGranted})`);
want(report.addOwed === 5, `§293: orrery must owe 5 cards, got ${report.addOwed}`);
want(report.addOffer >= 3, `§293: expected at least 3 offered cards, got ${report.addOffer}`);
want(report.addRows.length >= 4,
  `§293: the panel must draw one row per card plus the skip button, got ` +
  `${report.addRows.length} ${JSON.stringify(report.addRows)}`);
want(/挑一张牌加入牌组/.test(report.addHeading),
  `§293: the panel heading is ${JSON.stringify(report.addHeading)}`);
want(report.addDeckGrew === 1,
  `§293: clicking a row must add exactly one card, got ${report.addDeckGrew}`);
want(report.addOwedAfter === 4,
  `§293: the debt must go 5 -> 4, got ${report.addOwedAfter}`);
want(!report.addButtonsNoBowl.some((label) => /上限/.test(label)),
  `§293: without singing_bowl the +2 上限 button must not be drawn, got ` +
  `${JSON.stringify(report.addButtonsNoBowl)}`);
want(report.addButtonsWithBowl.some((label) => /上限/.test(label)),
  `§293: with singing_bowl the +2 上限 button must be drawn, got ` +
  `${JSON.stringify(report.addButtonsWithBowl)}`);
want(report.addMaxHpGrew === 2,
  `§293: the +2 上限 button must raise max HP by 2, got ${report.addMaxHpGrew}`);
want(report.addOwedAfterBowl === 4,
  `§293: and it spends one pick (5 -> 4), got ${report.addOwedAfterBowl}`);

// §279：条件选项的 DOM 半 —— 4 个选项、1 个锁着 ⇒ 3 个按钮，且锁着的那个**不在** DOM 里。
want(report.condOpened === 0, `§279: \`forgotten_altar\` did not open (${report.condOpened})`);
want(report.condPending === 5, `§279: the event screen is not open (pending ${report.condPending})`);
want(report.condOptions === 4, `§279: expected 4 options, got ${report.condOptions}`);
want(JSON.stringify(report.condAvailable) === JSON.stringify([0, 1, 1, 1]),
  `§279: availability must be [0,1,1,1] (locked first), got ${JSON.stringify(report.condAvailable)}`);
want(report.condButtons.length === 3,
  `§279: 4 options with 1 locked must draw **3** buttons, got ` +
  `${report.condButtons.length} ${JSON.stringify(report.condButtons)}`);
want(!report.condLockedDrawn,
  `§279: the locked option is drawn as a button: ${JSON.stringify(report.condButtons)}`);
want(report.condRefused === -2,
  `§279: clicking a locked option must be refused with -2, got ${report.condRefused}`);
want(report.condPendingAfterRefusal === 5,
  `§279: a refused click must leave the event open, pending ${report.condPendingAfterRefusal}`);


want(report.eye.eyeInFight === true, "§305: the fight never started, so the draw pile was never shown");
want(report.eye.eyeFlagBefore === 0 && report.eye.eyeFlagAfter === 1,
  `§305: frozen_eye flag went ${report.eye.eyeFlagBefore} -> ${report.eye.eyeFlagAfter}`);
want(report.eye.eyeDiffersBefore === true,
  "§305: without the relic the panel showed the kernel's draw order (it must NOT)");
want(report.eye.eyeSortedBefore === true,
  "§305: without the relic the panel is not the sorted view");
want(report.eye.eyeMatchesAfter === true,
  "§305: with the relic the panel must equal the kernel's draw order");
want(report.eye.eyeModalEnd === true, `§305: the modal was left open (${report.eye.eyeModalEnd}), which covers #seedInput`);
want(report.eye.eyePileUnchanged === true,
  "§305: granting the relic reordered the draw pile itself (it is a view, not state)");
want(report.eye.eyeShownAfter.length === report.eye.eyeKernelAfter.length,
  `§305: the panel showed ${report.eye.eyeShownAfter.length} of ` +
  `${report.eye.eyeKernelAfter.length} card(s)`);

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
console.log("  pointer           seed " + JSON.stringify(report.pointer.typed) + " · 开始 " +
  report.pointer.startHits + " · modal swallowed the map click " + report.pointer.mapCovered +
  " (" + report.pointer.mapCover + ") · floor " + report.pointer.floorAfterNode +
  " · card " + report.pointer.cardHits + " · energy " + report.pointer.energyBefore + " -> " +
  report.pointer.energyAfter + "/" + report.pointer.energyAfterTarget +
  " · round " + report.pointer.roundAfterEnd);
console.log("  script            " + report.scriptHead + "… head, " + report.scriptSteps +
  " step(s) · archive head " + report.scriptArchiveHead + " · verified " + report.scriptChecked +
  " · tampered step " + report.scriptTamperDiverged + " (checked " + report.scriptTamperChecked + ")");
console.log("  content           " + report.contentPin + " (head " + report.scriptPin +
  ") · foreign build refused with " + report.contentMismatchChecked + " step(s) applied");
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
console.log("  act 2 (orbs)      " + JSON.stringify(report.act2 && report.act2.after) +
  " · opening " + JSON.stringify(report.act2 && report.act2.opening));
console.log("  §279 locked       " + report.condOptions + " option(s) · available " +
  JSON.stringify(report.condAvailable) + " · drawn " + report.condButtons.length +
  " · locked drawn " + report.condLockedDrawn + " · refused " + report.condRefused);
console.log("  §287 wing statue  " + report.wingOptions + " option(s) · available " +
  JSON.stringify(report.wingAvailable) + " · drawn " + report.wingButtons.length +
  " · [Destroy] drawn " + report.wingDestroyDrawn + " · refused " + report.wingRefused);
console.log("  act 3 (daggers)   " + JSON.stringify({
  opening: report.act3 && report.act3.openingCount, left: report.act3 && report.act3.leftCount,
  done: report.act3 && report.act3.done, result: report.act3 && report.act3.result,
  hp: report.act3 && report.act3.hp, inFight: report.act3 && report.act3.inFight,
  msg: report.act3 && report.act3.msg,
}));
console.log("  §293 add cards    owed " + report.addOwed + " -> " + report.addOwedAfter +
  " · offer " + report.addOffer + " · rows " + report.addRows.length +
  " · deck +" + report.addDeckGrew + " · bowl +" + report.addMaxHpGrew + " max HP");
console.log("  §305 frozen eye  flag " + report.eye.eyeFlagBefore + " -> " +
  report.eye.eyeFlagAfter + " · sorted " + report.eye.eyeSortedBefore +
  " · differs " + report.eye.eyeDiffersBefore + " · matches after " +
  report.eye.eyeMatchesAfter + " · pile unchanged " + report.eye.eyePileUnchanged +
  " · shown " + report.eye.eyeShownAfter.length + "/" + report.eye.eyeKernelAfter.length);
console.log("BROWSER_TEST PASS");
