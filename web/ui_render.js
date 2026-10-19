// ui_render.js -- the page's *semantics*, separated from its markup.
//
// WHY THIS FILE EXISTS
// --------------------
// `tools\acceptance.ps1` gate 14 proves the page parses, only calls exports that exist, and has
// offsets that tile. It proves **nothing about what any cell displays** -- writing `o[H.HP_MAX]`
// where `o[H.HP]` belongs keeps all fourteen gates green. `docs/spec/ui-plan.md` §1 calls that out
// and U0 is the fix: move every "which number goes in which cell" decision in here, as pure
// functions, so `web/ui_test.mjs` can assert them against the real .wasm.
//
// WHAT IS PURE HERE AND WHAT IS NOT
// ---------------------------------
// These functions read an observation snapshot and an action table and return **plain objects**.
// They touch no DOM, no `ex.*`, and no globals. Text that only the module can produce (card names,
// enemy names, intent descriptions) arrives as an `io` argument -- three accessor functions --
// which is what keeps this file runnable under Node with no DOM at all.
//
// It is a classic script on purpose (no `import`/`export`): that keeps `index.html`'s inline
// script a classic script too, so gate 14's `vm.Script` syntax check keeps working without
// needing module parsing, and Node can load this file through `vm` and read `RD_UI` off the
// context. Zero build step, zero dependency, same as everything else in `web/`.

