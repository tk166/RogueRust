"""§156: type `begin_node`'s relic pool and fix the two test filters that assumed `&str`."""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

PAIRS = [
    (
        """    pub fn begin_node(
        &mut self,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[&str],
    ) -> Result<crate::map::NodeKind, RunError> {""",
        """    pub fn begin_node(
        &mut self,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<crate::map::NodeKind, RunError> {""",
    ),
    (
        """                .filter(|id| !run.relics().iter().any(|held| held.as_str() == **id))""",
        """                .filter(|entry| !run.relics().iter().any(|held| held.as_str() == entry.id))""",
    ),
]

for old, new in PAIRS:
    if old not in source:
        raise SystemExit("anchor missing: " + old[:50])
    source = source.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("begin_node typed")
