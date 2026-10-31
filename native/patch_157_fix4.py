"""§157: two more test fixes.

* the chance-walk test rolled with an **empty potion pool**, so a rolled drop could not be offered and
  the "offer == drop" equivalence broke. It now passes a one-potion pool.
* the capacity test shadowed `run` with a fresh run, which lost the full deck the last assertion
  checks. The potion half gets its own binding.
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


# ---- the chance walk needs a pool --------------------------------------------------------------
replace_once(
    """        let mut run = RunState::new(31, 80, 0, &DECK).expect("a run");
        assert_eq!(run.potion_drop_chance(), POTION_DROP_START, "starts at 40");""",
    """        // A pool with one potion: with an **empty** pool a rolled drop cannot be offered, and then
        // "offered" stops meaning "rolled" (found the hard way).
        let potions = [PoolPotion {
            id: "fire_potion",
            rarity: Rarity::Common,
        }];
        let mut run = RunState::new(31, 80, 0, &DECK).expect("a run");
        assert_eq!(run.potion_drop_chance(), POTION_DROP_START, "starts at 40");""",
    "potion pool",
)

replace_once(
    """            run.roll_reward(&pool, &[], &[], FightKind::Normal)
                .expect("a reward");
            let offered = run.reward_potion().is_some();""",
    """            run.roll_reward(&pool, &potions, &[], FightKind::Normal)
                .expect("a reward");
            let offered = run.reward_potion().is_some();""",
    "chance roll with pool",
)
source = source.replace(
    """            let offered = run.reward_potion().is_some();
            if offered {
                // Take it and throw it away: a **full** belt suppresses the offer while the drop
                // still counts (the wiki's Colosseum note), and then "offered" no longer means
                // "dropped".
                run.take_potion().expect("take it");
                let _ = run.drop_potion(0);
            }""",
    """            let offered = run.reward_potion().is_some();""",
)

# ---- the capacity test: a separate binding -----------------------------------------------------
replace_once(
    """        let mut run = ironclad();
        for _ in 0..BASE_POTION_SLOTS {""",
    """        let mut potion_run = ironclad();
        for _ in 0..BASE_POTION_SLOTS {""",
    "capacity binding",
)
source = source.replace(
    """        assert_eq!(run.push_potion("fire_potion"), Err(RunError::Capacity));
        run.push_relic("potion_belt").expect("the belt");
        for _ in 0..2 {
            run.push_potion("fire_potion").expect("the belt's two slots");
        }
        assert_eq!(
            run.push_potion("fire_potion"),
            Err(RunError::Capacity),
            "and the storage bound still holds"
        );""",
    """        assert_eq!(potion_run.push_potion("fire_potion"), Err(RunError::Capacity));
        potion_run.push_relic("potion_belt").expect("the belt");
        for _ in 0..2 {
            potion_run.push_potion("fire_potion").expect("the belt's two slots");
        }
        assert_eq!(
            potion_run.push_potion("fire_potion"),
            Err(RunError::Capacity),
            "and the storage bound still holds"
        );""",
)
source = source.replace(
    """        for _ in 0..BASE_POTION_SLOTS {
            run.push_potion("fire_potion").unwrap();
        }""",
    """        for _ in 0..BASE_POTION_SLOTS {
            potion_run.push_potion("fire_potion").unwrap();
        }""",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("fixed")
