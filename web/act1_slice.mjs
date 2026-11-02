// A **vertical slice of one act**: five deterministic browser scenarios, one per node kind.
//
// Why this exists (REVIEW §六 step 3): `soak_test.mjs` clicks around *randomly* and proves "nothing
// is a dead button" -- it does **not** prove that a shop can be shopped in, that an elite's relic
// arrives, or that beating the boss actually ends the act. Those are the five screens a milestone
// has to be able to name, and each one gets a **planned route** here: the run starts at floor 1 on a
// pinned seed and the driver walks a route it computed from the map, not the first node that lights
// up.
//
// What "from the start of the run to 幕末" means per scenario, stated so nobody over-reads it:
//   * every scenario starts at floor 1 (blessing → map) and **walks** to its node;
//   * `boss` goes on to the **end of the act** (boss beaten → act 2, new map, healed to full);
//   * the other four stop once their node is settled, because re-walking an act five times buys
//     runtime, not information. The union of the five covers the act's whole screen set.
//
// §161.7 is used as an **anchor**: the boss scenario drinks an Attack Potion mid-fight, answers the
// card-choice question it opens, and plays the card it got. That is the "degrees of freedom" half --
// a slice that can only walk a fixed script would not be able to do it, and the two newest
// mechanisms (offered candidates + per-copy price) would go unexercised end to end.

import { openPage } from "./cdp.mjs";

// `--only shop,rest` runs a subset (for diagnosing one scenario without paying for five).
const ONLY = process.argv.includes("--only")
  ? process.argv[process.argv.indexOf("--only") + 1].split(",")
  : null;
const wanted = (name) => !ONLY || ONLY.includes(name);

const page = await openPage({
  query: "slice&debug",
  gate: "ACT1_SLICE",
  waitFor: "Boolean(window.RD_DEBUG)",
});

