// smoke.mjs -- prove the BUILT artifact works, without a browser.
//
//   node web/smoke.mjs
//
// The Rust test in `kernel/rd-wasm/src/lib.rs` proves the *crate*; this proves the *file* that
// the page actually fetches: that it validates, instantiates with no imports, exports what
// `web/index.html` touches, and plays one real step of the content-built fight.
//
// It also proves two things that only became visible after a **real browser** session:
//   * `web/rd_wasm.wasm` is byte-identical to a fresh build. That file is a **local build
//     product**: `.gitignore` has `web/*.wasm`, so a clone has to build it once. When it is
//     missing or stale the failure prints the exact copy command. (位置陈旧 ≠ mtime 陈旧: a
//     `Copy-Item` restores mtime, a one-comment edit makes mtime lie the other way, and — measured
//     in this repo — a rebuild can change the bytes while the byte COUNT stays identical. All
//     three happened here, so the comparison is on **bytes**);
//   * `web/index.html`'s inline script parses, only calls exports the module really has, and its
//     observation offsets still tile. Before this section, editing the page was **ungated** —
//     a syntax error in it passed every one of the 12 acceptance gates.
//
// ⚠️ This is **not** a browser. It cannot catch: a wrong `Content-Type`, `instantiateStreaming`
// rejecting the response, the DOM, or anything that needs `performance.now`. It also cannot catch
// **Rust ↔ page offset drift**: the page hard-codes the 122-slot layout, and only a real browser
// (or a layout published over the ABI, which is not frozen that way today) shows the numbers
// landing in the wrong cells. What it does catch: a stale copy, a missing export, a module that
// needs an import nobody provides, a page that does not parse, and numbers that no longer match
// what `index.html` assumes.

import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const WASM = new URL("./rd_wasm.wasm", import.meta.url);
const fail = (message) => { console.error("SMOKE FAIL: " + message); process.exit(1); };

const COPY_HINT =
  `  & tools\\cargo.ps1 build -p rd-wasm --release --target wasm32-unknown-unknown\n` +
  `  Copy-Item "kernel\\target\\wasm32-unknown-unknown\\release\\rd_wasm.wasm" "web\\rd_wasm.wasm"`;

let bytes;
try {
  bytes = await readFile(WASM);
} catch (e) {
  // Absent, not corrupt: `web/*.wasm` is git-ignored on purpose, so a clone has no artifact until
  // it builds one. Silent-skip is not an option — the build commands are the message.
  fail(`web/rd_wasm.wasm is missing (${e.code || e.message}). It is git-ignored by design; build it:\n` +
       COPY_HINT);
}

if (!WebAssembly.validate(bytes)) fail("WebAssembly.validate() rejected the module");
const { instance } = await WebAssembly.instantiate(bytes, {});
const ex = instance.exports;

