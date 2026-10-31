"""§157: the last three tests that assumed the old constants.

* `capacity_is_an_error_not_a_truncation` filled `MAX_RUN_POTIONS` potions and expected the next to
  fail. `MAX_RUN_POTIONS` is now the **storage** (5); the rule is `potion_slots()` (3). The test fills
  to the rule and then proves the belt relic raises it -- which is the interesting half anyway.
* `an_event_can_give_a_relic_only_if_the_kernel_can_run_it` uses `golden_idol` as its "unimplemented"
  fixture; §157 implements it.
* `the_potion_chance_walks_the_wikis_ten_percent` compared the chance move against *"was a potion
  offered"*, but a **full belt** suppresses the offer while the drop still counts (the wiki's own
  Colosseum note). It now empties the belt after each offer, so the two agree.
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


# ---- capacity ----------------------------------------------------------------------------------
replace_once(
    """        // Potions: the belt is three slots (`inv:§9.3`).
        for _ in 0..MAX_RUN_POTIONS {
            run.push_potion("fire_potion").unwrap();
        }
        assert_eq!(run.push_potion("fire_potion"), Err(RunError::Capacity));""",
    """        // Potions: the **rule** is three slots (`inv:§9.3`, §157), even though the storage is five
        // so that `potion_belt` can hand out two more.
        for _ in 0..BASE_POTION_SLOTS {
            run.push_potion("fire_potion").unwrap();
        }
        assert_eq!(run.push_potion("fire_potion"), Err(RunError::Capacity));
        run.push_relic("potion_belt").expect("the belt");
        for _ in 0..2 {
            run.push_potion("fire_potion").expect("the belt's two slots");
        }
        assert_eq!(
            run.push_potion("fire_potion"),
            Err(RunError::Capacity),
            "and the storage bound still holds"
        );""",
    "capacity test",
)

# ---- the event's unimplemented relic ----------------------------------------------------------
if 'resolve_event(EventEffect::GainRelic, Some("golden_idol")' in source:
    source = source.replace(
        'resolve_event(EventEffect::GainRelic, Some("golden_idol")',
        'resolve_event(EventEffect::GainRelic, Some("no_such_relic")',
    )
    print("event fixture renamed")

# ---- the chance walk: keep the belt empty so "offered" == "dropped" ---------------------------
replace_once(
    """            let offered = run.reward_potion().is_some();
            let after = run.potion_drop_chance();""",
    """            let offered = run.reward_potion().is_some();
            if offered {
                // Take it and throw it away: a **full** belt suppresses the offer while the drop
                // still counts (the wiki's Colosseum note), and then "offered" no longer means
                // "dropped".
                run.take_potion().expect("take it");
                let _ = run.drop_potion(0);
            }
            let after = run.potion_drop_chance();""",
    "chance walk",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("three tests fixed")