const report = await page.evaluate(`(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const byId = (id) => document.getElementById(id);
  const panel = () => byId("nodePanel");
  const text = (el) => {
    if (!el) return "";
    const raw = typeof el.innerText === "string" ? el.innerText : el.textContent;
    return (raw || "").replace(/\\s+/g, " ").trim();
  };
  const click = async (el) => {
    if (!el) return false;
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await sleep(0);
    await sleep(0);
    return true;
  };
  const inFight = () => !byId("handPanel").hidden;
  const cell = (index) => {
    const buf = ex.rd_env_scratch_buf();
    ex.rd_env_observe_into(buf);
    return new Int32Array(ex.memory.buffer, buf, ex.rd_env_observe_len())[index];
  };
  const buttons = () => [...panel().querySelectorAll("[data-panel-action]:not([disabled])")];
  const findButton = (re) => buttons().find((b) => re.test(text(b)));

  // ---- answering a card-choice question (the kernel's action table is empty until it is) ------
  async function answerChoice() {
    if (ex.rd_env_choice_pending() !== 1) return false;
    const option = document.querySelector("#modalBody [data-choice]");
    if (option) await click(option);
    const confirm = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
    if (confirm && !confirm.disabled) {
      confirm.onclick ? confirm.onclick() : await click(confirm);
      await sleep(0);
    }
    return true;
  }

  /// Drink potion index and **finish the interaction it starts**.
  ///
  /// A damage/status potion does not resolve on the click: the page arms the enemy picker
  /// (potionPending) and waits for a target, during which every card click is ignored. The first
  /// version of this driver never noticed, so a single mid-fight potion froze the whole walk in
  /// "potion-armed" mode -- 20 identical frames with no error anywhere.
  async function drinkPotion(index) {
    const button = document.querySelector('[data-use-potion="' + index + '"]');
    if (!button) return false;
    button.onclick ? button.onclick() : await click(button);
    await sleep(0);
    if (document.getElementById("enemies").classList.contains("potion-armed")) {
      const target = document.querySelector("#enemies [data-enemy-panel]") ||
        document.querySelector("#enemies [data-target-slot]");
      if (target) await click(target);
      await sleep(0);
    }
    await answerChoice();
    return true;
  }

  // ---- a fight policy that is better than "first card" ---------------------------------------
  // It has to be able to **win an act**, because the boss scenario walks 15 floors: "attacks first,
  // block never" lost the boss at 50/95 HP and the whole slice then reported a driver gap. So:
  // block when the incoming damage would get through, otherwise hit, and drink when hurt.
  const incoming = () => {
    let total = 0;
    for (let slot = 0; slot < 6; slot++) {
      const base = OFF_ENEMY + slot * 8;
      if (cell(base) === 1) total += Math.max(0, cell(base + 6));
    }
    return total;
  };
  async function fight(budget) {
    let guard = 0;
    while (inFight() && guard++ < budget) {
      // The page has **two** "pick an enemy" flows and they are not interchangeable:
      //   * a potion waiting for a target  -> potion-armed on #enemies, click [data-enemy-panel];
      //   * a card waiting for a target    -> the aimable panels carry [data-target-slot].
      // data-enemy-panel exists on **every** panel, data-target-slot only where the armed card
      // can reach. The click handler looks for [data-target-slot] whenever a card is armed and
      // returns early if the panel lacks it -- so clicking [data-enemy-panel] first leaves the card
      // armed and every later card click ignored. That was the 25-minute stall at floor 12.
      if (byId("enemies").classList.contains("potion-armed")) {
        const target = document.querySelector("#enemies [data-enemy-panel]");
        if (target) {
          await click(target);
          await answerChoice();
          continue;
        }
      }
      // A card is armed iff some panel is marked aimable: finish that play before choosing another.
      const armed = document.querySelector("#enemies [data-target-slot]");
      if (armed) {
        await click(armed);
        await answerChoice();
        continue;
      }
      if (await answerChoice()) continue;
      if (!byId("modal").hidden) {
        const closer = byId("modalClose");
        if (closer) await click(closer);
        else byId("modal").hidden = true;
        continue;
      }
      // Potions at half health (and always on the first turn of a boss fight: a free card is worth
      // more early than the HP it saves later).
      if (cell(4) * 2 < cell(5)) {
        const potion = document.querySelector("[data-use-potion]");
        if (potion) {
          await drinkPotion(potion.dataset.usePotion);
          continue;
        }
      }
      const cards = [...document.querySelectorAll("#hand button.card:not([disabled])")];
      if (!cards.length) {
        await click(byId("endTurn"));
        continue;
      }
      const attack = cards.find((c) => /damage/i.test(text(c)));
      const block = cards.find((c) => /block/i.test(text(c)));
      // Blocking whenever damage "gets through" made fights *longer* than they were short: a 5-block
      // card against 27 incoming still lets 22 through, and every extra turn is another 27. What a
      // player does is kill faster and block only when the hit would be lethal.
      const lethal = incoming() >= cell(4);
      const pick = lethal && block ? block : (attack || block || cards[0]);
      await click(pick);
      // …and aim at the enemy that dies soonest, so the incoming total drops early.
      const weakest = (() => {
        let best = -1;
        let bestHp = Infinity;
        for (let slot = 0; slot < 6; slot++) {
          const base = OFF_ENEMY + slot * 8;
          if (cell(base) !== 1) continue;
          const hp = cell(base + 1);
          if (hp < bestHp) {
            bestHp = hp;
            best = slot;
          }
        }
        return best;
      })();
      const aimAt = weakest >= 0
        ? document.querySelector('#enemies [data-target-slot="' + weakest + '"]')
        : null;
      if (aimAt) await click(aimAt);
      // The card may have armed a target picker; the next loop iteration finishes it (see above).
      // Clicking anything else here is what used to strand the card.
    }
    return !inFight();
  }

  // ---- settling whatever panel is up ---------------------------------------------------------
  // Order matters and is the one a player uses: take what a screen offers, then leave.
  async function settle(budget) {
    let stalls = 0;
    let lastState = "";
    for (let guard = 0; guard < budget; guard++) {
      const nowState = text(panel()) + "|" + ex.rd_run_pending() + "|" + (inFight() ? "F" : "-");
      if (nowState === lastState) {
        stalls += 1;
        // Two identical frames in a row means the last click changed nothing: a refused action or a
        // button this driver does not understand. Burning the rest of the budget on it is how the
        // first version of this gate took 25 minutes and told nobody why.
        if (stalls >= 2) return false;
      } else {
        stalls = 0;
        lastState = nowState;
      }
      if (inFight()) {
        await fight(budget);
        continue;
      }
      if (await answerChoice()) continue;
      // A deck picker is a **modal**, not a panel: an event that upgrades/removes a card puts its
      // options in #modalBody[data-pick]. Missing this left the node unsettled and every later map
      // click refused -- which looked exactly like "the route planner is wrong".
      if (!byId("modal").hidden) {
        const pick = document.querySelector("#modalBody [data-pick]");
        if (pick) {
          await click(pick);
          continue;
        }
        const closer = document.querySelector("#modal [data-close]");
        if (closer) {
          await click(closer);
          continue;
        }
        if (ex.rd_env_choice_pending() !== 1) byId("modal").hidden = true;
        continue;
      }
      // **Stop at the boss.** Settling it here would fight and, if it lost, restart the run -- which
      // is exactly what the first version did: the walk reached floor 15, the boss was fought inside
      // the settler, the hero died at 21 HP, the run-over panel appeared, and the fallback below
      // clicked 再打一局 and started a *new* run. Three identical walks appeared in the trail.
      if (ex.rd_run_node_kind() === 7) return true;
      // A combat node presents 开始战斗; the fight does not start by itself. Without this the
      // settle loop stalled on every combat/elite and the walk "could not reach the last row".
      const begin = findButton(/^开始战斗/);
      if (begin) {
        await click(begin);
        continue;
      }
      const takeCard = findButton(/^拿这张/);
      if (takeCard) {
        await click(takeCard);
        continue;
      }
      const takePotion = findButton(/^拿起/);
      if (takePotion) {
        await click(takePotion);
        continue;
      }
      const skip = findButton(/^跳过/);
      if (skip) {
        await click(skip);
        // Terminal: the reward screen is gone and the node is settled.
        return true;
      }
      const open = findButton(/^开箱/);
      if (open) {
        await click(open);
        // The chest opens into a reward-ish panel; keep going so the relic is actually taken.
        continue;
      }
      const rest = findButton(/^休息/);
      if (rest) {
        await click(rest);
        // Terminal: a campfire is **one** action (Rest or Smith), then the node is settled. The
        // first version kept clicking, hit a leave that is refused once nothing is pending, and the
        // stall guard then reported "could not settle" -- which looked like a broken route.
        return true;
      }
      const leave = findButton(/^离开/);
      if (leave) {
        await click(leave);
        return true;
      }
      // An event: choosing is the only way on. The scenarios that care pass their own handler.
      const eventPick = findButton(/^选/);
      if (eventPick) {
        await click(eventPick);
        continue;
      }
      if (!buttons().length) return true;
      // Something this driver does not know: click it **once** and let the next round decide --
      // except a button that starts a **new run**. A driver that restarts hides its own failure
      // behind a fresh act, and the trail then shows three walks and no reason.
      // ⚠️ ui_panels.js spells this twice ("再**打**一局" and "再**来**一局"); a guard that names
      // only one of them let a driver restart the run and hide its own failure.
      const any = buttons().find((b) => !/再[打来]一局|换一个 ?seed|重开/.test(text(b)));
      if (!any) return false;
      const before = text(panel());
      await click(any);
      if (text(panel()) === before && !inFight()) return false;
    }
    return false;
  }

  // ---- route planning ------------------------------------------------------------------------
  // BFS over the map's own edges (describeMap reports them) to the nearest node of a kind.
  // The map is a DAG by row, so the first path found is a real route.
  const KIND = { shop: "shop", rest: "rest", elite: "elite", boss: "boss", unknown: "unknown" };
  function planTo(kindName) {
    const view = window.RD_DEBUG.view();
    if (!view) return null;
    const byIdMap = new Map(view.nodes.map((n) => [n.id, n]));
    const starts = view.nodes.filter((n) => n.reachable);
    const parent = new Map();
    const queue = [];
    for (const node of starts) {
      if (node.kindName === kindName) return [node.id];
      parent.set(node.id, -1);
      queue.push(node.id);
    }
    while (queue.length) {
      const id = queue.shift();
      for (const next of byIdMap.get(id).out) {
        if (parent.has(next)) continue;
        parent.set(next, id);
        if (byIdMap.get(next).kindName === kindName) {
          const path = [next];
          let walk = id;
          while (walk !== -1) {
            path.unshift(walk);
            walk = parent.get(walk);
          }
          return path;
        }
        queue.push(next);
      }
    }
    return null;
  }

  // The boss is a **sentinel cursor** at floor 16, off the map (inv:§7.2), so it is not a node a
  // route can name. The last row is the pre-boss campfire; settling it moves the cursor there.
  /// Cheapest route from the current position to the **last row**, where an elite costs a lot more
  /// than anything else.
  ///
  /// Not BFS: "shortest" and "safest" are different questions, and the first version asked the first
  /// one -- so the walk went straight through a three-Sentry elite with 5 HP left and died on floor
  /// 11. A player with a starter deck walks around elites; that is what the branching map is for.
  function planToLastRow() {
    const view = window.RD_DEBUG.view();
    if (!view) return null;
    const last = Math.max(...view.nodes.map((n) => n.row));
    const byIdMap = new Map(view.nodes.map((n) => [n.id, n]));
    const cost = new Map();
    const parent = new Map();
    const done = new Set();
    const frontier = [];
    for (const node of view.nodes.filter((n) => n.reachable)) {
      cost.set(node.id, 0);
      parent.set(node.id, -1);
      frontier.push(node.id);
    }
    while (frontier.length) {
      // smallest tentative cost first (73 nodes: a linear scan is clearer than a heap)
      let bestAt = 0;
      for (let i = 1; i < frontier.length; i++) {
        if (cost.get(frontier[i]) < cost.get(frontier[bestAt])) bestAt = i;
      }
      const id = frontier.splice(bestAt, 1)[0];
      if (done.has(id)) continue;
      done.add(id);
      const node = byIdMap.get(id);
      if (node.row === last) {
        const path = [id];
        let walk = parent.get(id);
        while (walk !== -1 && walk !== undefined) {
          path.unshift(walk);
          walk = parent.get(walk);
        }
        return path;
      }
      for (const next of node.out) {
        if (done.has(next)) continue;
        const step = byIdMap.get(next).kindName === "elite" ? 50 : 1;
        const total = cost.get(id) + step;
        if (!cost.has(next) || total < cost.get(next)) {
          cost.set(next, total);
          parent.set(next, id);
          frontier.push(next);
        }
      }
    }
    return null;
  }

  const deckIds = () => {
    const ids = [];
    for (let index = 0; index < ex.rd_run_deck_count(); index++) {
      const length = ex.rd_run_deck_id_len(index);
      if (length <= 0) continue;
      const ptr = ex.rd_env_scratch_buf();
      ex.rd_run_deck_id_into(index, ptr);
      ids.push(new TextDecoder().decode(new Uint8Array(ex.memory.buffer, ptr, length).slice()));
    }
    return ids;
  };
  // The **run** observation, not the fight vector: 2 health / 3 max / 4 gold / 5 deck / 6 relics
  // (rd_run_observe in rd-wasm). The first version read index 5 as gold, i.e. the deck size, and
  // "the shop did not cost gold" was really "the deck grew" -- a wrong index that looks plausible.
  const relicCount = () => ex.rd_run_observe(6);
  const gold = () => ex.rd_run_observe(4);
  const hp = () => ex.rd_run_observe(2);
  const maxHp = () => ex.rd_run_observe(3);

  // ---- starting a run: pick the first seed in a pinned list whose map can reach the kind ------
  // wanted lives **inside** the injected function (the page context cannot see this file's scope).
  const ONLY_NAMES = ${JSON.stringify(ONLY)};
  const wanted = (name) => ONLY_NAMES === null || ONLY_NAMES.includes(name);

  async function startTowards(name, kindName, seeds) {
    if (!wanted(name)) return { seed: null, ok: false, skipped: true };
    for (const seed of seeds) {
      window.RD_DEBUG.startWithSeed(seed, 0);
      await sleep(0);
      // The **blessing** must be fully settled before a map click means anything: while it is
      // pending, every enter_node is refused. The first version clicked one button and hoped,
      // which left the run on floor 0 while the walk reported "no progress" for 20 hops.
      for (let settleStart = 0; settleStart < 8; settleStart++) {
        if (ex.rd_run_pending() === 0) break;
        const offer = buttons()[0];
        if (offer) {
          await click(offer);
          continue;
        }
        // A blessing that owes a deck pick: the panel offers 选一张牌, then the modal has the cards.
        const pickButton = findButton(/选/);
        if (pickButton) await click(pickButton);
        const card = document.querySelector("#modalBody [data-pick]");
        if (card) await click(card);
        else if (!byId("modal").hidden) byId("modal").hidden = true;
      }
      if (ex.rd_run_pending() !== 0) continue;
      if (planTo(kindName)) return { seed, ok: true };
    }
    return { seed: null, ok: false };
  }

  const out = { scenarios: [], errors: [] };
  window.__sliceErrors = [];
  window.addEventListener("error", (event) => window.__sliceErrors.push(String(event.message)));

  // =============================================================================================
  const SEEDS = [101, 202, 303, 404, 505, 606, 707, 808, 909, 111, 222, 333];

  // ---- (1) shop ------------------------------------------------------------------------------
  {
    const t0 = performance.now();
    const started = await startTowards("shop", "shop", SEEDS);
    const row = { name: "shop", seed: started.seed, ok: started.ok, skipped: started.skipped || false, ms: 0 };
    if (started.ok) {
      const plan = planTo("shop");
      for (let step = 0; step + 1 < plan.length; step++) {
        await click(document.querySelector('[data-node="' + plan[step] + '"]'));
        await settle(120);
      }
      await click(document.querySelector('[data-node="' + plan[plan.length - 1] + '"]'));
      row.kind = ex.rd_run_node_kind();
      row.cards = [...panel().querySelectorAll(".shop-item")].length;
      row.goldBefore = gold();
      row.deckBefore = deckIds().length;
      // The removal service costs 75 and the cheapest card ~45, so with 99 gold a player can afford
      // **one** of them -- and the order decides which. Removing first is the order that proves both
      // (buying first leaves 49 gold and the removal button is disabled, which is exactly what the
      // first version of this scenario tripped over).
      const remove = findButton(/删一张牌/);
      row.hasRemove = Boolean(remove);
      row.deckBeforeRemove = deckIds().length;
      row.goldBeforeRemove = gold();
      if (remove) {
        await click(remove);
        const picks = [...document.querySelectorAll("#modalBody [data-pick]")];
        if (picks.length) await click(picks[0]);
        await settle(20);
      }
      row.deckAfterRemove = deckIds().length;
      row.goldAfterRemove = gold();
      const buyCard = findButton(/^买$/);
      row.hasBuy = Boolean(buyCard);
      if (buyCard) await click(buyCard);
      await settle(30);
      row.deckAfterBuy = deckIds().length;
      row.goldAfterBuy = gold();
      await settle(20);
      row.pending = ex.rd_run_pending();
      row.done = true;
    }
    row.ms = Math.round(performance.now() - t0);
    out.scenarios.push(row);
  }

  // ---- (2) event (the question-mark room) ----------------------------------------------------
  {
    const t0 = performance.now();
    const started = await startTowards("event", "unknown", SEEDS);
    const row = { name: "event", seed: started.seed, ok: started.ok, skipped: started.skipped || false, ms: 0 };
    if (started.ok) {
      const plan = planTo("unknown");
      for (let step = 0; step < plan.length; step++) {
        await click(document.querySelector('[data-node="' + plan[step] + '"]'));
        // the last node IS the event: do not let settle answer it for us
        if (step + 1 < plan.length) await settle(120);
      }
      row.kind = ex.rd_run_node_kind();
      row.text = text(panel()).slice(0, 120);
      const options = buttons().map((b) => text(b)).filter(Boolean);
      row.options = options;
      row.needs = ex.rd_run_event_needs();
      row.deckBefore = deckIds().length;
      row.hpBefore = hp();
      row.goldBefore = gold();
      // choose the first option, then answer any follow-up the page asks for
      const first = buttons()[0];
      if (first) await click(first);
      if (ex.rd_run_event_needs() !== 0) {
        const pick = document.querySelector("#modalBody [data-pick]");
        if (pick) await click(pick);
      }
      await settle(20);
      row.deckAfter = deckIds().length;
      row.hpAfter = hp();
      row.goldAfter = gold();
      row.pendingAfter = ex.rd_run_pending();
      row.done = true;
    }
    row.ms = Math.round(performance.now() - t0);
    out.scenarios.push(row);
  }

  // ---- (3) rest site: smith ------------------------------------------------------------------
  {
    const t0 = performance.now();
    const started = await startTowards("rest", "rest", SEEDS);
    const row = { name: "rest", seed: started.seed, ok: started.ok, skipped: started.skipped || false, ms: 0 };
    if (started.ok) {
      const plan = planTo("rest");
      for (let step = 0; step < plan.length; step++) {
        await click(document.querySelector('[data-node="' + plan[step] + '"]'));
        if (step + 1 < plan.length) await settle(120);
      }
      row.kind = ex.rd_run_node_kind();
      row.hpBefore = hp();
      row.deckBefore = deckIds();
      const smith = findButton(/打铁/);
      row.hasSmith = Boolean(smith);
      if (smith) {
        await click(smith);
        // The picker lists **every** card, upgraded ones included, and picking one of those is
        // refused ("已经升级过了"). A player picks a plain card; so does this.
        const picks = [...document.querySelectorAll("#modalBody [data-pick]")];
        const plain = picks.find((el) => !text(el).includes("+")) || picks[0];
        if (plain) await click(plain);
        await settle(20);
      }
      row.deckAfter = deckIds();
      row.hpAfter = hp();
      row.upgraded = row.deckAfter.filter((id) => id.includes("+")).length;
      row.upgradedBefore = row.deckBefore.filter((id) => id.includes("+")).length;
      row.done = true;
    }
    row.ms = Math.round(performance.now() - t0);
    out.scenarios.push(row);
  }

  // ---- (4) elite: win it, and its relic -------------------------------------------------------
  {
    const t0 = performance.now();
    const started = await startTowards("elite", "elite", SEEDS);
    const row = { name: "elite", seed: started.seed, ok: started.ok, skipped: started.skipped || false, ms: 0 };
    if (started.ok) {
      const plan = planTo("elite");
      for (let step = 0; step < plan.length; step++) {
        await click(document.querySelector('[data-node="' + plan[step] + '"]'));
        if (step + 1 < plan.length) await settle(120);
      }
      row.kind = ex.rd_run_node_kind();
      row.relicsBefore = relicCount();
      const begin = findButton(/^开始战斗/);
      if (begin) await click(begin);
      row.won = await fight(600);
      row.pending = ex.rd_run_pending();
      row.relicOffered = ex.rd_run_reward_relic_len() > 0;
      await settle(60);
      row.relicsAfter = relicCount();
      row.done = true;
    }
    row.ms = Math.round(performance.now() - t0);
    out.scenarios.push(row);
  }

  // ---- (5) boss: the end of the act ----------------------------------------------------------
  {
    // The boss is a sentinel cursor at floor 16, off the map: the route is "walk the whole act",
    // i.e. reach the last row and settle its campfire. That is as literal as "从开局走到幕末" gets.
    const t0 = performance.now();
    const started = await startTowards("boss", "combat", SEEDS);
    const row = { name: "boss", seed: started.seed, ok: started.ok, skipped: started.skipped || false, ms: 0 };
    if (started.ok) {
      // A trail of what each hop actually did: the gate's evidence when the walk stops short.
      row.diag = {
        reachable: ex.rd_run_observe(16),
        panel: text(panel()).slice(0, 40),
        nodes: document.querySelectorAll("#mapbox g.node").length,
        lit: document.querySelectorAll("#mapbox g.node.reachable").length,
        mapHidden: byId("mapbox") ? byId("mapbox").hidden : null,
        pending: ex.rd_run_pending(),
      };
      row.trail = [];
      let lastFloor = -1;
      let stallsOnFloor = 0;
      for (let hop = 0; hop < 40; hop++) {
        const plan = planToLastRow();
        if (!plan) {
          row.trail.push("no-plan@" + ex.rd_run_observe(0) + "/" + ex.rd_run_node_kind() + "/p" + ex.rd_run_pending());
          break;
        }
        // **Click the first hop of the plan**, then settle whatever it landed on. (A version of this
        // line skipped the click when the plan was longer than one hop and only settled -- the walk
        // then reported "no progress on floor 0" for 20 hops, which looked like a broken route.)
        await click(document.querySelector('[data-node="' + plan[0] + '"]'));
        // **Every** hop is settled, including the last one: settling the last row's campfire is what
        // moves the cursor onto the boss sentinel (floor 16). The first version stopped after the
        // click and then reported "stuck on floor 15".
        const settled = await settle(200);
        row.trail.push(
          "f" + ex.rd_run_observe(0) + "k" + ex.rd_run_node_kind() +
          "/len" + plan.length + (settled ? "" : "/STALL") + "/hp" + hp() +
          (settled ? "" : "/" + (inFight() ? "F" : "-") + "p" + ex.rd_run_pending() +
            "/" + text(panel()).slice(0, 20) +
            "/done" + ex.rd_env_done() + "/acts" + ex.rd_env_action_count() +
            "/cards" + document.querySelectorAll("#hand button.card").length +
            "/end" + (byId("endTurn").disabled ? "off" : "on") +
            "/arm" + (byId("enemies").classList.contains("potion-armed") ? "Y" : "N") +
            "/energy" + cell(8) + "/h0" + document.querySelectorAll("#hand button.card[disabled]").length)
        );
        if (ex.rd_run_node_kind() === 7) break; // the cursor is on the boss sentinel
        if (hp() <= 0) break;
        if (ex.rd_run_observe(0) === lastFloor) {
          stallsOnFloor += 1;
          if (stallsOnFloor >= 2) {
            row.trail.push("no-progress@" + ex.rd_run_observe(0));
            break;
          }
        } else {
          stallsOnFloor = 0;
          lastFloor = ex.rd_run_observe(0);
        }
      }
      row.kind = ex.rd_run_node_kind();
      row.actBefore = ex.rd_run_act();
      row.floor = ex.rd_run_observe(0);
      // §161.7 anchor: a potion that asks a question, inside the boss fight.
      row.potionGranted = window.RD_DEBUG.givePotion("attack_potion");
      const beltSlot = ex.rd_run_potion_count() - 1;
      const begin = findButton(/^开始战斗/);
      if (begin) await click(begin);
      row.started = inFight();
      if (row.started) {
        // givePotion appends, so the Attack Potion is the **last** belt slot. Taking the first
        // 用 button drank whatever the act had already dropped there (a block potion), which opens
        // no question -- and the gate then blamed the mechanism.
        const potion = document.querySelector('[data-use-potion="' + beltSlot + '"]');
        row.potionUsed = Boolean(potion);
        if (potion) {
          // §161.7's anchor, step by step: click 用, complete the **target pick** it arms, then read
          // the question it opened *before* answering it. (Reading it after the answer reports 0 --
          // an order-of-observation bug, not a mechanism bug.)
          const button = document.querySelector('[data-use-potion="' + potion.dataset.usePotion + '"]');
          button.onclick ? button.onclick() : await click(button);
          await sleep(0);
          if (byId("enemies").classList.contains("potion-armed")) {
            const target = document.querySelector("#enemies [data-enemy-panel]");
            if (target) await click(target);
            await sleep(0);
          }
          row.potionOpened = ex.rd_env_choice_pending();
          row.potionSource = ex.rd_env_choice_source();
          row.potionOptions = ex.rd_env_choice_count();
          const option = document.querySelector("#modalBody [data-choice]");
          if (option) await click(option);
          const confirmPick = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
          if (confirmPick && !confirmPick.disabled) {
            confirmPick.onclick ? confirmPick.onclick() : await click(confirmPick);
            await sleep(0);
          }
          row.potionAnswered = ex.rd_env_choice_pending() === 0;
        } else {
          row.potionOpened = 0;
          row.potionSource = 0;
          row.potionOptions = 0;
          row.potionAnswered = true;
        }
        row.won = await fight(900);
        if (!row.won) {
          // §175b: a fight that will not end has to say *why*. Same fields as the soak's stuck dump.
          row.fightState = {
            actions: ex.rd_env_action_count(),
            done: ex.rd_env_done(),
            result: ex.rd_env_result(),
            phase: cell(2),
            round: cell(0),
            turn: cell(1),
            heroHp: cell(4),
            hand: cell(10),
            active: (() => {
              const n = ex.rd_env_active_len();
              if (n < 0) return null;
              const b = ex.rd_env_scratch_buf();
              ex.rd_env_active_into(b);
              return new TextDecoder().decode(new Uint8Array(ex.memory.buffer, b, n).slice());
            })(),
            problem: (() => {
              const n = ex.rd_env_problem_len();
              if (n <= 0) return null;
              const b = ex.rd_env_scratch_buf();
              ex.rd_env_problem_into(b);
              return new TextDecoder().decode(new Uint8Array(ex.memory.buffer, b, n).slice());
            })(),
            // §177: the host keeps the FULL failure (TurnError::Host carries only a family).
            hostFailure: (() => {
              const n = ex.rd_env_host_failure_len();
              if (n <= 0) return null;
              const b = ex.rd_env_scratch_buf();
              ex.rd_env_host_failure_into(b);
              return new TextDecoder().decode(new Uint8Array(ex.memory.buffer, b, n).slice());
            })(),
            // §177: StepThrew(Script) only names the family; the code names WHICH refusal.
            code: (() => {
              const code = ex.rd_env_step_code(0);
              if (code <= 0) return null;
              const n = ex.rd_env_code_name_len(code);
              const b = ex.rd_env_scratch_buf();
              ex.rd_env_code_name_into(code, b);
              return code + ":" + new TextDecoder().decode(new Uint8Array(ex.memory.buffer, b, n).slice());
            })(),
            enemies: (() => {
              const out = [];
              for (let i = 0; ; i++) {
                if (ex.rd_env_enemy_name_len(i) < 0) break;
                const n = ex.rd_env_enemy_name_len(i);
                const b = ex.rd_env_scratch_buf();
                ex.rd_env_enemy_name_into(i, b);
                out.push(new TextDecoder().decode(new Uint8Array(ex.memory.buffer, b, n).slice()));
              }
              return out;
            })(),
          };
        }
        row.pending = ex.rd_run_pending();
      }
      await settle(80);
      row.actAfter = ex.rd_run_act();
      row.hpAfter = hp();
      row.maxHp = maxHp();
      row.mapNodes = (() => {
        const view = window.RD_DEBUG.view();
        return view ? view.nodes.length : -1;
      })();
      row.done = true;
    }
    row.ms = Math.round(performance.now() - t0);
    out.scenarios.push(row);
  }

  out.errors = window.__sliceErrors.slice(0, 5);
  return out;
})()`);