// The exports `web/index.html` touches (kept in sync with its boot list by hand -- a missing one
// must be a loud failure here rather than a `undefined is not a function` in the page).
const REQUIRED = [
  "memory", "rd_env_observe_len", "rd_env_observe_buf", "rd_env_action_count",
  "rd_env_action_kind", "rd_env_action_arg", "rd_env_step", "rd_env_done", "rd_env_result",
  "rd_env_reset", "rd_env_reward", "rd_env_selfcheck", "rd_env_scratch_buf",
  "rd_env_card_name_len", "rd_env_card_name_into",
  "rd_env_card_title_len", "rd_env_card_title_into",
  "rd_env_card_text_len", "rd_env_card_text_into", "rd_env_enemy_name_len",
  "rd_env_enemy_name_into", "rd_env_intent_len", "rd_env_intent_into",
  "rd_env_status_count", "rd_env_status_id_len", "rd_env_status_id_into", "rd_env_status_stacks",
  // §155: the elite/boss relic reward.
  "rd_run_reward_relic_len", "rd_run_reward_relic_into", "rd_run_take_relic",
  "rd_env_last_error_len", "rd_env_last_error_into", "rd_env_bench_bookkeeping",
  "rd_env_bench_envelope", "rd_env_bench_step_raw", "rd_env_bench_sizes",
  // The run layer (`env-abi.md` §11) -- the map page is the consumer.
  "rd_run_start", "rd_run_seed", "rd_run_observe_len", "rd_run_observe", "rd_run_map_len",
  "rd_run_map_rows", "rd_run_map_node", "rd_run_map_row_first", "rd_run_action_count",
  "rd_run_action", "rd_run_action_arg", "rd_run_step", "rd_run_last_error_len",
  "rd_run_last_error_into", "rd_run_kind_name_len", "rd_run_kind_name_into",
  "rd_run_relic_name_len", "rd_run_relic_name_into", "rd_run_relic_id_len", "rd_run_relic_id_into",
  "rd_run_pending", "rd_run_node_kind", "rd_run_begin_node", "rd_run_rest", "rd_run_smith",
  "rd_run_open_chest", "rd_run_leave", "rd_run_shop_card_count", "rd_run_shop_card_id_len",
  "rd_run_shop_card_id_into", "rd_run_shop_card_price", "rd_run_shop_relic_count",
  "rd_run_shop_relic_id_len", "rd_run_shop_relic_id_into", "rd_run_shop_relic_price",
  "rd_run_remove_price", "rd_run_buy_card", "rd_run_buy_relic", "rd_run_remove_card",
  "rd_run_deck_count", "rd_run_deck_id_len", "rd_run_deck_id_into", "rd_run_deck_title_len",
  "rd_run_deck_title_into", "rd_run_fight_begin", "rd_run_fight_end",
  "rd_env_pile_len", "rd_env_pile_card_id_len", "rd_env_pile_card_id_into",
  "rd_env_pile_card_title_len", "rd_env_pile_card_title_into",
  "rd_env_enemy_overflow", "rd_env_forced_turns", "rd_env_use_potion", "rd_run_potion_effect", "rd_run_potion_count", "rd_run_potion_id_len", "rd_run_potion_id_into", "rd_run_drop_potion",
  "rd_run_reward_potion_len", "rd_run_take_potion",
  "rd_run_start_offer_len", "rd_run_start_offer_into", "rd_run_start_gain",
  "rd_run_start_gain_amount", "rd_run_start_cost", "rd_run_start_cost_amount",
  "rd_run_choose_start",
  "rd_run_event_text_len", "rd_run_event_text_into", "rd_run_event_label_len",
  "rd_run_event_label_into", "rd_run_event_effect", "rd_run_event_amount", "rd_run_choose",
  "rd_run_event_needs", "rd_run_pick_event_card",
  "rd_run_reward_gold", "rd_run_reward_card_count", "rd_run_reward_card_id_len",
  "rd_run_reward_card_id_into", "rd_run_reward_card_title_len", "rd_run_reward_card_title_into",
  "rd_run_take_card", "rd_run_skip_reward",
  "rd_env_card_kind", "rd_run_card_kind", "rd_run_node_resolved", "rd_run_boss_beaten",
];
for (const name of REQUIRED) {
  if (!(name in ex)) fail(`missing export ${name}`);
}

const OBS_LEN = ex.rd_env_observe_len();
const obs = () => new Int32Array(ex.memory.buffer, ex.rd_env_observe_buf(), OBS_LEN);
const EMPTY = -1;
const H = { HP: 4, HP_MAX: 5, HAND: 10, ENEMIES: 11 };
// Derived, not remembered: MAX_ENEMY_SLOTS moved 4 -> 6 (a split needs the room), and every
// offset after it moved with it. Reading it off the page's own declaration is what keeps this
// test from being a second copy of the layout.
const OFF_ENEMY = 17, OFF_HAND = OFF_ENEMY + 6 * 8 + 6 * 5;

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
// The fight starts at turn 1 (`start_first_turn` in the builder): StS draws the opening hand when
// combat begins. The reference's scenario DSL waits for the first play (`ScenarioRunner.cs:105`) and
// that path is what the diff harness covers, so this is a *driver* difference, not a kernel one.
if (fresh[H.HAND] !== 5) fail(`hand at combat start is ${fresh[H.HAND]}, expected 5`);
if (fresh[H.ENEMIES] !== 2) fail(`enemy_count is ${fresh[H.ENEMIES]}, expected 2 (enc_small_slimes)`);
// With a hand there are play actions; end-turn must still be among them.
{
  const kinds = [];
  for (let index = 0; index < ex.rd_env_action_count(); index++) kinds.push(ex.rd_env_action_kind(index));
  if (!kinds.includes(1)) fail(`no end-turn action in ${JSON.stringify(kinds)}`);
  if (kinds.every((kind) => kind === 1)) fail("five cards in hand but no play action is offered");
}

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
// The end-turn action is found by **kind**: with a hand, index 0 is a *play*, so the old
// `step(0)` ended up playing a card and no enemy ever acted.
let endTurn = -1;
for (let index = 0; index < ex.rd_env_action_count(); index++) {
  if (ex.rd_env_action_kind(index) === 1) { endTurn = index; break; }
}
if (endTurn < 0) fail("no end-turn action to step with");
const hpBefore = fresh[H.HP];
if (ex.rd_env_step(endTurn) !== 0) fail(`end-turn step rejected: ${text(ex.rd_env_last_error_len, ex.rd_env_last_error_into, undefined)}`);
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

