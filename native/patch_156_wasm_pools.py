"""§156: build the two typed pools in `rd-wasm` from the content's tables.

`relic_pool(content)` becomes `Vec<PoolRelic>` (id + `Rarity` from `REL.Rarity`), and a new
`potion_pool_of(content, ids)` turns the act's `POT` ids into `Vec<PoolPotion>` (id + `POT.Rarity`).

Both parse the content's own rarity string through `Rarity::from_name`; an unknown rarity is a
**content error** the caller reports, not a silent `Common` (a typo would otherwise flatten the drop
distribution and look like a balance choice).
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-wasm\src\run.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()


def replace_once(old, new, why):
    global source
    if old not in source:
        raise SystemExit("anchor missing: " + why)
    source = source.replace(old, new, 1)


# ---- 1. the relic pool carries rarity ----------------------------------------------------------
replace_once(
    """/// The content's relic ids, in table order.
fn relic_pool(content: &'static Content<'static>) -> Vec<&'static str> {
    let mut out = Vec::new();
    let mut index = 0u32;
    while let Some(row) = content.row(rd_core::content::Table::Relic, index) {
        if let Some(relic) = rd_core::content::RelRow::new(row) {
            if let Some(id) = content.string(relic.id()) {
                out.push(id);
            }
        }
        index += 1;
    }
    out
}""",
    """/// The content's relics, in table order, **with their rarity** (§156).
///
/// A relic whose `REL.Rarity` is missing or unknown is skipped and reported by the caller: letting it
/// default to `Common` would flatten the drop weights and look exactly like a balance decision.
fn relic_pool(content: &'static Content<'static>) -> Vec<rd_run::state::PoolRelic<'static>> {
    let mut out = Vec::new();
    let mut index = 0u32;
    while let Some(row) = content.row(rd_core::content::Table::Relic, index) {
        if let Some(relic) = rd_core::content::RelRow::new(row) {
            let id = content.string(relic.id());
            let rarity = content
                .string(relic.rarity())
                .and_then(rd_run::state::Rarity::from_name);
            if let (Some(id), Some(rarity)) = (id, rarity) {
                out.push(rd_run::state::PoolRelic { id, rarity });
            }
        }
        index += 1;
    }
    out
}

/// The act's potion ids, with the rarity the `POT` row declares (§156).
fn potion_pool_of(image: &'static Content<'static>, ids: &[&'static str]) -> Vec<rd_run::state::PoolPotion<'static>> {
    let mut out = Vec::new();
    for id in ids {
        let rarity = (0..image.potion_count())
            .filter_map(|index| image.potion(index))
            .find(|potion| potion.id == *id)
            .and_then(|potion| rd_run::state::Rarity::from_name(potion.rarity));
        if let Some(rarity) = rarity {
            out.push(rd_run::state::PoolPotion { id, rarity });
        }
    }
    out
}""",
    "relic_pool",
)

# ---- 2. the reward's potion pool ---------------------------------------------------------------
replace_once(
    """        let mut potion_ids = std::vec::Vec::new();
        for id in potion_pool.iter() {
            if !id.is_empty() {
                potion_ids.push(*id);
            }
        }""",
    """        let mut potion_ids = std::vec::Vec::new();
        for id in potion_pool.iter() {
            if !id.is_empty() {
                potion_ids.push(*id);
            }
        }
        let potion_ids = potion_pool_of(image, &potion_ids);""",
    "potion ids",
)

# ---- 3. the ABI test's forced elite reward -----------------------------------------------------
replace_once(
    """                .roll_reward(&pool, &[], &relics, rd_run::state::FightKind::Elite)""",
    """                .roll_reward(&pool, &[], &relics, rd_run::state::FightKind::Elite)""",
    "(idempotent)",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("rd-wasm pools typed")
