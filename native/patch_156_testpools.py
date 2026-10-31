"""§156: `begin_node`'s inner call and the tests' relic-pool literals.

The test literals (`RELICS`, and a `let pool = [...]` in the chest/shop tests) become `PoolRelic`s so
the weighted pick is exercised there too. This is the last of the typing; after this the pools are one
shape everywhere.
"""

import io
import re

PATH = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()


def replace_once(old, new, why):
    global source
    if old not in source:
        raise SystemExit("anchor missing: " + why)
    source = source.replace(old, new, 1)


# 1. `begin_node` passes the typed pool through (the signature was fixed; the body had a &str list).
replace_once(
    """                self.stock_shop(card_pool, relic_pool)?;""",
    """                self.stock_shop(card_pool, relic_pool)?;""",
    "(idempotent)",
)

# 2. the shared test literal
source = re.sub(
    r'const RELICS: \[&str; 1\] = \["burning_blood"\];',
    'const RELICS: [PoolRelic<"static>; 1] = [PoolRelic {\n        id: "burning_blood",\n        rarity: Rarity::Common,\n    }];',
    source,
)
# the const generic above needs a real lifetime: `PoolRelic<'static>`
source = source.replace('PoolRelic<"static>', "PoolRelic<'static>")

# 3. the chest/shop test locals: `let pool = ["burning_blood", ...]`
def to_pool(match):
    ids = re.findall(r'"([a-z_]+)"', match.group(0))
    entries = ",\n".join(
        '        PoolRelic {\n            id: "%s",\n            rarity: Rarity::Common,\n        }' % i
        for i in ids
    )
    return "let pool = [\n%s,\n    ];" % entries

source = re.sub(r"let pool = \[(?:\s*\"[a-z_]+\",?)+\s*\];", to_pool, source)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("test pools typed")
