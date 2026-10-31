"""§157: `fruit_juice` belongs in **sorted** order in the potion-id assertion."""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-core\src\content.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()


def replace_once(old, new, why):
    global source
    if old not in source:
        raise SystemExit("anchor missing: " + why)
    source = source.replace(old, new, 1)


# remove the misplaced entry at the tail
replace_once(
    """                "weak_potion",
                "fruit_juice",
            ]""",
    """                "weak_potion",
            ]""",
    "tail",
)

# put it where sorted order wants it: after fire_potion
replace_once(
    """                "fire_potion",
                "regen_potion",""",
    """                "fire_potion",
                "fruit_juice",
                "regen_potion",""",
    "sorted position",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("sorted")