const problems = [];
const want = (condition, why) => {
  if (!condition) problems.push(why);
};
const byName = (name) => report.scenarios.find((s) => s.name === name) || {};

want(report.errors.length === 0, `the page threw: ${JSON.stringify(report.errors)}`);
for (const scenario of report.scenarios) {
  if (scenario.skipped) continue;
  want(scenario.ok, `${scenario.name}: no seed in the list can reach that node kind`);
}

const shop = byName("shop");
if (!shop.skipped) {
  want(shop.kind === 4, `shop: the cursor is on kind ${shop.kind}, expected 4 (merchant)`);
  want((shop.cards || 0) >= 4, `shop: only ${shop.cards} stock rows`);
  want(shop.hasRemove === true, "shop: no 删一张牌 service");
  // A run starts with **99** gold (wiki), so at a floor-3 shop a player can afford the 75-gold
  // removal **or** a card, not both -- and which one is not ours to promise across seeds.
  want(
    shop.deckAfterRemove === shop.deckBeforeRemove - 1,
    `shop: removing did not shrink the deck (${shop.deckBeforeRemove} -> ${shop.deckAfterRemove})`
  );
  want(shop.goldAfterRemove < shop.goldBeforeRemove, "shop: removing a card did not cost gold");
  if (shop.deckAfterBuy !== shop.deckAfterRemove) {
    want(
      shop.deckAfterBuy === shop.deckAfterRemove + 1,
      `shop: buying a card did not grow the deck (${shop.deckAfterRemove} -> ${shop.deckAfterBuy})`
    );
    want(shop.goldAfterBuy < shop.goldAfterRemove, "shop: buying a card did not cost gold");
  }
}

