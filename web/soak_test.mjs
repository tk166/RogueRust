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

  const out = {
    seeds: [], errors: [], dead: [], refused: [], stuck: [], invariant: [], screens: [],
    // §155 coverage: facts about the *run*, read off the ABI, so "did the soak reach this feature"
    // is a number and not a hope.
    eliteFights: 0, bossFights: 0, relicsGained: 0, relicFromElite: 0, upgradedSeen: false,
    arrivals: {}, smithTries: 0, eliteWins: 0, hopsSeen: 0, hopsTaken: 0, plannedHop: -1,
    // §161.3 coverage: the card-choice picker. choiceTicked counts the answers that picked a
    // **non-empty** selection, which is the half a "just press confirm" walk never reaches.
    choices: 0, choiceTicked: 0, choiceEmpty: 0,
  };
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

  // ---- §155: read the run through the ABI (not the DOM) -----------------------------------------
  const deckIds = () => {
    const ids = [];
    const count = ex.rd_run_deck_count();
    for (let index = 0; index < count; index++) {
      const length = ex.rd_run_deck_id_len(index);
      if (length <= 0) continue;
      const ptr = ex.rd_env_scratch_buf();
      ex.rd_run_deck_id_into(index, ptr);
      ids.push(new TextDecoder().decode(new Uint8Array(ex.memory.buffer, ptr, length).slice()));
    }
    return ids;
  };
  const relicCount = () => ex.rd_run_observe(6);

  // One observation cell, out of the fight vector (ui_render.js H / OFF_ENEMY).
  const cell = (index) => {
    const buf = ex.rd_env_scratch_buf();
    ex.rd_env_observe_into(buf);
    return new Int32Array(ex.memory.buffer, buf, ex.rd_env_observe_len())[index];
  };

  // How much damage the enemies are telegraphing this turn (OFF_ENEMY + slot*8 + 6).
  const incomingDamage = () => {
    let total = 0;
    const slots = Math.min(cell(11), 6);
    for (let slot = 0; slot < slots; slot++) {
      const damage = cell(24 + slot * 8 + 6);
      if (damage > 0) total += damage;
    }
    return total;
  };

  // ---- §155: route to the feature this run has not covered yet --------------------------------
  // RD_DEBUG.view() is the map the page drew (describeMap): nodes[].out are the exits and
  // cursor.node is where the player stands, so the next hop is a BFS away.
  const nextHopTo = (wanted) => {
    const view = RD_DEBUG.view();
    if (!view || !view.nodes || !wanted) return -1;
    // Before the first step the cursor is -1 ("还没出发"), so the search starts from **every** node
    // of the first row: the plan is "which of these leads to the thing I want".
    const start = view.cursor.node;
    const seeds = start >= 0
      ? [start]
      : view.nodes.reduce((out2, node) => {
          const lowest = Math.min(...view.nodes.map((n) => n.row));
          if (node.row === lowest) out2.push(node.id);
          return out2;
        }, []);
    if (!seeds.length) return -1;
    const previous = new Map(seeds.map((id) => [id, -1]));
    const queue = [...seeds];
    let goal = -1;
    while (queue.length) {
      const at = queue.shift();
      if (at !== start && wanted(view.nodes[at])) {
        goal = at;
        break;
      }
      for (const next of (view.nodes[at] && view.nodes[at].out) || []) {
        if (!previous.has(next)) {
          previous.set(next, at);
          queue.push(next);
        }
      }
    }
    if (goal < 0) return -1;
    let step = goal;
    while (previous.get(step) !== -1 && previous.get(step) !== start) step = previous.get(step);
    return step;
  };

  // Which kind of node this run still needs. null = nothing in particular, walk at random.
  const uncoveredTarget = () => {
    const hp = ex.rd_run_observe(2);
    const hpMax = Math.max(1, ex.rd_run_observe(3));
    const healthy = hp * 10 >= hpMax * 6;
    // The elite first, whatever the health: the point is to **reach** the relic reward once, and a
    // run that dies to it still counted the fight. (Gating on health meant three seeds never met one.)
    if (out.eliteFights === 0) return (node) => node.kindName === "elite";
    // Then the campfire -- the only place a card can be upgraded.
    if (!out.upgradedSeen) return (node) => node.kindName === "rest";
    return null;
  };

  // Pick a card the way a careful beginner would: block what hurts, then hit back.
  const chooseFightAction = () => {
    const cards = [...document.querySelectorAll("#hand button.card:not([disabled])")];
    const hp = cell(4);
    const hpMax = Math.max(1, cell(5));
    const block = cell(6);
    const hurt = hp * 10 < hpMax * 6 || incomingDamage() > block;
    const blocks = cards.filter((card) => /block/i.test(card.textContent));
    const hits = cards.filter((card) => /damage/i.test(card.textContent));
    const order = hurt ? [blocks, hits, cards] : [hits, blocks, cards];
    for (const group of order) {
      if (group.length) return group[Math.floor(random() * group.length)];
    }
    const end = byId("endTurn");
    return end && !end.disabled ? end : null;
  };

  // A reward screen is not "pick one thing": a player takes everything offered, and that is the only
  // way the **relic** row is ever clicked (it is appended after the card rows).
  const takeEverythingOffered = async () => {
    for (let guard = 0; guard < 6; guard++) {
      const buttons = [...panel().querySelectorAll(".shop-item [data-panel-action]")];
      const take = buttons.find((button) => text(button).startsWith("拿"));
      if (!take) return;
      const before = text(panel());
      take.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await sleep(0);
      await sleep(0);
      if (text(panel()) === before) return;
    }
  };
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
      // §161.3: a tick is a real UI change, and it lives nowhere else -- without this the walk
      // reports every tick as a **dead button** (§150's shape) because the page around it did not
      // move. innerHTML, not length: "确认 1 张" and "确认 2 张" are the same length.
      byId("modalBody").innerHTML,
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
      // §161.3: a pending card choice is the **only** way forward -- the kernel's action table is
      // empty until it is answered, and closeModal refuses to close it. So it owns the candidate
      // list: tick (sometimes) and confirm. Offering [data-close] here would be a button that
      // provably does nothing, which is the exact shape this gate exists to catch.
      if (ex.rd_env_choice_pending() === 1) {
        out.choices += 1;
        const options = [...document.querySelectorAll("#modalBody [data-choice]")];
        const unticked = options.filter((el) => el.dataset.ticked !== "1");
        const confirm = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
        // Six in ten clicks tick: "answer with nothing" is legal for both potions and deserves
        // coverage too, but a walk that always answers "nothing" never proves the picker works.
        if (unticked.length && random() < 0.6) {
          const el = pick(unticked);
          out.choiceTicked += 1;
          groups[0].push({ kind: "choice-tick", el, label: text(el) });
        }
        if (confirm) {
          // "Answer with nothing" is a real choice (both potions say "any number"), so it is
          // counted separately from "ticked something": a picker whose ticks never reach the
          // kernel and one nobody ever ticked look identical from the outside otherwise.
          if (!options.some((el) => el.dataset.ticked === "1")) out.choiceEmpty += 1;
          groups[0].push({ kind: "choice-confirm", el, label: text(confirm) });
        }
        return groups;
      }
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
        // §173: the potion's own label, so a stuck state names the bottle that caused it.
        groups[2].push({ kind: "use-potion", el,
          label: String(el.dataset.usePotion) + " " + text(el).slice(0, 24) });
      }
    } else {
      for (const el of document.querySelectorAll("#nodePanel [data-panel-action]")) {
        if (el.disabled) continue;
        groups[1].push({ kind: "panel", el, label: text(el) });
      }
      // §155: an elite pays a relic, so a player takes it. Sorting is the whole policy -- the
      // "arrival takes the first" rule then picks the elite without a second branch.
      const nodes = [...document.querySelectorAll("#mapbox g.node.reachable")];
      // Diagnostic: does the **map** hold an elite at all (as opposed to the preference not firing)?
      if (document.querySelector("#mapbox g.node[data-kind=elite]")) out.eliteOnMap = true;
      // A player takes an elite when healthy and rests when hurt -- and the soak has to do both:
      // taking every elite from floor 2 killed it at ~45 clicks, and picking nodes at random walked
      // past every elite for three seeds. Scores come from data-kind (a fact), not from glyphs.
      const healthNow = ex.rd_run_observe(2);
      const healthMax = Math.max(1, ex.rd_run_observe(3));
      const healthy = healthNow * 10 >= healthMax * 6;
      const SCORE_HEALTHY = { elite: 6, treasure: 5, shop: 4, rest: 3, unknown: 2, combat: 1 };
      const SCORE_HURT = { rest: 6, shop: 5, treasure: 4, unknown: 3, combat: 2, elite: 0 };
      const score = (el) => {
        const table = healthy ? SCORE_HEALTHY : SCORE_HURT;
        const kind = (el.dataset && el.dataset.kind) || "combat";
        return table[kind] ?? 1;
      };
      nodes.sort((a, b) => score(b) - score(a));
      // §155: the planned hop wins over the score, so a feature that has not been covered yet is
      // actually reached instead of merely being likely.
      const hop = nextHopTo(uncoveredTarget());
      out.plannedHop = hop;
      if (hop >= 0) out.hopsSeen = (out.hopsSeen || 0) + 1;
      if (hop >= 0) {
        nodes.sort((a, b) =>
          (String(b.dataset.node) === String(hop) ? 1 : 0) -
          (String(a.dataset.node) === String(hop) ? 1 : 0));
      }
      for (const el of nodes) {
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

  out.lastRelicsWatch = relicCount();
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
      for (const screenTitle of SCREENS) {
        if (panelNow.includes(screenTitle) && !out.screens.includes(screenTitle)) out.screens.push(screenTitle);
      }
      // The current screen (for the arrival rotation): the longest title that the panel mentions.
      const screen = SCREENS.filter((title) => panelNow.includes(title)).pop() || panelNow.slice(0, 8);
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
            // The last few log lines are the only record of *how* it got here.
            log: Array.from(document.querySelectorAll("#log div")).slice(-8)
              .map((el) => text(el).slice(0, 90)),
            mode: byId("handPanel").hidden ? "run" : "fight",
            lastClicks: (window.__soakClicks || []).slice(-6),
          });
          break;
        }
        await sleep(5);
        continue;
      }
      idlePolls = 0;
      // §155: a reward screen is taken in full before moving on.
      // §155: at a campfire the feature is 打铁 (upgrade), not 休息 -- the rotation would pick
      // 休息 on the first visit and the upgrade would never happen in a three-seed run.
      if (panelNow.includes("篝火") && !out.upgradedSeen && out.smithTries < 3 &&
          !byId("modal").hidden === false) {
        const smith = [...panel().querySelectorAll("[data-panel-action]")]
          .find((button) => text(button).includes("打铁"));
        if (smith) {
          out.smithTries += 1;
          smith.dispatchEvent(new MouseEvent("click", { bubbles: true }));
          await sleep(0);
          // the deck picker opens; the modal branch of candidates() handles it next tick
          preferPrimary = false;
          actions += 1;
          continue;
        }
      }
      if (preferPrimary && screen.includes("战斗奖励")) {
        await takeEverythingOffered();
        preferPrimary = false;
        actions += 1;
        continue;
      }
      // §155: the Nth arrival at a screen clicks its Nth action. Always clicking the first one meant
      // a campfire only ever rested and never forged (the upgrade), and the smith is exactly the
      // feature §154 was about.
      const arrivals = out.arrivals[screen] || 0;
      // A node group is already sorted elite-first, so taking its head **is** the elite preference
      // (picking at random from it made the sort pointless -- that is why three seeds never met one).
      // A **soft** elite bias: take the (sorted) head half the time when it is a node, otherwise
      // pick at random. Deterministically taking the head made the walk die at ~45 clicks.
      // §155: in a fight the choice is the beginner heuristic, not a dice roll (random play loses
      // to three gremlins at floor 1 and then nothing later in the act gets covered).
      const inFightNow = !byId("handPanel").hidden;
      // §155: the **planned** hop is taken every time (it is the route to an uncovered feature);
      // any other node is still a coin toss. The run survives the detour because the fight policy
      // blocks when it hurts.
      const headIsNode = !inFightNow && list[0] && list[0].kind === "node";
      const planned = headIsNode && out.plannedHop >= 0 &&
        String(list[0].el.dataset.node) === String(out.plannedHop);
      if (inFightNow) {
        const picked = chooseFightAction();
        if (picked) {
          const beforeFight = fingerprint();
          picked.dispatchEvent(new MouseEvent("click", { bubbles: true }));
          await sleep(0);
          // A card that arms the enemy picker needs a target click to resolve.
          const target = document.querySelector("#enemies [data-target-slot]");
          if (target) {
            target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
            await sleep(0);
          }
          await sleep(0);
          actions += 1;
          if (fingerprint() === beforeFight) {
            out.dead.push({
              runSeed, actions, kind: "fight-choice",
              label: text(picked).slice(0, 40),
            });
          }
          invariants("seed " + runSeed + " action " + actions);
          if (ex.rd_run_observe(2) <= 0) break;
          continue;
        }
      }
      if (planned) out.hopsTaken = (out.hopsTaken || 0) + 1;\n      const choice = preferPrimary
        ? list[Math.min(arrivals, list.length - 1)]
        : planned || (headIsNode && random() < 0.5)
          ? list[0]
          : pick(list);
      if (preferPrimary) out.arrivals[screen] = arrivals + 1;
      preferPrimary = false;
      if (choice.kind === "node") preferPrimary = true;
      choice.el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      // Shift+click opens a modal sometimes: it is a real control, and the modal must be closable.
      if (choice.kind === "card" && random() < 0.1) openModal();
      await sleep(0);
      await sleep(0);
      const after = fingerprint();
      actions += 1;
      // §173: the last few clicks are the only witness to *how* a stuck state was reached.
      (window.__soakClicks = window.__soakClicks || []).push(
        (choice.kind || "?") + ":" + String(choice.label || (choice.el && text(choice.el)) || "").slice(0, 30));
      if (window.__soakClicks.length > 12) window.__soakClicks.shift();
      const inFight = !byId("handPanel").hidden;
      if (inFight && !wasFight) fights += 1;
      wasFight = inFight;
      const floor = ex.rd_run_observe(0);
      // §155 coverage, read after the click: which kinds of fight were begun, whether the relic count
      // moved (and whether it moved right after an elite), and whether the deck now holds a `+` card.
      if (inFight && !wasFight) {
        const kind = ex.rd_run_node_kind();
        if (kind === 2) {
          out.eliteFights += 1;
          out.awaitingEliteReward = true;
        }
        if (kind === 7) out.bossFights += 1;
      }
      // An elite that was **won**: the reward screen followed it.
      if (out.awaitingEliteReward && !inFight && ex.rd_run_pending() === 4) {
        out.eliteWins = (out.eliteWins || 0) + 1;
      }
      const relicsNow = relicCount();
      if (relicsNow > (out.lastRelicsWatch ?? relicsNow)) {
        const gained = relicsNow - (out.lastRelicsWatch ?? relicsNow);
        out.relicsGained += gained;
        if (out.awaitingEliteReward) out.relicFromElite += gained;
      }
      out.lastRelicsWatch = relicsNow;
      if (!out.upgradedSeen && deckIds().some((id) => id.includes("+"))) out.upgradedSeen = true;
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
      endHp: ex.rd_run_observe(2), endPending: ex.rd_run_pending(),
      hopsSeen: out.hopsSeen, hopsTaken: out.hopsTaken,
      endWhy: ex.rd_run_observe(2) <= 0 ? "dead" : ex.rd_run_boss_beaten() === 1 ? "boss" : "budget",
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
// §155 coverage: the small features have to be **reached**, not merely survive a random walk.
// **Not** `eliteFights >= 1`: the random walk dies around floor 6-8 with the beginner policy, and the
// act-1 elites sit deeper than that. Requiring one meant the gate was red for a reason that has
// nothing to do with a bug -- the honest shape is the implication below, plus the deterministic
// coverage of the same rule at the two layers that own it (`the_elite_relic_reward_round_trips_…`,
// `an_elite_pays_a_relic_and_a_normal_fight_does_not`, and `ui_test`'s reward-row check).
want(report.relicsGained >= 1, "the walk never gained a relic (chest or elite reward)");
// Conditional on the **situation happening**, not on luck: whenever an elite was won, its reward must
// have paid a relic (§155); whenever a campfire was reached, its 打铁 must have been clicked (§154).
want(
  !report.eliteWins || report.relicFromElite >= 1,
  `an elite was won (${report.eliteWins}) but no relic came out of it`
);
want(
  !report.screens.includes("篝火") || report.upgradedSeen,
  "a campfire was reached but no card was ever upgraded"
);

