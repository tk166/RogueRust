"""§155: give the soak a **policy** worth having (elites when healthy, rest when hurt).

The soak's job is coverage, not survival, and the first version of the elite preference proved it:
always taking the leftmost node made it die at ~45 clicks (one fight, no campfire, no relic), and
picking nodes at random made it walk past every elite for three seeds.

The rule that works for both is the one a player uses:

* **healthy** (>= 60% HP): elite > treasure > shop > rest > unknown > combat;
* **hurt**: rest > shop > treasure > unknown > combat > elite.

That is a *score per node kind* read from the map element (`data-kind`), so it stays one sorted list
and no extra branch in the click path.
"""

import io

PATH = r"D:\Vibe\sts-tui\web\soak_test.mjs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

START = "      const nodes = [...document.querySelectorAll(\"#mapbox g.node.reachable\")];"
END = "      for (const el of nodes) {\n        groups[2].push({ kind: \"node\", el, label: text(el) });\n      }"

start = source.find(START)
end = source.find(END)
if start < 0 or end < 0:
    raise SystemExit("node block not found")

BLOCK = '''      const nodes = [...document.querySelectorAll("#mapbox g.node.reachable")];
      // Diagnostic: does the **map** hold an elite at all (as opposed to the preference not firing)?
      if (document.querySelector("#mapbox g.node[data-kind=elite]")) out.eliteOnMap = true;
      // A player takes an elite when healthy and rests when hurt -- and the soak has to do both:
      // taking every elite from floor 2 killed it at ~45 clicks, and picking nodes at random walked
      // past every elite for three seeds. Scores come from `data-kind` (a fact), not from glyphs.
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
'''

source = source[:start] + BLOCK + source[end:]
with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("walk policy replaced")
