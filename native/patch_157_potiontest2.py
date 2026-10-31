"""§157: the potion content test learns the eleventh potion and the `max_hp` shape."""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-core\src\content.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()


def replace_once(old, new, why):
    global source
    if old not in source:
        raise SystemExit("anchor missing: " + why)
    source = source.replace(old, new, 1)


replace_once(
    """        assert_eq!(
            content.potion_count(),
            10,
            "ten potions (§152: act 1's four, plus six more across the acts)"
        );""",
    """        assert_eq!(
            content.potion_count(),
            11,
            "eleven potions (§152's ten plus Fruit Juice, §157: the rare band had nothing in it)"
        );""",
    "potion count",
)

replace_once(
    """                    "combat_status",
                    "combat_status_target",
                ]
                .contains(&kind),""",
    """                    "combat_status",
                    "combat_status_target",
                    // §157: the one effect about the **run** rather than the fight.
                    "max_hp",
                ]
                .contains(&kind),""",
    "potion kinds",
)

replace_once(
    """                "weak_potion",
            ]
        );""",
    """                "weak_potion",
                "fruit_juice",
            ]
        );""",
    "potion ids",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("potion test updated")
