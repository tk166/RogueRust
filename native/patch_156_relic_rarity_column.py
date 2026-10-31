"""§156: `Rarity` on the relic row, so relic drops can be weighted like potions already are.

`REL_ROW` was `{Id, DisplayName, RunPrograms, CombatRules, extra}` -- five cells in a 12-byte row, so
there is room for a sixth without changing the stride (`rdcf_verify` checks count x stride against
the section bytes, and the stride stays 12).

The alternative was a rarity table in the run layer next to `relic_effect()`. That is where the
*effects* live (they are behaviour), but rarity is **content** -- and potions already carry it in
`POT.Rarity`. Two places for one concept is how the two drift apart.
"""

import io

RDCFMT = r"D:\Vibe\sts-tui\tools\contentc\rdcfmt.py"
CONTENT = r"D:\Vibe\sts-tui\kernel\rd-core\src\content.rs"

with io.open(RDCFMT, encoding="utf-8") as handle:
    fmt = handle.read()

OLD = """REL_ROW = [
    ("Id", F_STR, 0), ("DisplayName", F_STR, 0), ("RunPrograms", F_TERM, 0),
    ("CombatRules", F_TERM, 0), ("extra", F_TERM, 0),
]"""
NEW = """REL_ROW = [
    ("Id", F_STR, 0), ("DisplayName", F_STR, 0), ("RunPrograms", F_TERM, 0),
    ("CombatRules", F_TERM, 0),
    # §156: `Common` / `Uncommon` / `Rare` -- what the drop tables weight on (50/33/17, the wiki's
    # numbers). The row is 12 bytes = six `u16` cells, so this is a sixth cell, not a longer row.
    ("Rarity", F_STR, 0), ("extra", F_TERM, 0),
]"""
if OLD not in fmt:
    raise SystemExit("REL_ROW anchor missing")
fmt = fmt.replace(OLD, NEW, 1)
with io.open(RDCFMT, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(fmt)
print("rdcfmt.REL_ROW: Rarity added")

with io.open(CONTENT, encoding="utf-8") as handle:
    source = handle.read()

OLD_MACRO = """    RelRow, Relic, REL_SCHEMA, 12, 5, {
        /// `Id`（串号）。
        ("Id", F_STR, 0) => id => 0,
        /// `DisplayName`（串号）。
        ("DisplayName", F_STR, 0) => display_name => 1,
        /// `RunPrograms`（term 句柄）。
        ("RunPrograms", F_TERM, 0) => run_programs => 2,
        /// `CombatRules`（term 句柄）。
        ("CombatRules", F_TERM, 0) => combat_rules => 3,
        /// schema 不认识的键（term 句柄）。
        ("extra", F_TERM, 0) => extra => 4,
    }"""
NEW_MACRO = """    RelRow, Relic, REL_SCHEMA, 12, 6, {
        /// `Id`（串号）。
        ("Id", F_STR, 0) => id => 0,
        /// `DisplayName`（串号）。
        ("DisplayName", F_STR, 0) => display_name => 1,
        /// `RunPrograms`（term 句柄）。
        ("RunPrograms", F_TERM, 0) => run_programs => 2,
        /// `CombatRules`（term 句柄）。
        ("CombatRules", F_TERM, 0) => combat_rules => 3,
        /// `Rarity`（§156：`Common` / `Uncommon` / `Rare`）。
        ("Rarity", F_STR, 0) => rarity => 4,
        /// schema 不认识的键（term 句柄）。
        ("extra", F_TERM, 0) => extra => 5,
    }"""
if OLD_MACRO not in source:
    raise SystemExit("REL macro anchor missing")
source = source.replace(OLD_MACRO, NEW_MACRO, 1)
with io.open(CONTENT, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("content.rs: REL row is 6 cells, same 12-byte stride")