const event = byName("event");
if (!event.skipped) {
  want(event.kind === 5, `event: the cursor is on kind ${event.kind}, expected 5 (unknown room)`);
  want((event.text || "").length > 4, `event: the room shows no text (${JSON.stringify(event.text)})`);
  want((event.options || []).length >= 2, `event: only ${(event.options || []).length} option(s)`);
  // An event's payout is **one of** deck / HP / gold -- "Dig through" pays gold, "Study the glyphs"
  // upgrades a card, others take HP. Requires a change, not a particular kind of change.
  want(
    event.deckAfter !== event.deckBefore ||
      event.hpAfter !== event.hpBefore ||
      event.goldAfter !== event.goldBefore,
    `event: choosing an option changed nothing (deck ${event.deckBefore}->${event.deckAfter}, ` +
      `hp ${event.hpBefore}->${event.hpAfter}, gold ${event.goldBefore}->${event.goldAfter})`
  );
}

const rest = byName("rest");
if (!rest.skipped) {
  want(rest.kind === 3, `rest: the cursor is on kind ${rest.kind}, expected 3 (campfire)`);
  want(rest.hasSmith === true, "rest: no 打铁 button");
  want(
    rest.upgraded === rest.upgradedBefore + 1,
    `rest: smithing did not add a + card (${rest.upgradedBefore} -> ${rest.upgraded})`
  );
  want(rest.hpAfter === rest.hpBefore, "rest: smithing must not heal");
  want(
    (rest.deckAfter || []).length === (rest.deckBefore || []).length,
    "rest: smithing changed the deck size"
  );
}

