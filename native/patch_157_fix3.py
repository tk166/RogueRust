"""§157: the two remaining test fixes.

* capacity: the relic list is already full by the time the potion part runs, so `push_relic("potion_belt")`
  fails with `Capacity` -- a second, fresh run for the potion half.
* chance walk: the potion has to be **dropped while the pending state allows it**, so the belt is
  drained at the *top* of each iteration (after `skip_reward`), not right after the roll.
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


# ---- capacity: a second run for the potion half ------------------------------------------------
replace_once(
    """        // Potions: the **rule** is three slots (`inv:§9.3`, §157), even though the storage is five
        // so that `potion_belt` can hand out two more.
        for _ in 0..BASE_POTION_SLOTS {""",
    """        // Potions, on a **fresh** run: this one's relic list is already full, so `potion_belt`
        // could not be granted here. The rule is three slots (`inv:§9.3`, §157) even though the
        // storage is five, so that the belt relic can hand out two more.
        let mut run = ironclad();
        for _ in 0..BASE_POTION_SLOTS {""",
    "capacity fresh run",
)

# ---- the chance walk ---------------------------------------------------------------------------
replace_once(
    """        for _ in 0..12 {
            run.skip_reward().ok();
            let before = run.potion_drop_chance();
            run.roll_reward(&pool, &[], &[], FightKind::Normal)
                .expect("a reward");
            let offered = run.reward_potion().is_some();
            if offered {
                // Take it and throw it away: a **full** belt suppresses the offer while the drop
                // still counts (the wiki's Colosseum note), and then "offered" no longer means
                // "dropped".
                run.take_potion().expect("take it");
                let _ = run.drop_potion(0);
            }
            let after = run.potion_drop_chance();""",
    """        for _ in 0..12 {
            run.skip_reward().ok();
            // Drain the belt first: a **full** belt suppresses the offer while the drop still counts
            // (the wiki's Colosseum note), and then "offered" would stop meaning "dropped". Dropping
            // needs `Pending::None`, which `skip_reward` just gave us.
            while !run.potions().is_empty() {
                let _ = run.drop_potion(0);
            }
            let before = run.potion_drop_chance();
            run.roll_reward(&pool, &[], &[], FightKind::Normal)
                .expect("a reward");
            let offered = run.reward_potion().is_some();
            let after = run.potion_drop_chance();""",
    "chance walk drain",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("fixed")
