// map_render.js -- the Act 1 map, as data and as SVG, with no DOM and no wasm in sight.
//
// The companion of `ui_render.js`, for the *run* ABI (`docs/spec/env-abi.md` §11) instead of the
// combat one. Same reason it exists: "which node is drawn where, and which one is lit" is a
// decision, and a decision that no gate can see is a decision that will drift. Here it is a pure
// function from an accessor object to a plain view, plus a pure function from that view to SVG
// markup -- so `node web/map_test.mjs` can assert both against the real `.wasm`.
//
// It is a classic script (no `import`/`export`) for the same reason `ui_render.js` is: the page
// stays a classic script, gate 14 keeps working without module parsing, and Node can load this
// through `vm` and read `RD_MAP` off the context.

(function (root) {
  "use strict";

  // ---------------------------------------------------------------------------------------------
  // `env-abi.md` §11.3 -- the run observation. Indexed by number, like the combat one.
  // ---------------------------------------------------------------------------------------------
  const RUN_FLOOR = 0;
  const RUN_NODE = 1;
  const RUN_HEALTH = 2;
  const RUN_HEALTH_MAX = 3;
  const RUN_GOLD = 4;
  const RUN_DECK = 5;
  const RUN_RELICS = 6;
  const RUN_POTIONS = 7;
  const RUN_MAP_LEN = 8;
  const RUN_STREAM_FIRST = 9; // 9..=15, seven streams in id order
  const RUN_STREAM_COUNT = 7;
  const RUN_REACHABLE = 16;
  const RUN_REMOVED = 17;
  const RUN_OBS_LEN = 19;

  // `env-abi.md` §11.2
  const NODE_ROW = 0;
  const NODE_COL = 1;
  const NODE_KIND = 2;
  const NODE_OUT_DEGREE = 3;
  const NODE_EDGE0 = 4; // 4,5,6
  const NODE_REACHABLE = 7;

  // `run-layer.md` §7.2. The names are the kernel's own (`NodeKind::name`); the page must not
  // invent a second vocabulary, so the test cross-checks these against `rd_run_kind_name_*`.
  const KIND_NAMES = [
    "unassigned", "combat", "elite", "rest", "shop", "unknown", "treasure",
  ];

  // Presentation only. Colour is by kind; `unassigned` is deliberately ugly because seeing one is
  // a bug, not a state.
  const KIND_LABELS = {
    unassigned: "?",
    combat: "⚔",
    elite: "☠",
    rest: "🔥",
    shop: "$",
    unknown: "?",
    treasure: "💎",
  };

  const LAYOUT = {
    columns: 7,          // `inv:§7.1`: the grid is seven wide
    rows: 15,            // floors 1..=15; 16 (boss) and 17 (boss chest) are not on the map
    colWidth: 84,
    rowHeight: 58,
    marginX: 28,
    marginY: 34,
    radius: 15,
  };

  /// Where a node's circle centre goes. **Floor 1 is at the bottom**, because the player climbs
  /// (`run-layer.md` §6.1: the cursor walks from row 0 upward) and that is how the map reads.
  function position(row, col) {
    const x = LAYOUT.marginX + col * LAYOUT.colWidth + LAYOUT.colWidth / 2;
    const y = LAYOUT.marginY + (LAYOUT.rows - 1 - row) * LAYOUT.rowHeight + LAYOUT.rowHeight / 2;
    return { x, y };
  }

  /// Everything the page needs, as data.
  ///
  /// `io` is the ABI surface, passed in so this file never touches a global:
  /// `{ obs(i), mapLen(), rows(), node(i, field), rowFirst(row), actionCount(), actionArg(i, which) }`.
  function describeMap(io) {
    const len = io.mapLen();
    if (len < 0) return null;
    const nodes = [];
    for (let index = 0; index < len; index++) {
      const kind = io.node(index, NODE_KIND);
      const name = KIND_NAMES[kind] || "unknown";
      const degree = io.node(index, NODE_OUT_DEGREE);
      const out = [];
      for (let slot = 0; slot < degree; slot++) {
        const target = io.node(index, NODE_EDGE0 + slot);
        // `-1` means "no such edge"; a real global index is never negative.
        if (target >= 0) out.push(target);
      }
      nodes.push({
        id: index,
        row: io.node(index, NODE_ROW),
        col: io.node(index, NODE_COL),
        kind, kindName: name,
        label: KIND_LABELS[name] || "?",
        degree, out,
        reachable: io.node(index, NODE_REACHABLE) === 1,
      });
    }
    const cursor = io.obs(RUN_NODE);
    // The action table is the authority on "what can I do now"; the `reachable` flag above is the
    // same set seen from the map's side. Asserting the two agree is the test's job, not a choice
    // made here -- so both are reported and neither is derived from the other.
    const actions = [];
    for (let index = 0; index < io.actionCount(); index++) {
      actions.push(io.actionArg(index, 0));
    }
    return {
      nodes,
      cursor: { node: cursor, reached: cursor >= 0, row: cursor >= 0 ? io.node(cursor, NODE_ROW) : -1 },
      actions,
      status: {
        floor: io.obs(RUN_FLOOR),
        health: io.obs(RUN_HEALTH),
        healthMax: io.obs(RUN_HEALTH_MAX),
        gold: io.obs(RUN_GOLD),
        deckSize: io.obs(RUN_DECK),
        relics: io.obs(RUN_RELICS),
        potions: io.obs(RUN_POTIONS),
        mapLen: io.obs(RUN_MAP_LEN),
        reachable: io.obs(RUN_REACHABLE),
        removed: io.obs(RUN_REMOVED),
        streams: Array.from({ length: RUN_STREAM_COUNT }, (_, k) => io.obs(RUN_STREAM_FIRST + k)),
      },
      layout: LAYOUT,
    };
  }

  const esc = (s) => String(s).replace(/[<>&"]/g,
    (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]));

  /// The map as an SVG string. Pure: same view in, same string out, which is what makes "the
  /// picture has one circle per node and one path per edge" an assertion rather than a look.
  ///
  /// The background and the border are on the `<svg>` element itself (set by the page), and the
  /// `viewBox` is derived from the layout so the two cannot disagree.
  function svgMarkup(view) {
    if (!view) return "";
    const { rows } = LAYOUT;
    const width = LAYOUT.marginX * 2 + LAYOUT.columns * LAYOUT.colWidth;
    const height = LAYOUT.marginY * 2 + rows * LAYOUT.rowHeight;
    const byId = new Map(view.nodes.map((node) => [node.id, node]));

    const edges = [];
    const circles = [];
    const captions = [];
    for (const node of view.nodes) {
      const from = position(node.row, node.col);
      for (const target of node.out) {
        const to = byId.get(target);
        if (!to) continue; // a dangling edge is the validator's business, not the renderer's
        const end = position(to.row, to.col);
        edges.push(
          `<path class="edge${node.reachable || to.reachable ? " edge-live" : ""}" ` +
          `data-from="${node.id}" data-to="${target}" ` +
          `d="M ${from.x} ${from.y} L ${end.x} ${end.y}"/>`);
      }
      const classes = ["node", `kind-${node.kindName}`];
      if (node.reachable) classes.push("reachable");
      if (node.id === view.cursor.node) classes.push("here");
      circles.push(
        `<g class="${classes.join(" ")}" data-node="${node.id}" data-kind="${esc(node.kindName)}" ` +
        `data-row="${node.row}" data-col="${node.col}">` +
        `<circle cx="${from.x}" cy="${from.y}" r="${LAYOUT.radius}"/>` +
        `<text x="${from.x}" y="${from.y}" text-anchor="middle" dominant-baseline="central">` +
        `${esc(node.label)}</text>` +
        `<title>floor ${node.row + 1} · ${esc(node.kindName)} · node ${node.id}</title>` +
        `</g>`);
      // Floor numbers on the left edge, so a screenshot is readable without the tooltip.
      if (node.col === 0 || node === view.nodes.find((n) => n.row === node.row)) {
        captions.push(
          `<text class="floor" x="${LAYOUT.marginX - 12}" y="${from.y}" ` +
          `text-anchor="end" dominant-baseline="central">${node.row + 1}</text>`);
      }
    }

    return (
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" ` +
      `width="${width}" height="${height}" data-nodes="${view.nodes.length}" ` +
      `data-edges="${edges.length}" data-cursor="${view.cursor.node}">` +
      `<desc>Act 1 map: ${view.nodes.length} nodes, ${edges.length} edges, ` +
      `cursor at ${view.cursor.node}</desc>` +
      `<g class="edges">${edges.join("")}</g>` +
      // NOT `class="nodes"`: that starts with the same characters as a node group's
      // `class="node ..."`, and a test that counts node groups by prefix then counts this too.
      `<g class="node-layer">${circles.join("")}</g>` +
      `<g class="captions">${captions.join("")}</g>` +
      `</svg>`);
  }

  /// One line of status, so the page and the test agree about what the header says.
  function statusLine(view) {
    if (!view) return "no run";
    const s = view.status;
    return `floor ${s.floor} · hp ${s.health}/${s.healthMax} · gold ${s.gold} · ` +
           `deck ${s.deckSize} · relics ${s.relics} · potions ${s.potions}`;
  }

  root.RD_MAP = {
    // layout of the run observation (gate 14 does not check these; `map_test.mjs` does)
    RUN_FLOOR, RUN_NODE, RUN_HEALTH, RUN_HEALTH_MAX, RUN_GOLD, RUN_DECK, RUN_RELICS,
    RUN_POTIONS, RUN_MAP_LEN, RUN_STREAM_FIRST, RUN_STREAM_COUNT, RUN_REACHABLE, RUN_REMOVED,
    RUN_OBS_LEN,
    // map node fields
    NODE_ROW, NODE_COL, NODE_KIND, NODE_OUT_DEGREE, NODE_EDGE0, NODE_REACHABLE,
    KIND_NAMES, KIND_LABELS, LAYOUT,
    // pure functions
    position, describeMap, svgMarkup, statusLine,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
