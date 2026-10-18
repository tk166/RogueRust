// map_test.mjs -- assert the map page's *semantics*: which node is drawn where, and what is lit.
//
//   node web/map_test.mjs
//
// The companion of `ui_test.mjs`, for the run ABI (`docs/spec/env-abi.md` §11) instead of the
// combat one. `web/map_render.js` holds the decisions; this drives them with the real `.wasm` and
// compares them, node by node, with the module.
//
// It is deliberately **not** a DOM test: the describer and the SVG builder are pure, so there is
// no DOM to fake. The click handler is the DOM half and stays a browser-only check.

import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const fail = (message) => { console.error("MAP_TEST FAIL: " + message); process.exit(1); };

// ---------------------------------------------------------------------------------------------
// Load the module the way the browser does: run it, then read the global it defines.
// ---------------------------------------------------------------------------------------------
const source = await readFile(new URL("./map_render.js", import.meta.url), "utf8");
const context = vm.createContext({});
new vm.Script(source, { filename: "map_render.js" }).runInContext(context);
const M = context.RD_MAP;
if (!M) fail("map_render.js did not define globalThis.RD_MAP");

const page = await readFile(new URL("./map.html", import.meta.url), "utf8");
if (!page.includes('src="./map_render.js"')) {
  fail("map.html does not load map_render.js -- everything below would be dead code");
}
if (!page.includes("RD_MAP.describeMap(") || !page.includes("RD_MAP.svgMarkup(")) {
  fail("map.html loads map_render.js but does not use both describers");
}

// ---------------------------------------------------------------------------------------------
// The module, driven through the same accessor shape the page passes in.
// ---------------------------------------------------------------------------------------------
const bytes = await readFile(new URL("./rd_wasm.wasm", import.meta.url));
const { instance } = await WebAssembly.instantiate(bytes, {});
const ex = instance.exports;

const io = {
  obs: (i) => ex.rd_run_observe(i),
  mapLen: () => ex.rd_run_map_len(),
  rows: () => ex.rd_run_map_rows(),
  node: (i, f) => ex.rd_run_map_node(i, f),
  rowFirst: (r) => ex.rd_run_map_row_first(r),
  actionCount: () => ex.rd_run_action_count(),
  actionArg: (i, w) => ex.rd_run_action_arg(i, w),
};
const view = () => M.describeMap(io);

if (ex.rd_run_start(7) !== 0) {
  const n = ex.rd_run_last_error_len();
  const ptr = ex.rd_env_scratch_buf();
  ex.rd_run_last_error_into(ptr);
  fail("rd_run_start(7) failed: " +
       new TextDecoder().decode(new Uint8Array(ex.memory.buffer, ptr, n).slice()));
}

