// smoke.mjs -- prove the BUILT artifact works, without a browser.
//
//   node web/smoke.mjs
//
// The Rust test in `kernel/rd-wasm/src/lib.rs` proves the *crate*; this proves the *file* that
// the page actually fetches: that it validates, instantiates with no imports, exports what
// `web/index.html` touches, and plays one real step of the content-built fight.
//
// ⚠️ This is **not** a browser. It cannot catch: a wrong `Content-Type`, `instantiateStreaming`
// rejecting the response, the page's DOM/JS, or anything that needs `performance.now`. What it
// does catch: a stale copy, a missing export, a module that needs an import nobody provides, and
// numbers that no longer match what `index.html` assumes.

import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const WASM = new URL("./rd_wasm.wasm", import.meta.url);
const bytes = await readFile(WASM);
const fail = (message) => { console.error("SMOKE FAIL: " + message); process.exit(1); };

if (!WebAssembly.validate(bytes)) fail("WebAssembly.validate() rejected the module");
const { instance } = await WebAssembly.instantiate(bytes, {});
const ex = instance.exports;

// The exports `web/index.html` touches (kept in sync with its boot list by hand -- a missing one
// must be a loud failure here rather than a `undefined is not a function` in the page).
const REQUIRED = [
  "memory", "rd_env_observe_len", "rd_env_observe_buf", "rd_env_action_count",
  "rd_env_action_kind", "rd_env_action_arg", "rd_env_step", "rd_env_done", "rd_env_result",
  "rd_env_reset", "rd_env_reward", "rd_env_selfcheck", "rd_env_scratch_buf",
  "rd_env_card_name_len", "rd_env_card_name_into", "rd_env_enemy_name_len",
  "rd_env_enemy_name_into", "rd_env_intent_len", "rd_env_intent_into",
  "rd_env_last_error_len", "rd_env_last_error_into", "rd_env_bench_bookkeeping",
  "rd_env_bench_envelope", "rd_env_bench_step_raw", "rd_env_bench_sizes",
];
for (const name of REQUIRED) {
  if (!(name in ex)) fail(`missing export ${name}`);
}

const OBS_LEN = ex.rd_env_observe_len();
const obs = () => new Int32Array(ex.memory.buffer, ex.rd_env_observe_buf(), OBS_LEN);
const EMPTY = -1;
const H = { HP: 4, HP_MAX: 5, HAND: 10, ENEMIES: 11 };
const OFF_ENEMY = 17, OFF_HAND = 69;

function text(lenOf, intoOf, index) {
  const n = lenOf(index);
  if (n <= 0) return "";
  const ptr = ex.rd_env_scratch_buf();
  intoOf(index, ptr);
  return new TextDecoder().decode(new Uint8Array(ex.memory.buffer, ptr, n).slice());
}
const intentText = (slot) => text(ex.rd_env_intent_len, ex.rd_env_intent_into, slot);
const enemyName = (slot) => text(ex.rd_env_enemy_name_len, ex.rd_env_enemy_name_into, slot);

if (ex.rd_env_reset() !== 0) fail("rd_env_reset() != 0");
const fresh = obs().slice();
if (fresh[H.HAND] !== 0) fail(`hand before the first turn is ${fresh[H.HAND]}, expected 0`);
if (fresh[H.ENEMIES] !== 2) fail(`enemy_count is ${fresh[H.ENEMIES]}, expected 2 (enc_small_slimes)`);
if (ex.rd_env_action_count() !== 1) fail("a fresh fight must offer exactly one action (end turn)");
if (ex.rd_env_action_kind(0) !== 1) fail("that one action must be kind 1 (end turn)");

// Intent: real content, not a placeholder.
const names = [], intents = [];
let previewed = 0;
for (let slot = 0; slot < 2; slot++) {
  const base = OFF_ENEMY + slot * 8;
  if (fresh[base] !== 1) fail(`enemy ${slot} is not alive`);
  if (fresh[base + 5] <= 0) fail(`enemy ${slot} intent_kind is ${fresh[base + 5]}`);
  if (fresh[base + 6] <= 0) fail(`enemy ${slot} intent_damage is ${fresh[base + 6]}`);
  names.push(enemyName(slot));
  intents.push(intentText(slot));
  previewed += fresh[base + 6];
}
if (names.some((n) => n === "")) fail("enemy name is empty (ENCT not read?)");

// One end-turn step must let BOTH enemies act: the HP drop equals the sum of the previewed
// damages. With the old single-enemy path this would be one enemy's worth.
const hpBefore = fresh[H.HP];
if (ex.rd_env_step(0) !== 0) fail(`end-turn step rejected: ${text(ex.rd_env_last_error_len, ex.rd_env_last_error_into, undefined)}`);
const after = obs().slice();
if (hpBefore - after[H.HP] !== previewed) {
  fail(`hero lost ${hpBefore - after[H.HP]} HP, previewed ${previewed} -> not every enemy acted`);
}
if (after[H.HAND] !== 5) fail(`hand after the round is ${after[H.HAND]}, expected 5`);
if (after[OFF_HAND] !== 1) fail("hand slot 0 is not occupied");
if (after[OFF_HAND + 1] < 0) fail("hand slot 0 has no printed cost");

// Play it out with the same "attack first, else end turn" policy the Rust test uses.
let steps = 0;
while (ex.rd_env_done() === 0 && steps < 200) {
  let choice = -1;
  const count = ex.rd_env_action_count();
  for (let i = 0; i < count; i++) {
    if (ex.rd_env_action_kind(i) !== 0) continue;
    const name = text(ex.rd_env_card_name_len, ex.rd_env_card_name_into, ex.rd_env_action_arg(i, 0));
    if (name === "strike" || name === "bash") { choice = i; break; }
  }
  if (choice < 0) {
    for (let i = 0; i < count; i++) {
      if (ex.rd_env_action_kind(i) === 1) { choice = i; break; }
    }
  }
  if (choice < 0) fail(`no legal action at step ${steps}`);
  if (ex.rd_env_step(choice) !== 0) fail(`step ${steps} rejected`);
  steps++;
}
if (ex.rd_env_done() !== 1) fail("the fight did not terminate");
if (ex.rd_env_result() !== 1) fail(`result ${ex.rd_env_result()}, expected 1 (victory)`);
if (ex.rd_env_selfcheck(7, 40) !== 1) fail("selfcheck != 1");

console.log("WEB_SMOKE PASS");
console.log(`  wasm bytes        ${bytes.length}`);
console.log(`  observe_len       ${OBS_LEN} i32`);
console.log(`  enemies           ${names.map((n, i) => `${n} (${intents[i]})`).join(" / ")}`);
console.log(`  round 1 preview   ${previewed} damage, and the fact matched it`);
console.log(`  steps to victory  ${steps}`);
console.log(`  CombatState       ${ex.rd_env_bench_sizes(0)} B (this build)`);
console.log("  ⚠️  not a browser: no DOM, no Content-Type, no instantiateStreaming.");
