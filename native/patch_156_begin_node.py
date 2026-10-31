"""§156: `begin_node` / `open_chest` / the shop take the typed relic pool too.

Both of them already filtered held relics (`relic_candidates`); now they also **weight by rarity**, so
"the chest gave me a rare" and "the elite gave me a rare" are the same distribution (§156) instead of
"the chest is uniform and the elite is uniform".
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


# ---- begin_node --------------------------------------------------------------------------------
replace_once(
    """    pub fn begin_node(
        &mut self,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[&str],
    ) -> Result<i32, RunError> {""",
    """    pub fn begin_node(
        &mut self,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<i32, RunError> {""",
    "begin_node signature",
)

# ---- the shop's relic offer: weighted ----------------------------------------------------------
OLD_SHOP = """        let mut available = [0usize; MAX_POOL];
        let count = self.relic_candidates(relic_pool, &mut available);"""
NEW_SHOP = """        // §156: a shop relic is drawn by rarity weight, like a chest's.
        let mut available = [0usize; MAX_POOL];
        let count = self.relic_candidates_ids(relic_pool, &mut available);"""
if OLD_SHOP in source:
    source = source.replace(OLD_SHOP, NEW_SHOP)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("begin_node typed")