const elite = byName("elite");
if (!elite.skipped) {
  want(elite.kind === 2, `elite: the cursor is on kind ${elite.kind}, expected 2 (elite)`);
  want(elite.won === true, "elite: the fight was not won");
  want(elite.relicOffered === true, "elite: no relic on the reward screen");
  want(
    elite.relicsAfter === (elite.relicsBefore || 0) + 1,
    `elite: the relic was not taken (${elite.relicsBefore} -> ${elite.relicsAfter})`
  );
}

const boss = byName("boss");
if (!boss.skipped) {
  // The boss is the **sentinel cursor** at floor 16 (`inv:§7.2`), reached by settling the last row's
  // campfire -- which is as literal as "从开局走到幕末" gets.
  want(boss.kind === 7, `boss: the cursor is on kind ${boss.kind}, expected 7 (the boss sentinel)`);
  want(boss.floor === 16, `boss: floor ${boss.floor}, expected 16`);
  want(boss.started === true, "boss: the fight did not start");
  // §161.7's anchor: a potion that opens a card question, inside the boss fight.
  want(boss.potionGranted === 0, `boss: the debug grant failed (${boss.potionGranted})`);
  want(boss.potionUsed === true, "boss: no 用 button for the granted potion");
  want(boss.potionOpened === 1, "boss: the Attack Potion opened no question");
  want(boss.potionSource === 2, `boss: the question's source is ${boss.potionSource}, expected 2`);
  want(boss.potionOptions === 3, `boss: ${boss.potionOptions} candidates, expected 3`);
  want(boss.potionAnswered === true, "boss: the question was not answered");
  want(boss.won === true,
  "boss: the boss was not beaten · fight " + JSON.stringify(boss.fightState || null));
  want(
    boss.actAfter === (boss.actBefore || 1) + 1,
    `boss: the act did not advance (${boss.actBefore} -> ${boss.actAfter})`
  );
  want(boss.hpAfter === boss.maxHp, `boss: the act-end heal did not fill up (${boss.hpAfter}/${boss.maxHp})`);
  want(boss.mapNodes > 0, "boss: the next act has no map");
}
if (boss.trail) console.log("  boss trail  " + boss.trail.join(" "));

await page.close();

for (const scenario of report.scenarios) {
  const bits = Object.entries(scenario)
    .filter(([key]) => !["name", "ok", "text", "options", "trail", "diag",
                          "deckBefore", "deckAfter"].includes(key))
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(" ");
  console.log(`  ${scenario.name.padEnd(6)} ${bits}`);
}
if (problems.length) {
  for (const problem of problems) console.error("  - " + problem);
  page.fail(`${problems.length} assertion(s) failed`);
}
console.log("ACT1_SLICE PASS");
