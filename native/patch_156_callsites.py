"""§156: fix the `roll_reward` call sites in `rd-run`'s tests for the two new pool types.

The relic pool in the elite test becomes `PoolRelic` (with rarities, so the weighted pick is
exercised), and the potion pools in the three potion tests become `PoolPotion`.
"""

import io
import re

PATH = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

# the relic pool used by the elite test
OLD = """        let relics = ["burning_blood", "anchor", "vajra"];"""
NEW = """        let relics = [
            PoolRelic {
                id: "burning_blood",
                rarity: Rarity::Common,
            },
            PoolRelic {
                id: "vajra",
                rarity: Rarity::Common,
            },
            PoolRelic {
                id: "thread_and_needle",
                rarity: Rarity::Rare,
            },
        ];"""
if OLD not in source:
    raise SystemExit("relic pool anchor missing")
source = source.replace(OLD, NEW, 1)

# `relics.contains(&offered.as_str())` no longer type-checks: compare against the ids.
OLD2 = """        assert!(
            relics.contains(&offered.as_str()),
            "{offered} is not in the pool"
        );"""
NEW2 = """        assert!(
            relics.iter().any(|entry| entry.id == offered),
            "{offered} is not in the pool"
        );"""
if OLD2 in source:
    source = source.replace(OLD2, NEW2, 1)

OLD3 = """        for relic in relics {
            run.push_relic(relic).expect("grant");
        }"""
NEW3 = """        for relic in relics.iter().map(|entry| entry.id) {
            run.push_relic(relic).expect("grant");
        }"""
if OLD3 in source:
    source = source.replace(OLD3, NEW3, 1)

# the potion pools in the three potion tests
OLD4 = """        let pool = ["fire_potion", "block_potion", "energy_potion"];"""
NEW4 = """        let pool = [
            PoolPotion {
                id: "fire_potion",
                rarity: Rarity::Common,
            },
            PoolPotion {
                id: "block_potion",
                rarity: Rarity::Common,
            },
            PoolPotion {
                id: "energy_potion",
                rarity: Rarity::Uncommon,
            },
        ];"""
count = source.count(OLD4)
source = source.replace(OLD4, NEW4)
print("potion pool literal replaced:", count)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("call sites patched")