// =============================================================================================
// (1) The artifact in `web/` must be **this tree's** build — compared on bytes, not on mtime.
// =============================================================================================
// mtime has lied twice on this machine: `Copy-Item` restoring a file also restores its mtime
// (cargo then re-used a stale `.rlib`), and a one-line comment edit makes the artifact look old
// while it is in fact current. Bytes have no such ambiguity.
const BUILT = fileURLToPath(
  new URL("../kernel/target/wasm32-unknown-unknown/release/rd_wasm.wasm", import.meta.url));
let builtBytes;
try {
  builtBytes = await readFile(BUILT);
} catch (e) {
  fail(`no build to compare against at ${BUILT} (${e.code || e.message}).\n` + COPY_HINT);
}
const sha = (b) => createHash("sha256").update(b).digest("hex");
if (builtBytes.length !== bytes.length || sha(builtBytes) !== sha(bytes)) {
  fail(`web/rd_wasm.wasm is NOT a fresh build of this tree.\n` +
       `  on disk    ${bytes.length} B  sha256 ${sha(bytes)}\n` +
       `  fresh      ${builtBytes.length} B  sha256 ${sha(builtBytes)}\n` +
       `  Fix: Copy-Item "${BUILT}" "${fileURLToPath(WASM)}"`);
}

// =============================================================================================
// (2) `web/index.html` — the page was the one thing no gate looked at.
// =============================================================================================
// A syntax error in the inline script used to pass all twelve acceptance gates, because every
// gate stopped at the `.wasm`. Four checks, cheapest first: is there exactly one **inline** script,
// does every script (inline or `src=`) parse, does the code call only exports that exist, and do
// the hard-coded observation offsets still tile.
//
// Where the layout lives moved on 2026-10-19: the constants below are declared by
// `web/ui_render.js`, not by the page (`docs/spec/ui-plan.md` U0). So the tiling check reads the
// file that declares them, and the page's own job is checked to be "loads it and calls it".
const html = await readFile(fileURLToPath(new URL("./index.html", import.meta.url)), "utf8");

const tags = [...html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)]
  .map((m) => ({ attrs: m[1], body: m[2] }));
const inline = tags.filter((t) => !/\ssrc\s*=/.test(t.attrs));
const external = tags
  .map((t) => (/\ssrc\s*=\s*"([^"]+)"/.exec(t.attrs) || [])[1])
  .filter(Boolean);
if (inline.length !== 1) {
  fail(`index.html has ${inline.length} inline <script> blocks, expected exactly 1`);
}

// Every file the page loads must exist and parse. Missing is a loud failure with the path, because
// a 404 on a script tag is otherwise a page that silently half-works.
const sources = new Map(); // path -> text, for the checks that follow
for (const src of external) {
  if (!src.startsWith("./")) fail(`script src "${src}" is not relative to the page`);
  const path = fileURLToPath(new URL(src, new URL("./index.html", import.meta.url)));
  try {
    sources.set(src, await readFile(path, "utf8"));
  } catch (e) {
    fail(`index.html loads "${src}", which does not exist (${e.code || e.message})`);
  }
}
for (const [name, text] of [...sources, ["index.html<script>", inline[0].body]]) {
  try {
    new vm.Script(text, { filename: name });
  } catch (e) {
    fail(`${name} does not parse: ${e.message}`);
  }
}
if (!html.includes("RD_UI.describe(")) {
  fail("index.html loads scripts but never calls RD_UI.describe() — the render layer is bypassed");
}

