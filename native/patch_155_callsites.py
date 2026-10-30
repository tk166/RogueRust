"""§155: update the `roll_reward` call sites (the relic pool is a new argument).

Ten call sites, all in `rd-run`'s tests: they pass `&[]` for the potion pool, so they pass `&[]` for
the relic pool too unless the test is about relics.
"""

import io
import re

PATH = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

# `roll_reward(<cards>, <potions>, FightKind::X)` -> `roll_reward(<cards>, <potions>, &[], FightKind::X)`
pattern = re.compile(r"roll_reward\((&[^,]+),\s*(&[^,]+),\s*(FightKind::\w+)\)")
source, count = pattern.subn(r"roll_reward(\1, \2, &[], \3)", source)
print("call sites updated:", count)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
