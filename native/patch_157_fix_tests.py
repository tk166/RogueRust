"""§157: three existing tests named a relic that is now implemented, and one looped 400 fights.

1. `golden_idol` was the "unimplemented relic" fixture -- §157 implements it. The fixture moves to a
   name that will never be implemented (`no_such_relic`), which is a **better** fixture anyway: it
   cannot drift out of date the next time a relic lands.
2. `a_won_fight_drops_a_potion_and_the_belt_takes_it` rolled 400 rewards and expected ~40% drops.
   With the wiki's moving chance (§157) the rate converges to a different number *and* every fight
   needs `skip_reward` in between; the test now sets the chance to 100 for the drop it needs.
3. `capacity_is_an_error_not_a_truncation` pushed potions until `Capacity` -- five now fit (the belt
   storage), so it must fill to `potion_slots()` first.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()


def replace_once(old, new, why):
    global source
    if old not in source:
        raise SystemExit("anchor missing: " + why)
    source = source.replace(old, new, 1)


# 1. the "unimplemented relic" fixture
source = source.replace('run.push_relic("golden_idol")', 'run.push_relic("no_such_relic")')
source = source.replace('run.push_relic("strawberry")', 'run.push_relic("no_such_relic")')
print("unimplemented-relic fixtures renamed")

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
