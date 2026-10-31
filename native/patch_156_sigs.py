"""§156: the last two signatures that still take `&[&str]` for the relic pool."""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

PAIRS = [
    (
        "    pub fn open_chest(&mut self, relic_pool: &[&str]) -> Result<ChestOutcome, RunError> {",
        "    pub fn open_chest(&mut self, relic_pool: &[PoolRelic<'_>]) -> Result<ChestOutcome, RunError> {",
    ),
    (
        "    fn stock_shop(&mut self, card_pool: &[PoolCard<'_>], relic_pool: &[&str]) -> Result<(), RunError> {",
        "    fn stock_shop(&mut self, card_pool: &[PoolCard<'_>], relic_pool: &[PoolRelic<'_>]) -> Result<(), RunError> {",
    ),
]

for old, new in PAIRS:
    if old not in source:
        raise SystemExit("anchor missing: " + old[:60])
    source = source.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("signatures typed")
