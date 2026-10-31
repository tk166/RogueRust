"""§156: use the weights at the three places a relic or potion is drawn.

* `roll_reward` -- the elite/boss relic (`PoolRelic` now) and the potion drop;
* `relic_candidates` -- unchanged (it filters held relics); the *pick* on top of it becomes weighted;
* chest (`open_chest`) and shop (`ShopStock`) -- the same weighted pick, so "a chest gave you a rare"
  and "an elite gave you a rare" are the same distribution.

Signature changes:
    roll_reward(cards, potions, relics, kind)  ->  relics: &[PoolRelic<'_>]
    potions stays `&[&str]` but gains a parallel rarity slice? NO -- see below.

For potions the run layer gets `&[PoolPotion]` too: the same "id + rarity" shape, for the same reason
(and the content's `POT.Rarity` is already there).
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


# ---- a matching struct for potions -------------------------------------------------------------
replace_once(
    """/// The wiki's relic drop weights: Common 50%, Uncommon 33%, Rare 17%.""",
    """/// A potion the content offers: what it is, and how rare (§156). See [`PoolRelic`].
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PoolPotion<'a> {
    /// The definition id.
    pub id: &'a str,
    /// Its rarity, from the content's `POT.Rarity`.
    pub rarity: Rarity,
}

/// The wiki's relic drop weights: Common 50%, Uncommon 33%, Rare 17%.""",
    "PoolPotion",
)

# ---- roll_reward: the two pools ----------------------------------------------------------------
replace_once(
    """    pub fn roll_reward(
        &mut self,
        card_pool: &[PoolCard<'_>],
        potion_pool: &[&str],
        relic_pool: &[&str],
        kind: FightKind,
    ) -> Result<(), RunError> {""",
    """    pub fn roll_reward(
        &mut self,
        card_pool: &[PoolCard<'_>],
        potion_pool: &[PoolPotion<'_>],
        relic_pool: &[PoolRelic<'_>],
        kind: FightKind,
    ) -> Result<(), RunError> {""",
    "roll_reward signature",
)

replace_once(
    """        // Which potion: the content's own list, picked on the same stream. `potion_pool` is empty
        // when the image declares none (roguedeck), and then no potion is offered at all.
        let potion = if drop && !potion_pool.is_empty() {
            let index = self.rng.roll(RunStream::Potion, potion_pool.len() as u32)? as usize;
            RunId::new(potion_pool[index]).map_err(|_| RunError::BadId)?
        } else {
            RunId::EMPTY
        };""",
    """        // Which potion: the content's own list, **weighted by rarity** (§156). `potion_pool` is
        // empty when the image declares none (roguedeck), and then no potion is offered at all.
        let potion = if drop && !potion_pool.is_empty() {
            let mut rarities: [Rarity; MAX_POOL] = [Rarity::Common; MAX_POOL];
            for (slot, entry) in potion_pool.iter().take(MAX_POOL).enumerate() {
                rarities[slot] = entry.rarity;
            }
            let present = &rarities[..potion_pool.len().min(MAX_POOL)];
            let band = self.pick_rarity(RunStream::Potion, &POTION_RARITY_WEIGHTS, present)?;
            let band = band.unwrap_or(potion_pool[0].rarity);
            let mut eligible = [0usize; MAX_POOL];
            let mut count = 0usize;
            for (slot, entry) in potion_pool.iter().take(MAX_POOL).enumerate() {
                if entry.rarity == band {
                    eligible[count] = slot;
                    count += 1;
                }
            }
            let pool: &[usize] = if count == 0 {
                &[]
            } else {
                &eligible[..count]
            };
            let chosen = if pool.is_empty() {
                0
            } else {
                let pick = self.rng.roll(RunStream::Potion, pool.len() as u32)? as usize;
                pool[pick]
            };
            RunId::new(potion_pool[chosen].id).map_err(|_| RunError::BadId)?
        } else {
            RunId::EMPTY
        };""",
    "potion pick",
)

replace_once(
    """        let mut relic = RunId::EMPTY;
        if matches!(kind, FightKind::Elite | FightKind::Boss) {
            // Same filter as the chest and the shop (§145): never a second copy of a held relic.
            let mut candidates = [0usize; MAX_POOL];
            let count = self.relic_candidates(relic_pool, &mut candidates);
            if count > 0 {
                let pick = self.rng.roll(RunStream::Reward, count as u32)? as usize;
                let Some(cell) = candidates.get(pick).copied() else {
                    return Err(RunError::BadId);
                };
                let Some(id) = relic_pool.get(cell) else {
                    return Err(RunError::BadId);
                };
                relic = RunId::new(id).map_err(|_| RunError::BadId)?;
            }
        }""",
    """        let mut relic = RunId::EMPTY;
        if matches!(kind, FightKind::Elite | FightKind::Boss) {
            relic = self.pick_relic(RunStream::Reward, relic_pool)?;
        }""",
    "relic pick",
)

# ---- the shared relic pick --------------------------------------------------------------------
replace_once(
    """    /// The indices in `pool` that name a relic the run **does not already hold** (§145).""",
    """    /// Draw a relic from `pool` by **rarity weight** (§156), skipping relics already held.
    ///
    /// One helper for the chest, the shop and the elite reward: before this each of them picked
    /// uniformly, so "an elite pays a rare more often than a chest" was not true even in principle.
    pub fn pick_relic(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
    ) -> Result<RunId, RunError> {
        // Never a second copy of a held relic (§145) -- the filter every source shares.
        let mut candidates = [0usize; MAX_POOL];
        let mut rarities = [Rarity::Common; MAX_POOL];
        let mut count = 0usize;
        for (slot, entry) in pool.iter().take(MAX_POOL).enumerate() {
            if self.relics().iter().any(|held| held.as_str() == entry.id) {
                continue;
            }
            candidates[count] = slot;
            rarities[count] = entry.rarity;
            count += 1;
        }
        if count == 0 {
            return Ok(RunId::EMPTY);
        }
        let present = &rarities[..count];
        let band = self
            .pick_rarity(stream, &RELIC_RARITY_WEIGHTS, present)?
            .unwrap_or(pool[candidates[0]].rarity);
        let mut band_slots = [0usize; MAX_POOL];
        let mut band_count = 0usize;
        for slot in &candidates[..count] {
            if pool[*slot].rarity == band {
                band_slots[band_count] = *slot;
                band_count += 1;
            }
        }
        let chosen = if band_count == 0 {
            candidates[0]
        } else {
            let pick = self.rng.roll(stream, band_count as u32)? as usize;
            band_slots[pick]
        };
        RunId::new(pool[chosen].id).map_err(|_| RunError::BadId)
    }

    /// The indices in `pool` that name a relic the run **does not already hold** (§145).""",
    "pick_relic",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("weighted picks wired")