// The direction that breaks when the ABI loses a symbol. (`REQUIRED` above is the other one: a
// symbol the page should be using and is not.)
const allCode = [inline[0].body, ...sources.values()].join("\n");
const called = new Set([...allCode.matchAll(/\bex\.([A-Za-z_][A-Za-z0-9_]*)/g)].map((m) => m[1]));
if (called.size < 20) fail(`only ${called.size} ex.* references found — the extraction broke, not the page`);
for (const name of called) {
  if (!(name in ex)) fail(`the page calls ex.${name}, which the module does not export`);
}

// The 122-slot layout is declared once, in the file that owns it. Re-derive it from that file's own
// parts: adding a status axis or widening a block has to move every offset after it.
const layoutFile = [...sources.entries()].find(([, text]) => /const\s+OFF_HAND\s*=/.test(text));
if (!layoutFile) fail("no loaded script declares the observation layout (OFF_HAND) — where did it move?");
const layout = layoutFile[1];
const NUM = (name) => {
  const m = new RegExp("const\\s+" + name + "\\s*=\\s*(\\d+)\\s*;").exec(layout);
  if (!m) fail(`${layoutFile[0]} no longer declares \`const ${name} = <number>;\``);
  return Number(m[1]);
};
const axesMatch = /const\s+STATUS_AXES\s*=\s*\[([^\]]*)\]/.exec(layout);
if (!axesMatch) fail(`${layoutFile[0]} no longer declares \`const STATUS_AXES = [...]\``);
const axes = axesMatch[1].split(",").filter((s) => s.trim() !== "").length;

const PAGE_HERO_STATUS = NUM("OFF_HERO_STATUS"), PAGE_ENEMY = NUM("OFF_ENEMY");
const PAGE_ENEMY_STATUS = NUM("OFF_ENEMY_STATUS"), PAGE_HAND = NUM("OFF_HAND");
const PAGE_PILES = NUM("OFF_PILES");
const PAGE_ENEMY_SLOTS = NUM("MAX_ENEMY_SLOTS"), PAGE_HAND_SLOTS = NUM("MAX_HAND_SLOTS");
for (const [name, got, want] of [
  ["OFF_ENEMY", PAGE_ENEMY, PAGE_HERO_STATUS + axes],
  ["OFF_ENEMY_STATUS", PAGE_ENEMY_STATUS, PAGE_ENEMY + PAGE_ENEMY_SLOTS * 8],
  ["OFF_HAND", PAGE_HAND, PAGE_ENEMY_STATUS + PAGE_ENEMY_SLOTS * 5],
  ["OFF_PILES", PAGE_PILES, PAGE_HAND + PAGE_HAND_SLOTS * 4],
]) {
  if (got !== want) fail(`${name} is ${got}, but every block before it ends at ${want}`);
}
if (PAGE_PILES + 5 > OBS_LEN) fail(`the piles block ends at ${PAGE_PILES + 5}, past observe_len ${OBS_LEN}`);

// §132: the act transition is announced by the page. A comment cannot be asserted, but the
// **call** can: if someone deletes the announcement the string disappears and this goes red.
// The literal from the page: `<b>—— 第 ${act} 幕 ——</b>`. Asserting on the template
// literal keeps the check honest (it fails if the announcement is deleted or the act is dropped).
if (!inline[0].body.includes("第 ${act} 幕")) {
  fail("index.html no longer announces the act transition");
}

console.log("WEB_SMOKE PASS");
console.log(`  wasm bytes        ${bytes.length}`);
console.log(`  observe_len       ${OBS_LEN} i32`);
console.log(`  enemies           ${names.map((n, i) => `${n} (${intents[i]})`).join(" / ")}`);
console.log(`  round 1 preview   ${previewed} damage, and the fact matched it`);
console.log(`  steps to victory  ${steps}`);
console.log(`  CombatState       ${ex.rd_env_bench_sizes(0)} B (this build)`);
console.log(`  artifact          byte-identical to kernel/target/…/rd_wasm.wasm, sha256 ${sha(bytes).slice(0, 12)}…`);
console.log(`  page              ${1 + sources.size} scripts parsed, ${called.size} exports cross-checked, ` +
            `layout from ${layoutFile[0]}, offsets tile to ${PAGE_PILES + 5}/${OBS_LEN}`);
console.log("  ⚠️  not a browser: no DOM, no Content-Type, no instantiateStreaming, no Rust↔page offset check.");
