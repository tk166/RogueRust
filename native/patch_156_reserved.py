"""§156: `pick_relic` must know what the shop already shelved.

The shop stocks three relics from one pool, and a picked relic is **not** in the belt until it is
bought -- so "skip the ones you hold" was not enough and the same relic appeared three times. The fix
is an explicit `reserved` list: the shop passes what it has already put out, everything else passes
an empty slice.
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


# 1. the signature + the filter
replace_once(
    """    pub fn pick_relic(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
    ) -> Result<RunId, RunError> {""",
    """    pub fn pick_relic(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
    ) -> Result<RunId, RunError> {
        self.pick_relic_avoiding(stream, pool, &[])
    }

    /// [`Self::pick_relic`], also skipping `reserved` -- the relics a caller has already put on a
    /// shelf but not yet sold (the shop stocks three, and a picked relic is not in the belt yet).
    pub fn pick_relic_avoiding(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
    ) -> Result<RunId, RunError> {""",
    "pick_relic split",
)

replace_once(
    """            if self.relics().iter().any(|held| held.as_str() == entry.id) {
                continue;
            }""",
    """            if self.relics().iter().any(|held| held.as_str() == entry.id)
                || reserved.iter().any(|taken| taken.as_str() == entry.id)
            {
                continue;
            }""",
    "held filter",
)

# 2. the shop passes what it has shelved
replace_once(
    """        for slot in 0..MAX_SHOP_RELICS {
            let picked = self.pick_relic(RunStream::Shop, relic_pool)?;""",
    """        let mut shelved: [RunId; MAX_SHOP_RELICS] = [RunId::EMPTY; MAX_SHOP_RELICS];
        for slot in 0..MAX_SHOP_RELICS {
            let picked = self.pick_relic_avoiding(
                RunStream::Shop,
                relic_pool,
                &shelved[..slot],
            )?;""",
    "shop reserved",
)

replace_once(
    """            self.shop.relics[slot] = Offer {
                id: picked,
                price,
            };
            self.shop.relics_len = (slot + 1) as u8;""",
    """            self.shop.relics[slot] = Offer {
                id: picked,
                price,
            };
            shelved[slot] = picked;
            self.shop.relics_len = (slot + 1) as u8;""",
    "shop shelved",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("pick_relic_avoiding wired")
