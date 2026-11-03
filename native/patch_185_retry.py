"""§185: the boss scenario retries seeds instead of betting on one.

Why: `§183` found that adding three colorless cards + one potion to the content made the **same
seed** walk a different route (drop table + reward pool), and the driver lost the boss fight. That
is a legal loss, not an engine bug -- but the gate's claim is "an act can be walked to its end", and
a gate that holds only for one lucky content size is a lottery, not a gate (§183's conclusion).

The fix is not "pick a luckier number": the scenario now tries `BOSS_SEEDS` in order and accepts the
first attempt that satisfies **both** claims it makes:

1. the act advanced (`actAfter === 2`), i.e. the boss was actually beaten, and
2. the §161.7 potion anchor really fired (a potion could be granted, a picker opened, an answer
   landed) -- a winning seed whose belt was full does not exercise the anchor at all.

Every attempt is reported in `row.attempts`, so a red gate says *which* seeds were tried and *how*
each one ended instead of "the boss was not beaten".
"""
import io
import re

PATH = "web/act1_slice.mjs"

HEADER_OLD = """    const t0 = performance.now();
    const started = await startTowards("boss", "combat", SEEDS);
    const row = { name: "boss", seed: started.seed, ok: started.ok, skipped: started.skipped || false, ms: 0 };
    if (started.ok) {"""

HEADER_NEW = """    const t0 = performance.now();
    // §185: try the seeds in order; the first attempt that both **beats the boss** and exercises the
    // potion anchor is the one reported. See the module note in port-plan.md §185 for why "pick a
    // luckier seed" was not acceptable.
    const attempts = [];
    let row = null;
    let fallback = null;
    for (const seed of BOSS_SEEDS) {
      const started = await startTowards("boss", "combat", [seed]);
      const attempt = {
        name: "boss", seed: started.seed, ok: started.ok, skipped: started.skipped || false, ms: 0,
      };
      if (!started.ok || attempt.skipped) {
        attempts.push({ seed, why: started.skipped ? "skipped" : "unreachable" });
        fallback = attempt;
        continue;
      }"""

# The boss block is the **last** one (line ~785); the same two lines appear in four other scenarios,
# so the anchor is the pair together with `row.done = true` -- unique to this one.
TAIL_OLD = """      row.done = true;
    }
    row.ms = Math.round(performance.now() - t0);
    out.scenarios.push(row);"""

TAIL_NEW = """      attempt.done = true;
      attempt.ms = Math.round(performance.now() - t0);
      attempts.push({
        seed: attempt.seed,
        actAfter: attempt.actAfter,
        hpAfter: attempt.hpAfter,
        potionOpened: attempt.potionOpened,
        potionGranted: attempt.potionGranted,
      });
      fallback = attempt;
      // Both claims at once: the act moved on **and** the §161.7 anchor ran for real.
      const anchored = attempt.potionGranted === 0 && (attempt.potionOpened || 0) > 0
        && attempt.potionAnswered === true;
      if (attempt.actAfter === 2 && anchored) {
        row = attempt;
        break;
      }
    }
    if (!row) {
      // Nothing passed, so the **last** attempt is the one reported: its dump is what a red gate has
      // to explain itself with, and "no row at all" explains nothing.
      row = fallback || { name: "boss", ok: false, skipped: false, ms: 0, seed: null };
    }
    row.attempts = attempts;
    row.tries = attempts.length;
    row.ms = Math.round(performance.now() - t0);
    out.scenarios.push(row);"""


def main():
    # §2b, tenth time: this text is injected into a **template literal**, so a backtick in a comment
    # ends the literal and the whole module becomes a syntax error. Guard it here instead of
    # discovering it from `node --check` every time.
    for name, block in (("HEADER_NEW", HEADER_NEW), ("TAIL_NEW", TAIL_NEW)):
        assert "`" not in block, "%s contains a backtick (it lands inside a template literal)" % name
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(HEADER_OLD) == 1, ("header", text.count(HEADER_OLD))
    assert text.count(HEADER_OLD) == 1, ("header", text.count(HEADER_OLD))
    assert text.rindex(TAIL_OLD) > text.index(HEADER_OLD), "the tail must follow the header"

    # Everything between the two anchors is the boss body; inside it `row` becomes `attempt`.
    start = text.index(HEADER_OLD)
    # The tail text appears in five scenarios; the boss one is the **last**.
    end = text.rindex(TAIL_OLD)
    body = text[start + len(HEADER_OLD):end]
    # `row.` only where it is the block's own variable -- the body has no other `row` (checked).
    assert "const row" not in body
    body = re.sub(r"\brow\.", "attempt.", body)

    patched = text[:start] + HEADER_NEW + body + TAIL_NEW + text[end + len(TAIL_OLD):]
    # The old tail's closing brace of `if (started.ok) {` was inside TAIL_OLD; the loop body must not
    # keep a stray one. Count braces in the result as a cheap structural check.
    io.open(PATH, "w", encoding="utf-8", newline="").write(patched)
    print("boss scenario now retries:", patched.count("for (const seed of BOSS_SEEDS)"))


if __name__ == "__main__":
    main()
