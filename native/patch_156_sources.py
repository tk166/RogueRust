"""§156: the chest and the shop use the weighted `pick_relic` too.

Three sources now share **one** function (`pick_relic`): chest, shop shelf, elite/boss reward. They
already shared the "never a second copy of a held relic" filter (§145); §156 adds "draw the rarity band
by weight" and the only way three sources stay in step is one function.

`relic_candidates` (which produced *indices*) is deleted: it existed to be shared by two callers, and
both now go through `pick_relic`.
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


# ---- 1. the chest ------------------------------------------------------------------------------
replace_once(
    """        let relic = {
            let mut available = [0usize; MAX_POOL];
            let count = self.relic_candidates(relic_pool, &mut available);
            if count == 0 {
                None
            } else {
                let index = self.rng.roll(RunStream::Chest, count as u32)? as usize;
                let Some(&slot) = available.get(index) else {
                    return Err(RunError::EmptyPool("relics"));
                };
                let id = RunId::new(relic_pool[slot]).map_err(|_| RunError::BadId)?;
                self.push_relic(relic_pool[slot])?;
                Some(id)
            }
        };""",
    """        let relic = {
            // §156: the same weighted draw as an elite reward, and the same "not one you hold".
            let picked = self.pick_relic(RunStream::Chest, relic_pool)?;
            if picked.as_str().is_empty() {
                None
            } else {
                self.push_relic(picked.as_str())?;
                Some(picked)
            }
        };""",
    "chest",
)

# ---- 2. the shop shelf -------------------------------------------------------------------------
replace_once(
    """        // §145: the merchant also refuses to sell you something you already wear (same filter as
        // the chest — one rule, one helper).
        let mut available = [0usize; MAX_POOL];
        let candidates = self.relic_candidates(relic_pool, &mut available);
        let relics = MAX_SHOP_RELICS.min(candidates);
        for (slot, source) in available.iter().take(relics).enumerate() {
            let index = *source;
            let Some(id) = relic_pool.get(index) else {
                return Err(RunError::EmptyPool("relics"));
            };
            // Common 143–157.
            let price = 143 + self.rng.roll(RunStream::Shop, 15)? as i32;
            self.shop.relics[slot] = Offer {
                id: RunId::new(id).map_err(|_| RunError::BadId)?,
                price,
            };
        }
        self.shop.relics_len = relics as u8;""",
    """        // §145/§156: the merchant refuses to sell what you already wear, and draws by rarity weight
        // (both via `pick_relic`, the one function the chest and the elite reward share).
        for slot in 0..MAX_SHOP_RELICS {
            let picked = self.pick_relic(RunStream::Shop, relic_pool)?;
            if picked.as_str().is_empty() {
                break;
            }
            // Common 143–157.
            let price = 143 + self.rng.roll(RunStream::Shop, 15)? as i32;
            self.shop.relics[slot] = Offer {
                id: picked,
                price,
            };
            self.shop.relics_len = (slot + 1) as u8;
        }""",
    "shop",
)

# ---- 3. delete the now-unused index helper -----------------------------------------------------
START = "    /// The indices in `pool` that name a relic the run **does not already hold** (§145)."
END = "    /// Buy the card in `slot`."
start = source.find(START)
end = source.find(END)
if start < 0 or end < 0:
    raise SystemExit("relic_candidates block not found")
source = source[:start] + source[end:]

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("chest + shop share pick_relic; relic_candidates removed")
