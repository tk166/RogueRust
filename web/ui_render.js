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

  root.RD_UI = {
    // layout (gate 14 checks these tile)
    OFF_HERO_STATUS, OFF_ENEMY, OFF_ENEMY_STATUS, OFF_HAND, OFF_PILES,
    MAX_ENEMY_SLOTS, MAX_HAND_SLOTS, STATUS_AXES, H,
    RESULT_NAMES, INTENT_KINDS, ACTION_PLAY, ACTION_END_TURN,
    // pure describers
    playOptions, endTurnAction,
    describeHero, describeEnemies, describeHand, describeStatus, describe,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