// ---------------------------------------------------------------------------------------------
// 1. The view is the module's own map, node for node. A renderer that invented a node, dropped
//    one, or mislabelled a kind would have to agree with all of these to pass.
// ---------------------------------------------------------------------------------------------
{
  const v = view();
  if (!v) fail("describeMap returned null for a started run");
  if (v.nodes.length !== ex.rd_run_map_len()) {
    fail(`view has ${v.nodes.length} nodes, the module has ${ex.rd_run_map_len()}`);
  }
  if (v.nodes.length < 15) fail(`only ${v.nodes.length} nodes: a 15-row map cannot be this small`);
  let edges = 0;
  for (const node of v.nodes) {
    if (node.id !== v.nodes.indexOf(node)) fail("node ids are not their own indices");
    if (node.row !== io.node(node.id, M.NODE_ROW)) fail(`node ${node.id} row`);
    if (node.col !== io.node(node.id, M.NODE_COL)) fail(`node ${node.id} col`);
    if (node.kind !== io.node(node.id, M.NODE_KIND)) fail(`node ${node.id} kind`);
    if (node.degree !== io.node(node.id, M.NODE_OUT_DEGREE)) fail(`node ${node.id} out degree`);
    if (node.reachable !== (io.node(node.id, M.NODE_REACHABLE) === 1)) {
      fail(`node ${node.id} reachable flag`);
    }
    if (!(node.row >= 0 && node.row < M.LAYOUT.rows)) fail(`node ${node.id} row ${node.row}`);
    if (!(node.col >= 0 && node.col < M.LAYOUT.columns)) fail(`node ${node.id} col ${node.col}`);
    for (const target of node.out) {
      if (target < 0 || target >= v.nodes.length) fail(`node ${node.id} names node ${target}`);
      if (v.nodes[target].row !== node.row + 1) {
        fail(`node ${node.id} -> ${target} crosses ${v.nodes[target].row - node.row} rows`);
      }
      edges++;
    }
    if (node.out.length !== node.degree) fail(`node ${node.id} edge list length`);
  }
  if (edges === 0) fail("the map has no edges");

  // The kind names must be the kernel's, not a second vocabulary invented by the page.
  const readName = (kind) => {
    const n = ex.rd_run_kind_name_len(kind);
    if (n < 0) return null;
    const ptr = ex.rd_env_scratch_buf();
    ex.rd_run_kind_name_into(kind, ptr);
    return new TextDecoder().decode(new Uint8Array(ex.memory.buffer, ptr, n).slice());
  };
  for (let kind = 0; kind < M.KIND_NAMES.length; kind++) {
    if (readName(kind) !== M.KIND_NAMES[kind]) {
      fail(`kind ${kind}: page says "${M.KIND_NAMES[kind]}", the module says "${readName(kind)}"`);
    }
  }
  if (readName(M.KIND_NAMES.length) !== null) fail("the module has more kinds than the page knows");
}

