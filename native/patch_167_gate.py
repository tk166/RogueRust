"""`INV_CARDS`: the six new Power rows (§161.7), with the facts the gate re-derives.

This dict is a per-card contract, not a list of ids: the gate re-reads each row's program and
checks that it produces exactly these facts. Adding a card here without the right number is a red.
"""
import io

PATH = "native/sts_content_check.py"

ANCHOR = """    "whirlwind": {"Cost": 0, "Tags": ["attack", "x_cost"],
                  "Facts": [("repeat", ("expr", "x.cost"), "damage", 5, "allEnemies")]},
}"""

NEW = """    "whirlwind": {"Cost": 0, "Tags": ["attack", "x_cost"],
                  "Facts": [("repeat", ("expr", "x.cost"), "damage", 5, "allEnemies")]},
    # §161.7: the three **Power** cards (inv:§2 rows 178/183/184). They exist so that
    # `choice_offered:power` has three cards to offer -- and every number here is the inventory's
    # second column (5->7, 2->3, 3->4), not a guess.
    #
    # ⚠️ These are the content's first cards whose whole effect is a **status that keeps working
    # after the card is played**. Two statuses had to be fixed for them to be honest:
    # `standard.metallicize` had no trigger at all, and `standard.combust`'s trigger skipped the
    # "lose 1 HP" its own description promises.
    "inflame": {"Cost": 1, "Tags": ["power"],
                "Facts": [("status", "standard.strength", 2, "source")]},
    "inflame+": {"Cost": 1, "Tags": ["power"],
                 "Facts": [("status", "standard.strength", 3, "source")]},
    "metallicize": {"Cost": 1, "Tags": ["power"],
                    "Facts": [("status", "standard.metallicize", 3, "source")]},
    "metallicize+": {"Cost": 1, "Tags": ["power"],
                     "Facts": [("status", "standard.metallicize", 4, "source")]},
    "combust": {"Cost": 1, "Tags": ["power"],
                "Facts": [("status", "standard.combust", 5, "source")]},
    "combust+": {"Cost": 1, "Tags": ["power"],
                 "Facts": [("status", "standard.combust", 7, "source")]},
}"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert '"inflame":' not in text, "already inserted"
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("INV_CARDS += 6 power rows")


if __name__ == "__main__":
    main()