(function (root) {
  "use strict";

  // ---------------------------------------------------------------------------------------------
  // Observation layout -- mirrors `kernel/rd-wasm/src/lib.rs`. The ABI says the caller must ask
  // for the length instead of hard-coding it, so OBS_LEN comes from `rd_env_observe_len()` at
  // runtime and these are only index bases that the Rust side publishes in the same order.
  // Gate 14 re-derives the tiling from these numbers and the axis list below.
  // ---------------------------------------------------------------------------------------------
  const OFF_HERO_STATUS = 12;
  const OFF_ENEMY = 17; // 4 slots × 8
  const OFF_ENEMY_STATUS = 49; // 4 slots × 5
  const OFF_HAND = 69; // 10 slots × 4
  const OFF_PILES = 109; // 5
  const MAX_ENEMY_SLOTS = 4;
  const MAX_HAND_SLOTS = 10;
  const STATUS_AXES = ["str", "vuln", "weak", "dex", "frail"];

  const H = {
    ROUND: 0, TURN: 1, PHASE: 2, RESULT: 3, HP: 4, HP_MAX: 5, BLOCK: 6, WARD: 7,
    ENERGY: 8, ENERGY_MAX: 9, HAND: 10, ENEMIES: 11,
  };

  const RESULT_NAMES = ["Ongoing", "Victory", "Defeat", "Draw", "Aborted"];
  // `EACT.Intent.Kind` -> the observation's small integer, in the reference enum's order
  // (`ActionIntent.cs:5-13`; the core mirror has no `Label`, so the category is all there is).
  const INTENT_KINDS = ["Unknown", "Attack", "Defend", "Buff", "Debuff", "Special"];
  const ACTION_PLAY = 0;
  const ACTION_END_TURN = 1;

  // ---------------------------------------------------------------------------------------------
  // Action table
  // ---------------------------------------------------------------------------------------------
  // `env-abi.md` §5 emits one play action per (card × live enemy slot), with `arg1 = -1` when
  // there is no live enemy. Grouping by hand slot is what lets the page decide "click plays it"
  // (one option) versus "click arms a target picker" (several).
  function playOptions(actions) {
    const byHand = new Map();
    for (const a of actions) {
      if (a.kind !== ACTION_PLAY) continue;
      if (!byHand.has(a.arg0)) byHand.set(a.arg0, []);
      byHand.get(a.arg0).push({ slot: a.arg1, actionIndex: a.index });
    }
    return byHand;
  }

  function endTurnAction(actions) {
    return actions.find((a) => a.kind === ACTION_END_TURN) || null;
  }

  // ---------------------------------------------------------------------------------------------
  // The four describers
  // ---------------------------------------------------------------------------------------------
  function describeHero(o, io) {
    const statuses = [];
    for (let axis = 0; axis < STATUS_AXES.length; axis++) {
      const stacks = o[OFF_HERO_STATUS + axis];
      if (stacks) statuses.push({ label: STATUS_AXES[axis], stacks });
    }
    return {
      name: io.heroName ? io.heroName() : "hero",
      hp: o[H.HP], hpMax: o[H.HP_MAX],
      energy: o[H.ENERGY], energyMax: o[H.ENERGY_MAX],
      block: o[H.BLOCK],
      handCount: o[H.HAND],
      // `draw d  exhaust x  discard e` -- read straight out of the pile block.
      piles: { draw: o[OFF_PILES], discard: o[OFF_PILES + 2], exhaust: o[OFF_PILES + 3] },
      statuses,
    };
  }

  function describeEnemies(o, io) {
    const out = [];
    const occupied = Math.min(o[H.ENEMIES], MAX_ENEMY_SLOTS);
    for (let slot = 0; slot < occupied; slot++) {
      const base = OFF_ENEMY + slot * 8;
      const statuses = [];
      for (let axis = 0; axis < STATUS_AXES.length; axis++) {
        const stacks = o[OFF_ENEMY_STATUS + slot * 5 + axis];
        if (stacks) statuses.push({ label: STATUS_AXES[axis], stacks });
      }
      const kind = o[base + 5];
      const damage = o[base + 6];
      out.push({
        slot,
        name: io.enemyName(slot) || ("enemy #" + slot),
        alive: o[base] === 1,
        hp: o[base + 1], hpMax: o[base + 2], block: o[base + 3],
        // The observation's own count of ALL statuses on this combatant (`obs[base+7]`), which is
        // NOT the same number as `statuses.length` below: that list only covers the five tracked
        // axes. The page printed the raw cell before this refactor and must keep doing so.
        statusCount: o[base + 7],
        // `-1` means "this implementation has no number for it" (`env-abi.md` §4 reserves -1 for
        // absent), so it is not printed as a quantity.
        intentKind: kind, intentLabel: INTENT_KINDS[kind] || "?",
        intentDamage: damage >= 0 ? damage : null,
        intentText: io.intentText(slot) || "—",
        statuses,
      });
    }
    return out;
  }

  // One entry per hand slot the observation says exists. `cardName` may legitimately be empty for
  // a definition the module cannot name, in which case the definition slot is the fallback -- that
  // is a *content* fact, not a rendering choice, so it is decided here where it can be asserted.
  function describeHand(o, actions, io, aiming) {
    const byHand = playOptions(actions);
    const out = [];
    for (let slot = 0; slot < o[H.HAND]; slot++) {
      const base = OFF_HAND + slot * 4;
      const cost = o[base + 1];
      const definitionSlot = o[base + 2];
      const options = byHand.get(slot) || [];
      const name = io.cardName(slot);
      const affordable = cost >= 0 && cost <= o[H.ENERGY];
      const armed = !!aiming && aiming.hand === slot;
      const playable = options.length > 0;
      const note = !playable ? "出不了" : (armed ? "选一个敌人" : (options.length > 1 ? "多目标" : ""));
      out.push({
        slot, cost, definitionSlot,
        name: name || ("def#" + definitionSlot),
        affordable, playable, armed,
        targetSlots: options.map((option) => option.slot),
        // The single-target case is the fast path: one action in the table means the click can go
        // straight through, and the test pins that so a "always ask for a target" regression shows.
        directActionIndex: options.length === 1 ? options[0].actionIndex : -1,
        note: [!affordable ? "付不起" : "", note].filter(Boolean).join(" · "),
      });
    }
    return out;
  }

  function describeStatus(o) {
    return {
      round: o[H.ROUND], turn: o[H.TURN], phase: o[H.PHASE],
      result: o[H.RESULT], resultName: RESULT_NAMES[o[H.RESULT]] || String(o[H.RESULT]),
      done: o[H.RESULT] > 0,
    };
  }

  /// The whole page, as data. `io` = { cardName, enemyName, intentText }.
  function describe(o, actions, io, aiming) {
    return {
      hero: describeHero(o, io),
      enemies: describeEnemies(o, io),
      hand: describeHand(o, actions, io, aiming),
      status: describeStatus(o),
      endTurn: (() => {
        const action = endTurnAction(actions);
        return { available: !!action, actionIndex: action ? action.index : -1 };
      })(),
    };
  }


  // ---------------------------------------------------------------------------------------------
  // Step diff -- "what just happened", for the animation and the battle log.
  //
  // ⚠️ **Derived from the observation, not from engine events.** `env-abi.md` §4 gives two
  // snapshot vectors per step and no event stream, so this reconstructs the events by subtraction.
  // That is enough for every *visible* thing (health, block, energy, hand, statuses, deaths) and it
  // cannot recover one thing: whether a Block decrease was damage absorbed or the end-of-turn
  // clear. The caller says which step it was (`wasEndTurn`), and the two are reported separately
  // rather than merged into a number that would be wrong half the time.
  //
  // A real event stream would be better and is a recorded follow-up (`docs/spec/ui-plan.md` U2);
  // this exists so the animation can be built and tested now instead of after that.
  // ---------------------------------------------------------------------------------------------

  /// Multiset of hand definition slots (`def_slot` per occupied hand slot).
  function handSlots(o) {
    const out = [];
    for (let slot = 0; slot < o[H.HAND]; slot++) {
      out.push(o[OFF_HAND + slot * 4 + 2]);
    }
    out.sort((a, b) => a - b);
    return out;
  }

  /// Elements of `a` not matched in `b`, as a multiset difference.
  function missingFrom(a, b) {
    const pool = b.slice();
    const out = [];
    for (const value of a) {
      const at = pool.indexOf(value);
      if (at >= 0) pool.splice(at, 1);
      else out.push(value);
    }
    return out;
  }

  /// Every visible change between two observations, as a list of events plus per-side shortcuts.
  function diffObservations(before, after, wasEndTurn) {
    const events = [];
    const push = (event) => { events.push(event); return event; };

    // ---- hero --------------------------------------------------------------------------------
    const heroHpLost = Math.max(0, before[H.HP] - after[H.HP]);
    const heroHpGained = Math.max(0, after[H.HP] - before[H.HP]);
    const heroBlockBefore = Math.max(0, before[H.BLOCK]);
    const heroBlockAfter = Math.max(0, after[H.BLOCK]);
    const heroBlockLost = Math.max(0, heroBlockBefore - heroBlockAfter);
    const heroBlockGained = Math.max(0, heroBlockAfter - heroBlockBefore);
    // A Block decrease is absorbed damage mid-turn and the end-of-turn clear otherwise.
    const heroAbsorbed = wasEndTurn ? 0 : heroBlockLost;
    const heroCleared = wasEndTurn ? heroBlockLost : 0;
    if (heroHpLost || heroAbsorbed) {
      push({ kind: "damage", side: "hero", amount: heroHpLost, blocked: heroAbsorbed });
    }
    if (heroHpGained) push({ kind: "heal", side: "hero", amount: heroHpGained });
    if (heroBlockGained) push({ kind: "block", side: "hero", amount: heroBlockGained });
    if (heroCleared) push({ kind: "blockCleared", side: "hero", amount: heroCleared });

    const energySpent = Math.max(0, before[H.ENERGY] - after[H.ENERGY]);
    if (energySpent) push({ kind: "energy", spent: energySpent });

    // ---- enemies -----------------------------------------------------------------------------
    const slots = Math.max(before[H.ENEMIES], after[H.ENEMIES]);
    for (let slot = 0; slot < slots; slot++) {
      const b = OFF_ENEMY + slot * 8;
      const wasAlive = before[b] === 1;
      const isAlive = after[b] === 1;
      if (!wasAlive && !isAlive) continue; // an empty seat, or one that was already down
      const hpLost = Math.max(0, before[b + 1] - after[b + 1]);
      const hpGained = Math.max(0, after[b + 1] - before[b + 1]);
      const blockLost = Math.max(0, Math.max(0, before[b + 3]) - Math.max(0, after[b + 3]));
      const blockGained = Math.max(0, Math.max(0, after[b + 3]) - Math.max(0, before[b + 3]));
      // An enemy never clears its own Block at end of turn the way the hero does, so a decrease
      // here is absorbed damage either way.
      const absorbed = wasAlive && isAlive ? blockLost : 0;
      if (hpLost || absorbed) {
        push({ kind: "damage", side: "enemy", slot, amount: hpLost, blocked: absorbed });
      }
      if (hpGained) push({ kind: "heal", side: "enemy", slot, amount: hpGained });
      if (blockGained) push({ kind: "block", side: "enemy", slot, amount: blockGained });
      if (wasAlive && !isAlive) push({ kind: "down", slot });
    }

    // ---- statuses ----------------------------------------------------------------------------
    for (let axis = 0; axis < STATUS_AXES.length; axis++) {
      const heroDelta = after[OFF_HERO_STATUS + axis] - before[OFF_HERO_STATUS + axis];
      if (heroDelta) {
        push({ kind: "status", side: "hero", axis: STATUS_AXES[axis],
               label: STATUS_AXES[axis], delta: heroDelta,
               stacks: after[OFF_HERO_STATUS + axis] });
      }
    }
    for (let slot = 0; slot < slots; slot++) {
      for (let axis = 0; axis < STATUS_AXES.length; axis++) {
        const at = OFF_ENEMY_STATUS + slot * 5 + axis;
        const delta = after[at] - before[at];
        if (delta) {
          push({ kind: "status", side: "enemy", slot, axis: STATUS_AXES[axis],
                 label: STATUS_AXES[axis], delta, stacks: after[at] });
        }
      }
    }

    // ---- cards -------------------------------------------------------------------------------
    const discarded = Math.max(0, after[OFF_PILES + 2] - before[OFF_PILES + 2]);
    const exhausted = Math.max(0, after[OFF_PILES + 3] - before[OFF_PILES + 3]);
    const leftHand = missingFrom(handSlots(before), handSlots(after));
    const joinedHand = missingFrom(handSlots(after), handSlots(before));
    // `hand_after = hand_before + drawn - left`, so this is drawn. **Not** the draw pile's delta:
    // drawing takes cards *out* of the draw pile, so its delta is negative and the first version
    // of this reported "0 cards drawn" for a hand that had just gone from empty to five.
    const drawn = Math.max(0, after[H.HAND] - before[H.HAND] + leftHand.length);
    if (drawn) push({ kind: "draw", count: drawn, defSlots: joinedHand });
    if (leftHand.length) {
      push({ kind: "leftHand", count: leftHand.length, defSlots: leftHand, discarded, exhausted });
    }

    // ---- turn and result ---------------------------------------------------------------------
    const turnChanged = before[H.ROUND] !== after[H.ROUND] || before[H.TURN] !== after[H.TURN];
    if (turnChanged) {
      push({ kind: "turn", round: after[H.ROUND], turn: after[H.TURN] });
    }
    if (before[H.RESULT] === 0 && after[H.RESULT] !== 0) {
      push({ kind: "result", result: after[H.RESULT], name: RESULT_NAMES[after[H.RESULT]] });
    }

    return {
      events,
      hero: { hpLost: heroHpLost, hpGained: heroHpGained, absorbed: heroAbsorbed,
              blockGained: heroBlockGained, blockCleared: heroCleared, energySpent },
      drawn, discarded, exhausted,
      leftHand, joinedHand,
      turnChanged,
      result: after[H.RESULT],
      hits: events.filter((event) => event.kind === "damage"),
      deaths: events.filter((event) => event.kind === "down").map((event) => event.slot),
    };
  }

  /// How the log reads, which is not the order the diff computes things in.
  ///
  /// `diffObservations` walks the vector top-down (hero, enemies, statuses, cards, turn), so a card
  /// play came out as "消耗 1 点能量 / 敌人 0 受到 6 点伤害 / 手牌离开：strike" -- the cost before the
  /// card. The reading order is a separate decision, so it is made separately and can be asserted.
  const LOG_ORDER = {
    turn: 0, result: 1, draw: 2, leftHand: 3, energy: 4, block: 5, blockCleared: 6,
    damage: 7, heal: 8, status: 9, down: 10,
  };

  /// The same diff, as lines a player can read. Chinese to match the rest of the page.
  function logLines(diff, io) {
    const lines = [];
    const ordered = diff.events
      .map((event, index) => ({ event, index }))
      .sort((a, b) => {
        const pa = LOG_ORDER[a.event.kind] ?? 99;
        const pb = LOG_ORDER[b.event.kind] ?? 99;
        return pa - pb || a.index - b.index; // stable within a kind
      })
      .map((pair) => pair.event);
    for (const event of ordered) {
      switch (event.kind) {
        case "damage": {
          const who = event.side === "hero" ? "英雄" : `敌人 ${event.slot}`;
          const absorbed = event.blocked ? `（格挡挡下 ${event.blocked}）` : "";
          if (event.amount) lines.push(`${who} 受到 ${event.amount} 点伤害${absorbed}`);
          else lines.push(`${who} 的格挡挡下 ${event.blocked} 点伤害`);
          break;
        }
        case "heal": lines.push(`${event.side === "hero" ? "英雄" : `敌人 ${event.slot}`} 回复 ${event.amount} 点生命`); break;
        case "block": lines.push(`${event.side === "hero" ? "英雄" : `敌人 ${event.slot}`} 获得 ${event.amount} 点格挡`); break;
        case "blockCleared": lines.push("回合结束，格挡清空"); break;
        case "down": lines.push(`敌人 ${event.slot} 被击倒`); break;
        case "energy": lines.push(`消耗 ${event.spent} 点能量`); break;
        case "draw": lines.push(`抽 ${event.count} 张牌`); break;
        case "leftHand": {
          const names = event.defSlots.map((slot) => io.cardNameOfDefinition(slot)).filter(Boolean);
          const what = names.length ? names.join("、") : `${event.count} 张牌`;
          lines.push(`手牌离开：${what}`);
          break;
        }
        case "status": {
          const who = event.side === "hero" ? "英雄" : `敌人 ${event.slot}`;
          const sign = event.delta > 0 ? "+" : "";
          lines.push(`${who} ${event.label} ${sign}${event.delta}`);
          break;
        }
        case "turn": lines.push(`—— 第 ${event.round} 回合 · ${event.turn} ——`); break;
        case "result": lines.push(`战斗结束：${event.name}`); break;
        default: break;
      }
    }
    return lines;
  }

  /// The animation script for one step: what to flash, shake and float, and where.
  ///
  /// Separate from `logLines` because the two answer different questions -- "what does the player
  /// read" and "what moves". Keeping them apart is what lets the log be asserted without a DOM.
  function animationPlan(diff, view) {
    const plan = [];
    for (const hit of diff.hits) {
      const amount = hit.amount + hit.blocked;
      if (hit.side === "hero") plan.push({ effect: "float", at: "hero", text: `-${amount}`, damage: true });
      else plan.push({ effect: "float", at: `enemy:${hit.slot}`, text: `-${amount}`, damage: true });
      if (hit.blocked) {
        plan.push({ effect: "float-at-block", at: hit.side === "hero" ? "hero" : `enemy:${hit.slot}`,
                    text: `格挡 ${hit.blocked}` });
      }
    }
    for (const event of diff.events) {
      if (event.kind === "block") {
        plan.push({ effect: "float", at: event.side === "hero" ? "hero" : `enemy:${event.slot}`,
                    text: `+${event.amount} 格挡` });
      }
      if (event.kind === "heal") {
        plan.push({ effect: "float", at: event.side === "hero" ? "hero" : `enemy:${event.slot}`,
                    text: `+${event.amount}`, heal: true });
      }
      if (event.kind === "down") plan.push({ effect: "collapse", at: `enemy:${event.slot}` });
    }
    for (const hit of diff.hits) {
      plan.push({ effect: "shake", at: hit.side === "hero" ? "hero" : `enemy:${hit.slot}` });
    }
    if (diff.drawn) plan.push({ effect: "draw", count: diff.drawn });
    if (diff.leftHand.length) plan.push({ effect: "cards-left-hand", count: diff.leftHand.length });
    if (diff.turnChanged) plan.push({ effect: "turn", round: diff.turn });
    void view;
    return plan;
  }

  // ---------------------------------------------------------------------------------------------
  // Dragging a card onto a target.
  //
  // The decision "this drop means that action" is a pure function so that the *interaction* can be
  // asserted in Node even though the pointer plumbing can only be checked in a browser -- the same
  // split as the log and the animation plan.
  // ---------------------------------------------------------------------------------------------

  /// Which action a drop on `targetSlot` means.
  ///
  /// `-1` = "not a legal drop": either the card is not playable, or it can be aimed and the drop
  /// missed every enemy it can reach. Returning `-1` rather than "the first action" is the whole
  /// point -- picking a target for the player is exactly the bug that shipped once already
  /// (`web/README.md`, "the card target was never sent").
  ///
  /// A card with a single option (no target, or only one reachable enemy) ignores where it was
  /// dropped, because there is nothing to choose.
  function actionFor(options, handSlot, targetSlot) {
    const list = options.get(handSlot) || [];
    if (list.length === 0) return -1;
    const exact = list.find((option) => option.slot === targetSlot);
    if (exact) return exact.actionIndex;
    if (list.length === 1) return list[0].actionIndex;
    return -1;
  }

  /// The enemy slots a card may be dropped on. Empty means "drop anywhere".
  function dropSlots(options, handSlot) {
    const list = options.get(handSlot) || [];
    if (list.length <= 1) return [];
    return list.map((option) => option.slot).filter((slot) => slot >= 0);
  }

  // ---------------------------------------------------------------------------------------------
  // Sound, as a list of ids rather than as calls.
  //
  // Same reason as the rest: "which sound plays" is a decision about the game, so it is a pure
  // function of the step diff and the browser only renders it. No audio files anywhere -- the
  // page has no assets and is going to keep it that way (`ui-plan.md` §4).
  // ---------------------------------------------------------------------------------------------
  function soundPlan(diff) {
    const ids = [];
    if (diff.result !== 0 && diff.events.some((e) => e.kind === "result")) {
      ids.push(diff.result === 1 ? "victory" : "defeat");
      return ids; // one sound for the end of the fight, not the whole queue behind it
    }
    for (const hit of diff.hits) {
      ids.push(hit.side === "hero" ? "hit-hero" : "hit-enemy");
    }
    for (const event of diff.events) {
      if (event.kind === "block") ids.push("block");
      if (event.kind === "heal") ids.push("heal");
      if (event.kind === "down") ids.push("death");
      if (event.kind === "energy") ids.push("cost");
      if (event.kind === "draw") ids.push("draw");
      if (event.kind === "leftHand") ids.push("whoosh");
      if (event.kind === "turn") ids.push("turn");
    }
    return ids;
  }

  root.RD_UI = {
    // layout (gate 14 checks these tile)
    OFF_HERO_STATUS, OFF_ENEMY, OFF_ENEMY_STATUS, OFF_HAND, OFF_PILES,
    MAX_ENEMY_SLOTS, MAX_HAND_SLOTS, STATUS_AXES, H,
    RESULT_NAMES, INTENT_KINDS, ACTION_PLAY, ACTION_END_TURN,
    // pure describers
    playOptions, endTurnAction,
    describeHero, describeEnemies, describeHand, describeStatus, describe,
    handSlots, diffObservations, logLines, animationPlan, LOG_ORDER,
    actionFor, dropSlots, soundPlan,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
