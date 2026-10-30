"""§155: give the soak a **route planner**, so "cover the elite reward" is not a dice roll.

Random walking never met an elite in three seeds (HP-gated preference still needs an elite to be on
the row the walk happened to take). Hoping is not coverage: the soak now **routes** to whatever it has
not exercised yet.

`RD_DEBUG.view()` already exposes the map graph (`nodes[].out`, `cursor.node`), so the planner is a
BFS from the cursor to the nearest node of the wanted kind, and the click policy prefers that node's
id. Two targets, in priority order:

* **rest** when hurt or when no card has been upgraded yet (the campfire's 锻造 is the §154 feature);
* **elite** when healthy and no elite has been fought yet (the §155 relic reward).

Everything else stays random -- the point of the soak is still the random clicking, not a scripted
tour.
"""

import io

PATH = r"D:\Vibe\sts-tui\web\soak_test.mjs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

ANCHOR = "  // Pick a card the way a careful beginner would: block what hurts, then hit back."

PLANNER = '''  // ---- §155: route to the feature this run has not covered yet --------------------------------
  // `RD_DEBUG.view()` is the map the page drew (`describeMap`): `nodes[].out` are the exits and
  // `cursor.node` is where the player stands, so the next hop is a BFS away.
  const nextHopTo = (wanted) => {
    const view = RD_DEBUG.view();
    if (!view || !view.nodes || !wanted) return -1;
    const start = view.cursor.node;
    if (start < 0) return -1;
    const previous = new Map([[start, -1]]);
    const queue = [start];
    let goal = -1;
    while (queue.length) {
      const at = queue.shift();
      if (at !== start && wanted(view.nodes[at])) {
        goal = at;
        break;
      }
      for (const next of view.nodes[at].out || []) {
        if (!previous.has(next)) {
          previous.set(next, at);
          queue.push(next);
        }
      }
    }
    if (goal < 0) return -1;
    let step = goal;
    while (previous.get(step) !== start) step = previous.get(step);
    return step;
  };

  /// Which kind of node this run still needs. `null` = nothing in particular, walk at random.
  const uncoveredTarget = () => {
    const hp = ex.rd_run_observe(2);
    const hpMax = Math.max(1, ex.rd_run_observe(3));
    const healthy = hp * 10 >= hpMax * 6;
    if (!out.upgradedSeen) {
      // The campfire is the only place a card gets upgraded; hurt or not, go there.
      if (!healthy) return (node) => node.kindName === "rest";
      return (node) => node.kindName === "rest";
    }
    if (healthy && out.eliteFights === 0) return (node) => node.kindName === "elite";
    return null;
  };

'''

if "const nextHopTo" in source:
    print("planner already present")
else:
    if ANCHOR not in source:
        raise SystemExit("anchor missing")
    source = source.replace(ANCHOR, PLANNER + ANCHOR, 1)
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("planner inserted")

# make the node sort prefer the planned hop
with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

OLD = """      nodes.sort((a, b) => score(b) - score(a));"""
NEW = """      nodes.sort((a, b) => score(b) - score(a));
      // §155: the planned hop wins over the score, so a feature that has not been covered yet is
      // actually reached instead of merely being likely.
      const hop = nextHopTo(uncoveredTarget());
      if (hop >= 0) {
        nodes.sort((a, b) =>
          (String(b.dataset.node) === String(hop) ? 1 : 0) -
          (String(a.dataset.node) === String(hop) ? 1 : 0));
      }"""

if OLD not in source:
    raise SystemExit("sort anchor missing")
if "const hop = nextHopTo(" in source:
    print("hop sort already present")
else:
    source = source.replace(OLD, NEW, 1)
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("hop sort wired")
