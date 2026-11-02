"""§173: teach the content gate the three new elites.

`native/sts_content_check.py` *is* the inventory contract (`docs/spec/sts-act1-inventory.md`, reduced to
data). Adding content therefore means adding it here too -- and the gate failing on `enc_lagavulin`
("not in the inventory's pool") is the gate doing its job, not an obstacle.

Six actions, one card (`wound`), three monsters, three encounters, and the two pool tables.
"""
import io

PATH = "native/sts_content_check.py"

# (1) the actions, with the facts the walker will produce (see `program_facts`).
OLD_ACTIONS_TAIL = '''    "gremlin_wizard.ultimate_blast": ("Attack", [
        ("damage", 25, "event"),
        # the AI turn counter is reset by the blast itself; it is the content-side
        # substitute for `intent.round` (there is none, see Notes.Deviations).
        ("counter", "gremlin_wizard_charges", 0, False, "source")]),
}'''

NEW_ACTIONS_TAIL = '''    "gremlin_wizard.ultimate_blast": ("Attack", [
        ("damage", 25, "event"),
        # the AI turn counter is reset by the blast itself; it is the content-side
        # substitute for `intent.round` (there is none, see Notes.Deviations).
        ("counter", "gremlin_wizard_charges", 0, False, "source")]),
    # §173: the three elites that bring the act-1 and act-2 pools up to the wiki's three each.
    # `Sleep` is an **empty** program on purpose: the turn is taken and nothing happens.
    "lagavulin.sleep": ("Unknown", []),
    "lagavulin.attack": ("Attack", [("damage", 18, "event")]),
    # Negative stacks: the wiki's Siphon Soul is "-1 Strength, -1 Dexterity".
    "lagavulin.siphon_soul": ("Debuff", [("status", "standard.strength", -1, "event"),
                                        ("status", "standard.dexterity", -1, "event")]),
    # "6×N damage, N = times Multi Stab was used this combat + 2" -- the bump then a repeat whose
    # count is `uses + 2`, so the `repeat` fact carries the count **expression**, not a number.
    "book_of_stabbing.multi_stab": ("Attack",
                                    [("counter", "book_stab_uses", ("expr", "add"), False, "source"),
                                     ("repeat", ("expr", "add"), ("damage", 6, "event"))]),
    "book_of_stabbing.big_stab": ("Attack", [("damage", 21, "event")]),
    "taskmaster.scouring_whip": ("Attack", [("damage", 7, "event"),
                                            ("card", "wound", 1, "DiscardPile", "event")]),
}'''

# (2) the card.
OLD_CARD = '''    "injury": {"Cost": 1, "Tags": ["curse", "unplayable", "junk"], "Facts": []},'''

NEW_CARD = '''    "injury": {"Cost": 1, "Tags": ["curse", "unplayable", "junk"], "Facts": []},
    # §173: the junk the act-2 elites hand out (Taskmaster's whip, and the Daggers that come later).
    # Same shape as `slimed`: a status card, unplayable, no program.
    "wound": {"Cost": 1, "Tags": ["status", "unplayable", "junk"], "Facts": []},'''

# (3) the monsters. `Lagavulin`'s cycle deliberately starts with `siphon_soul` so that round 4 --
# the first round after the three sleeps -- indexes `attack`, which is what the wiki says happens.
OLD_MONSTER = '''    ("gremlin_nob", 82, 86,
     ["gremlin_nob.bellow", "gremlin_nob.rush", "gremlin_nob.skull_bash"]),'''

NEW_MONSTER = '''    ("gremlin_nob", 82, 86,
     ["gremlin_nob.bellow", "gremlin_nob.rush", "gremlin_nob.skull_bash"]),
    # §173: the wiki's act-1 elite #2 and act-2 elites #2/#3.
    # Lagavulin: HP 109-111, Metallicize 8, Sleep for rounds 1-3 (`intent.round` rule), then
    # `siphon_soul`/`attack` alternating -- the order is chosen so round 4 is the Attack.
    ("lagavulin", 109, 111, ["lagavulin.siphon_soul", "lagavulin.attack"]),
    ("book_of_stabbing", 160, 164,
     ["book_of_stabbing.multi_stab", "book_of_stabbing.big_stab"]),
    ("taskmaster", 54, 60, ["taskmaster.scouring_whip"]),'''

# (4) the elite pool.
OLD_ELITE = '''    # §152: a second act-1 elite, so the elite node is not always the same fight.
    "enc_gremlin_nob": ["gremlin_nob"],
}'''

NEW_ELITE = '''    # §152: a second act-1 elite, so the elite node is not always the same fight.
    "enc_gremlin_nob": ["gremlin_nob"],
    # §173: the wiki's three-per-act elite pools. Act 1 gains Lagavulin, act 2 gains Book of
    # Stabbing and the Slavers trio (Taskmaster + Red Slaver + Blue Slaver, in that order -- the
    # order is the turn order).
    "enc_lagavulin": ["lagavulin"],
    "enc_book_of_stabbing": ["book_of_stabbing"],
    "enc_slavers": ["taskmaster", "slaver_red", "blue_slaver"],
}'''

# (5) the per-act tables.
OLD_TABLES = '''    "Elite": ["enc_gremlin_nob", "enc_three_sentries"],
    "Elite2": ["enc_gremlin_leader"],'''

NEW_TABLES = '''    "Elite": ["enc_gremlin_nob", "enc_lagavulin", "enc_three_sentries"],
    "Elite2": ["enc_book_of_stabbing", "enc_gremlin_leader", "enc_slavers"],'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in [
        (OLD_ACTIONS_TAIL, NEW_ACTIONS_TAIL),
        (OLD_CARD, NEW_CARD),
        (OLD_MONSTER, NEW_MONSTER),
        (OLD_ELITE, NEW_ELITE),
        (OLD_TABLES, NEW_TABLES),
    ]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("inventory updated: 6 actions, 1 card, 3 monsters, 3 encounters, 2 pool tables")


if __name__ == "__main__":
    main()