await page.close();

for (const seed of report.seeds) {
  console.log(
    `  hops ${seed.hopsSeen}/${seed.hopsTaken} · seed ${String(seed.runSeed).padStart(3)}  ${String(seed.actions).padStart(4)} clicks · ` +
      `${seed.fights} fights · floor ${seed.maxFloor} · act ${seed.maxAct} · ` +
      `${seed.potions} potions · hp ${seed.endHp} · ${seed.endWhy} · pending ${seed.endPending} · ${seed.ms} ms`
  );
}
console.log("  screens           " + report.screens.join(" / "));
console.log(
  "  choices           " + (report.choices || 0) + " card question(s) · " +
    (report.choiceTicked || 0) + " tick(s) · " + (report.choiceEmpty || 0) + " answered with nothing"
);
console.log("  refusals          " + report.refused.length);
console.log(
  "  coverage          " + (report.eliteOnMap ? "map has elites · " : "map HAS NO ELITE · ") + report.eliteFights + " elite(s) · " + report.bossFights + " boss(es) · " +
    report.relicsGained + " relic(s) (" + report.relicFromElite + " from elites) · elite wins " +
    (report.eliteWins || 0) + " · upgrade " +
    (report.upgradedSeen ? "yes" : "NO")
);

if (problems.length) {
  for (const problem of problems) console.error("  - " + problem);
  fail(`${problems.length} assertion(s) failed`);
}
console.log("SOAK_TEST PASS");
