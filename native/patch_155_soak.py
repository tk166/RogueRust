"""§155: teach the soak to *reach* the small features (elite relics, campfire upgrades).

The soak (§151) clicks random enabled controls. That is excellent at finding dead buttons and useless
at covering one specific thing: it took whichever reward row came first (always a card, never the
relic appended after it), it walked past elites because a normal node was equally reachable, and on
arrival it always clicked a screen's **first** action -- so a campfire only ever rested, never forged.

Policy changes (the assertions stay "no dead button, no exception, no wedge"):

1. elites come first among reachable nodes (a player takes an elite for the relic);
2. a reward screen is taken **in full** (card, potion, relic), then skipped;
3. the Nth arrival at a screen clicks its Nth action (so 休息 and 锻造 both happen);
4. after every click, three facts are read off the ABI: elite fights begun, relics gained, and
   whether any deck entry carries a `+` (an upgrade happened).

The exported names are `rd_run_deck_id_len` / `rd_run_deck_id_into` (not `..._card_...`).
"""

import io

PATH = r"D:\Vibe\sts-tui\web\soak_test.mjs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()


def replace_once(old, new, why):
    global source
    if old not in source:
        raise SystemExit("anchor missing: " + why)
    source = source.replace(old, new, 1)


replace_once(
    "  const out = { seeds: [], errors: [], dead: [], refused: [], stuck: [], invariant: [], screens: [] };",
    """  const out = {
    seeds: [], errors: [], dead: [], refused: [], stuck: [], invariant: [], screens: [],
    // §155 coverage: facts about the *run*, read off the ABI, so "did the soak reach this feature"
    // is a number and not a hope.
    eliteFights: 0, bossFights: 0, relicsGained: 0, relicFromElite: 0, upgradedSeen: false,
    arrivals: {},
  };""",
    "out shape",
)

replace_once(
    '  const panel = () => document.getElementById("nodePanel");',
    '''  const panel = () => document.getElementById("nodePanel");

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
  };''',
    "coverage probes",
)

replace_once(
    """      for (const el of document.querySelectorAll("#mapbox g.node.reachable")) {
        groups[2].push({ kind: "node", el, label: text(el) });
      }""",
    """      // §155: an elite pays a relic, so a player takes it. Sorting is the whole policy -- the
      // "arrival takes the first" rule then picks the elite without a second branch.
      const nodes = [...document.querySelectorAll("#mapbox g.node.reachable")];
      const isElite = (el) => text(el).includes("精英");
      nodes.sort((a, b) => (isElite(b) ? 1 : 0) - (isElite(a) ? 1 : 0));
      for (const el of nodes) {
        groups[2].push({ kind: "node", el, label: text(el) });
      }""",
    "elite preference",
)

# rotation + "take everything on a reward screen"
replace_once(
    """      const choice = preferPrimary ? list[0] : pick(list);
      preferPrimary = false;
      if (choice.kind === "node") preferPrimary = true;""",
    """      // §155: a reward screen is taken in full before moving on.
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
      const choice = preferPrimary ? list[Math.min(arrivals, list.length - 1)] : pick(list);
      if (preferPrimary) out.arrivals[screen] = arrivals + 1;
      preferPrimary = false;
      if (choice.kind === "node") preferPrimary = true;""",
    "rotation",
)

replace_once(
    """      const floor = ex.rd_run_observe(0);""",
    """      const floor = ex.rd_run_observe(0);
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
      const relicsNow = relicCount();
      if (relicsNow > (out.lastRelicsWatch ?? relicsNow)) {
        const gained = relicsNow - (out.lastRelicsWatch ?? relicsNow);
        out.relicsGained += gained;
        if (out.awaitingEliteReward) out.relicFromElite += gained;
      }
      out.lastRelicsWatch = relicsNow;
      if (!out.upgradedSeen && deckIds().some((id) => id.includes("+"))) out.upgradedSeen = true;""",
    "coverage probes in the loop",
)

replace_once(
    """  for (let run = 0; run < SEED_COUNT; run++) {""",
    """  out.lastRelicsWatch = relicCount();
  for (let run = 0; run < SEED_COUNT; run++) {""",
    "relic baseline",
)

# the assertion block
replace_once(
    """want(report.screens.length >= 4,
  `the walk only saw ${report.screens.length} kinds of screen: ${JSON.stringify(report.screens)}`);""",
    """want(report.screens.length >= 4,
  `the walk only saw ${report.screens.length} kinds of screen: ${JSON.stringify(report.screens)}`);
// §155 coverage: the small features have to be **reached**, not merely survive a random walk.
want(report.eliteFights >= 1, "the walk never fought an elite (so elite rewards were never exercised)");
want(report.relicsGained >= 1, "the walk never gained a relic (chest or elite reward)");
want(report.relicFromElite >= 1, "no relic was gained from an elite reward");
want(report.upgradedSeen, "the walk never upgraded a card (the campfire's 锻造 was never clicked)");""",
    "coverage assertions",
)

replace_once(
    """console.log("  refusals          " + report.refused.length);""",
    """console.log("  refusals          " + report.refused.length);
console.log(
  "  coverage          " + report.eliteFights + " elite(s) · " + report.bossFights + " boss(es) · " +
    report.relicsGained + " relic(s) (" + report.relicFromElite + " from elites) · upgrade " +
    (report.upgradedSeen ? "yes" : "NO")
);""",
    "coverage log",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("soak policy patched")
