"""§155: the soak needs to *survive* to reach the features, so it plays like a beginner, not a die.

Why: with `enc_gremlin_gang` moved into act 1 (§153), a walk that plays random cards loses at floor 1
to three gremlins -- and then the elite keepsake, the campfire forge and the boss are never reached,
which is exactly what the coverage assertions started reporting.

The heuristic, in the driver only:

1. read the fight's numbers from the observation (HP, Block, and each enemy's intent damage);
2. if the incoming damage beats the current Block (or HP is under 60%), play a **Block** card first;
3. otherwise play a **damage** card;
4. otherwise play anything playable; otherwise end the turn.

"Which card is which" comes from the button's own text ("Gain 5 Block." / "Deal 6 damage.") -- the
page prints the content's description, so this reads the same words a player does.
"""

import io

PATH = r"D:\Vibe\sts-tui\web\soak_test.mjs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

ANCHOR = "  const relicCount = () => ex.rd_run_observe(6);"

HELPER = '''  const relicCount = () => ex.rd_run_observe(6);

  /// One observation cell, out of the fight's vector (`ui_render.js`'s `H` / `OFF_ENEMY`).
  const cell = (index) => {
    const buf = ex.rd_env_scratch_buf();
    ex.rd_env_observe_into(buf);
    return new Int32Array(ex.memory.buffer, buf, ex.rd_env_observe_len())[index];
  };

  /// How much damage the enemies are telegraphing this turn (`OFF_ENEMY + slot*8 + 6`).
  const incomingDamage = () => {
    let total = 0;
    const slots = Math.min(cell(11), 6);
    for (let slot = 0; slot < slots; slot++) {
      const damage = cell(24 + slot * 8 + 6);
      if (damage > 0) total += damage;
    }
    return total;
  };

  /// Pick a card the way a careful beginner would: block what hurts, then hit back.
  const chooseFightAction = () => {
    const cards = [...document.querySelectorAll("#hand button.card:not([disabled])")];
    const hp = cell(4);
    const hpMax = Math.max(1, cell(5));
    const block = cell(6);
    const hurt = hp * 10 < hpMax * 6 || incomingDamage() > block;
    const blocks = cards.filter((card) => /block/i.test(card.textContent));
    const hits = cards.filter((card) => /damage/i.test(card.textContent));
    const order = hurt ? [blocks, hits, cards] : [hits, blocks, cards];
    for (const group of order) {
      if (group.length) return group[Math.floor(random() * group.length)];
    }
    const end = byId("endTurn");
    return end && !end.disabled ? end : null;
  };'''

if "const chooseFightAction" in source:
    print("fight heuristic already present")
else:
    if ANCHOR not in source:
        raise SystemExit("anchor missing")
    source = source.replace(ANCHOR, HELPER, 1)
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("fight heuristic inserted")

# use it: in a fight, the choice comes from the heuristic instead of `pick(list)`
with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

OLD = """      const headIsNode = list[0] && list[0].kind === "node";"""
NEW = """      // §155: in a fight the choice is the beginner heuristic, not a dice roll (random play loses
      // to three gremlins at floor 1 and then nothing later in the act gets covered).
      const inFightNow = !byId("handPanel").hidden;
      const headIsNode = !inFightNow && list[0] && list[0].kind === "node";
      if (inFightNow) {
        const picked = chooseFightAction();
        if (picked) {
          const beforeFight = fingerprint();
          picked.dispatchEvent(new MouseEvent("click", { bubbles: true }));
          await sleep(0);
          // A card that arms the enemy picker needs a target click to resolve.
          const target = document.querySelector("#enemies [data-target-slot]");
          if (target) {
            target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
            await sleep(0);
          }
          await sleep(0);
          actions += 1;
          if (fingerprint() === beforeFight) {
            out.dead.push({
              runSeed, actions, kind: "fight-choice",
              label: text(picked).slice(0, 40),
            });
          }
          invariants("seed " + runSeed + " action " + actions);
          if (ex.rd_run_observe(2) <= 0) break;
          continue;
        }
      }"""

if OLD not in source:
    raise SystemExit("choice anchor missing")
if "const inFightNow = " in source:
    print("fight branch already present")
else:
    source = source.replace(OLD, NEW, 1)
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("fight branch wired")