// ---------------------------------------------------------------------------------------------
// 2. The picture: one shape per node, one path per edge, and the lit set is exactly the action
//    table. Counted off the markup, because "it looks right" is not an assertion.
// ---------------------------------------------------------------------------------------------
{
  const v = view();
  const svg = M.svgMarkup(v);
  const count = (re) => (svg.match(re) || []).length;
  const circles = count(/<circle /g);
  // One `data-node="` per node group, and the `data-nodes="..."` summary is a different string
  // (`s` before the `="`), so this cannot double-count. Counting `<g class="node` did: the
  // wrapper `<g class="nodes">` matched it, which is why the wrapper is now named otherwise.
  const groups = count(/data-node="/g);
  const paths = count(/<path class="edge/g);
  if (groups !== v.nodes.length) fail(`${groups} node groups for ${v.nodes.length} nodes`);
  if (circles !== v.nodes.length) fail(`${circles} circles for ${v.nodes.length} nodes`);
  const edgeTotal = v.nodes.reduce((sum, n) => sum + n.out.length, 0);
  if (paths !== edgeTotal) fail(`${paths} edge paths for ${edgeTotal} edges`);
  if (!svg.includes(`data-nodes="${v.nodes.length}"`) || !svg.includes(`data-edges="${edgeTotal}"`)) {
    fail("the svg does not declare how many nodes and edges it drew");
  }

  // The lit set (`reachable` in the markup) and the action table are two views of one fact; the
  // page uses the action table to decide what a click spends, so they must agree.
  const lit = v.nodes.filter((n) => n.reachable).map((n) => n.id);
  const offered = Array.from({ length: io.actionCount() }, (_, i) => io.actionArg(i, 0));
  if (lit.length !== offered.length ||
      !lit.every((id) => offered.includes(id))) {
    fail(`lit nodes [${lit}] != offered actions [${offered}]`);
  }
  for (const id of lit) {
    if (!svg.includes(`data-node="${id}"`)) fail(`node ${id} is lit but not drawn`);
  }
  // Exactly one node carries `here` when the cursor is on the map.
  const hereCount = count(/class="[^"]*\bhere\b[^"]*"/g);
  if (v.cursor.reached && hereCount !== 1) fail(`${hereCount} "here" markers for a live cursor`);
  if (!v.cursor.reached && hereCount !== 0) fail("a cursor marker before the run started");
  if (v.cursor.reached && !svg.includes(`data-cursor="${v.cursor.node}"`)) {
    fail("the svg does not name the cursor node");
  }
  if (v.cursor.reached && io.node(v.cursor.node, M.NODE_ROW) !== v.cursor.row) {
    fail("the cursor's row disagrees with the module");
  }
}

// ---------------------------------------------------------------------------------------------
// 3. Walking: the view follows the cursor, and the lit set is the new node's exits rather than the
//    old one's. A renderer that cached the reachable set would pass everything above this.
// ---------------------------------------------------------------------------------------------
{
  const before = view();
  const firstOffered = before.actions.slice();
  if (firstOffered.length < 2) fail("floor 1 must offer a choice");
  const target = firstOffered[0];
  const verdict = ex.rd_run_step(0);
  if (verdict !== 0) fail(`rd_run_step(0) returned ${verdict}`);
  const after = view();
  if (after.cursor.node !== target) fail(`cursor is at ${after.cursor.node}, walked to ${target}`);
  if (!after.cursor.reached) fail("the cursor is not marked as reached after a step");
  if (after.status.floor !== 1) fail(`floor is ${after.status.floor} after the first step`);
  const nowOffered = after.actions.slice();
  const firstExits = after.nodes.find((n) => n.id === target).out;
  if (nowOffered.length !== firstExits.length ||
      !nowOffered.every((id) => firstExits.includes(id))) {
    fail(`after the step the action table is [${nowOffered}], the node's exits are [${firstExits}]`);
  }
  if (nowOffered.length === firstOffered.length &&
      nowOffered.every((id, i) => id === firstOffered[i])) {
    fail("the offered set did not change after walking: it is probably cached");
  }
  // The stroke colour of the live edges is what tells the player where they may go; make sure the
  // markup actually distinguishes them.
  const svg = M.svgMarkup(after);
  if (!/edge-live/.test(svg)) fail("no live edges are highlighted after a step");

  // Walk to the bottom and check the invariants hold at every floor.
  let guard = 0;
  while (view().actions.length > 0 && guard < 40) {
    const step = view();
    if (ex.rd_run_step(0) !== 0) fail(`step at floor ${step.status.floor} was refused`);
    guard++;
  }
  const end = view();
  if (end.status.floor !== M.LAYOUT.rows) {
    fail(`walking stopped at floor ${end.status.floor}, expected ${M.LAYOUT.rows}`);
  }
  if (end.actions.length !== 0) fail("the last row still offers a step");
  if (end.nodes.some((n) => n.reachable)) fail("a node is lit although nowhere can be entered");
}

// ---------------------------------------------------------------------------------------------
// 4. A refused step changes nothing, and the view says so.
// ---------------------------------------------------------------------------------------------
{
  const before = view();
  const snapshot = Array.from({ length: M.RUN_OBS_LEN }, (_, i) => io.obs(i));
  if (ex.rd_run_step(9999) !== -1) fail("an out-of-range action was not refused with -1");
  const after = Array.from({ length: M.RUN_OBS_LEN }, (_, i) => io.obs(i));
  if (after.join(",") !== snapshot.join(",")) fail("a refused step moved the run observation");
  const again = view();
  if (again.cursor.node !== before.cursor.node) fail("a refused step moved the cursor");
}

// ---------------------------------------------------------------------------------------------
// 5. Two seeds are two maps. A generator that ignored the seed would pass everything above.
// ---------------------------------------------------------------------------------------------
{
  if (ex.rd_run_start(7) !== 0) fail("restarting seed 7 failed");
  const seven = view().nodes.map((n) => `${n.row}:${n.col}:${n.kind}`).join("|");
  if (ex.rd_run_start(1234) !== 0) fail("starting seed 1234 failed");
  const other = view().nodes.map((n) => `${n.row}:${n.col}:${n.kind}`).join("|");
  if (seven === other) fail("two different seeds produced the same map");
}

// ---------------------------------------------------------------------------------------------
// 6. The agreement between the view and the module, re-checked **after walking**. Blocks 1-3
//    asserted it once, at the fresh state -- which is exactly where the two mutations below are
//    invisible:
//      * `reachable: index < obs[RUN_REACHABLE]` (the lit set becomes "the first N nodes") agrees
//        with the module on floor 1, where the first N nodes ARE the whole of row 0;
//      * dropping the cursor marker agrees with the module before the first step, when there is
//        no cursor.
//    So the helper runs at five points, not one.
// ---------------------------------------------------------------------------------------------
function assertViewAgreesWithModule(where) {
  const v = M.describeMap(io);
  if (!v) fail(`${where}: describeMap returned null`);
  if (v.nodes.length !== io.mapLen()) {
    fail(`${where}: ${v.nodes.length} nodes in the view, ${io.mapLen()} in the module`);
  }
  for (const node of v.nodes) {
    if (node.row !== io.node(node.id, M.NODE_ROW)) fail(`${where}: node ${node.id} row`);
    if (node.col !== io.node(node.id, M.NODE_COL)) fail(`${where}: node ${node.id} col`);
    if (node.kind !== io.node(node.id, M.NODE_KIND)) fail(`${where}: node ${node.id} kind`);
    if (node.reachable !== (io.node(node.id, M.NODE_REACHABLE) === 1)) {
      fail(`${where}: node ${node.id} reachable flag`);
    }
  }
  const lit = v.nodes.filter((n) => n.reachable).map((n) => n.id).sort((a, b) => a - b);
  const offered = Array.from({ length: io.actionCount() }, (_, i) => io.actionArg(i, 0))
    .sort((a, b) => a - b);
  if (lit.join(",") !== offered.join(",")) {
    fail(`${where}: lit [${lit}] but the action table offers [${offered}]`);
  }
  const svg = M.svgMarkup(v);
  const markers = (svg.match(/class="[^"]*\bhere\b[^"]*"/g) || []).length;
  const wantMarkers = v.cursor.reached ? 1 : 0;
  if (markers !== wantMarkers) {
    fail(`${where}: ${markers} cursor markers, expected ${wantMarkers} (reached=${v.cursor.reached})`);
  }
  if (v.cursor.reached && !svg.includes(`data-node="${v.cursor.node}"`)) {
    fail(`${where}: the cursor node is not drawn`);
  }
  return v;
}

{
  assertViewAgreesWithModule("fresh run");
  let steps = 0;
  while (io.actionCount() > 0 && steps < 40) {
    if (ex.rd_run_step(0) !== 0) fail(`step ${steps} refused`);
    steps++;
    assertViewAgreesWithModule(`after step ${steps} (floor ${io.obs(M.RUN_FLOOR)})`);
  }
  if (io.obs(M.RUN_FLOOR) !== M.LAYOUT.rows) {
    fail(`walking stopped at floor ${io.obs(M.RUN_FLOOR)} after ${steps} steps`);
  }
  // A different seed, checked the same way: the helper must not be passing by coincidence.
  if (ex.rd_run_start(4242) !== 0) fail("starting seed 4242 failed");
  assertViewAgreesWithModule("seed 4242, fresh");
  if (ex.rd_run_step(0) !== 0) fail("the first step of seed 4242 was refused");
  assertViewAgreesWithModule("seed 4242, after one step");
}

console.log("MAP_RENDER PASS");
console.log(`  nodes              ${view().nodes.length} drawn, one circle and one group each`);
console.log(`  edges              each path crosses exactly one row`);
console.log(`  lit == actions     the highlighted set and the action table agree at every step`);
console.log(`  walking            floor climbs to ${M.LAYOUT.rows} and the lit set follows the cursor`);
console.log(`  kind names         the page's vocabulary is the module's (rd_run_kind_name_*)`);
console.log(`  seed sensitivity   two seeds, two maps`);
console.log(`  view == module     re-checked after every step of a full walk, on two seeds`);
console.log("  ⚠️  no DOM: the click handler on the SVG is still only checked by eye in a browser.");
