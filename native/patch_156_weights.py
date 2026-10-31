"""§156: one weighted-by-rarity helper, used by both relic and potion drops.

StS draws a **rarity band** first and then a uniform entry inside it:

    relic   50 / 33 / 17   (Common / Uncommon / Rare)
    potion  65 / 25 / 10

That is not the same as weighting each entry by its rarity (a band with one relic would get a third of
the picks), and it degrades correctly: `pick_rarity` re-normalises over the bands that are **still
available**, so "no rares left in the pool" shifts the mass instead of silently returning None.

The relic pool becomes `&[PoolRelic]` (id + rarity), mirroring `PoolCard` -- the run layer must be able
to see the rarity, and passing a `&[&str]` plus a parallel table is how two lists drift apart.
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


# ---- 1. PoolRelic + the weights ----------------------------------------------------------------
replace_once(
    """/// Which fight paid. `inv:§5` / `inv:§3.5` differ per kind in **both** gold and rarity.""",
    """/// A relic the content offers: what it is, and how rare (§156).
///
/// Same shape as [`PoolCard`] and for the same reason: the drop tables weight on rarity, so the run
/// layer has to see it. A parallel `&[Rarity]` beside a `&[&str]` is how the two get out of step.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PoolRelic<'a> {
    /// The definition id.
    pub id: &'a str,
    /// Its rarity, from the content's `REL.Rarity`.
    pub rarity: Rarity,
}

/// The wiki's relic drop weights: Common 50%, Uncommon 33%, Rare 17%.
pub const RELIC_RARITY_WEIGHTS: [(Rarity, u32); 3] = [
    (Rarity::Common, 50),
    (Rarity::Uncommon, 33),
    (Rarity::Rare, 17),
];

/// The wiki's potion drop weights: Common 65%, Uncommon 25%, Rare 10%.
pub const POTION_RARITY_WEIGHTS: [(Rarity, u32); 3] = [
    (Rarity::Common, 65),
    (Rarity::Uncommon, 25),
    (Rarity::Rare, 10),
];

/// Which fight paid. `inv:§5` / `inv:§3.5` differ per kind in **both** gold and rarity.""",
    "PoolRelic",
)

# ---- 2. the helper (next to the other pick helpers) -------------------------------------------
replace_once(
    """    /// The indices in `pool` that name a relic the run **does not already hold** (§145).""",
    """    /// Draw a rarity band by weight, re-normalised over the bands that still have entries
    /// (§156). `None` = no band has an entry.
    fn pick_rarity(
        &mut self,
        stream: RunStream,
        weights: &[(Rarity, u32)],
        present: &[Rarity],
    ) -> Result<Option<Rarity>, RunError> {
        let mut total = 0u32;
        for (rarity, weight) in weights {
            if present.contains(rarity) {
                total += *weight;
            }
        }
        if total == 0 {
            return Ok(None);
        }
        let mut roll = self.rng.roll(stream, total)?;
        for (rarity, weight) in weights {
            if !present.contains(rarity) {
                continue;
            }
            if roll < *weight {
                return Ok(Some(*rarity));
            }
            roll -= *weight;
        }
        Ok(None)
    }

    /// The indices in `pool` that name a relic the run **does not already hold** (§145).""",
    "pick_rarity",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("PoolRelic + pick_rarity added")
