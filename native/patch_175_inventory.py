"""§175: teach the content gate act 3's two elites, the Dagger, the Burn card and the carrier status.

Five places, same as §173: counts, actions, cards, monsters, pools -- plus the status count and the
`standard.phantom_veil` row, which is the first content that uses a `TurnStarted` trigger.
"""
import io

PATH = "native/sts_content_check.py"

OLD_COUNTS = '''    # §173: +3 (Lagavulin / Book of Stabbing / Taskmaster).
    "monsters": 34,'''
NEW_COUNTS = '''    # §173: +3 (Lagavulin / Book of Stabbing / Taskmaster); §175: +3 (Nemesis / Reptomancer / Dagger).
    "monsters": 37,'''

OLD_COUNTS2 = '''    # §173: +3 (enc_lagavulin / enc_book_of_stabbing / enc_slavers).
    "encounters": 25,'''
NEW_COUNTS2 = '''    # §173: +3 (lagavulin / book of stabbing / slavers); §175: +2 (nemesis / reptomancer).
    "encounters": 27,'''

OLD_STATUSES = '''    "statuses": 24,       # inv:§10 the ones this subset actually needs (+ the three §158 added)'''
NEW_STATUSES = '''    # §175: +1 -- `standard.phantom_veil`, the carrier for Nemesis's "intangible every other turn".
    # It is the first content row that uses a `TurnStarted` trigger.
    "statuses": 25,'''

OLD_ACTIONS = '''    "book_of_stabbing.big_stab": ("Attack", [("damage", 21, "event")]),'''
NEW_ACTIONS = '''    "book_of_stabbing.big_stab": ("Attack", [("damage", 21, "event")]),
    # §175: act 3's two elites and the Dagger they summon.
    "nemesis.tri_attack": ("Attack", [("damage", 6, "event"), ("damage", 6, "event"),
                                      ("damage", 6, "event")]),
    "nemesis.tri_burn": ("Debuff", [("card", "burn", 3, "DiscardPile", "event")]),
    "nemesis.scythe": ("Attack", [("damage", 45, "event")]),
    "reptomancer.spawn_dagger": ("Buff", [("spawn", "dagger", 22)]),
    "reptomancer.big_bite": ("Attack", [("damage", 30, "event")]),
    "reptomancer.snake_strike": ("Attack", [("damage", 13, "event"), ("damage", 13, "event"),
                                            ("status", "standard.weak", 1, "event")]),
    "dagger.wound": ("Attack", [("damage", 9, "event"),
                                ("card", "wound", 1, "DiscardPile", "event")]),
    "dagger.explode": ("Attack", [("damage", 25, "event")]),'''

OLD_CARD = '''    "wound": {"Cost": 1, "Tags": ["status", "unplayable", "junk"], "Facts": []},'''
NEW_CARD = '''    "wound": {"Cost": 1, "Tags": ["status", "unplayable", "junk"], "Facts": []},
    # §175: Burn is the first card in this package with a `LifecyclePrograms[TurnEndInHand]` program
    # ("at the end of your turn, take 2 damage"). `Facts` is the **card's own** program (empty); the
    # lifecycle program is checked by the card-lifecycle test, not by this table.
    "burn": {"Cost": 1, "Tags": ["status", "unplayable", "junk"], "Facts": [],
             "Lifecycle": {"TurnEndInHand": [("damage", 2, "source")]}},'''

OLD_MONSTERS = '''    ("taskmaster", 54, 60, ["taskmaster.scouring_whip"]),'''
NEW_MONSTERS = '''    ("taskmaster", 54, 60, ["taskmaster.scouring_whip"]),
    # §175: act 3's elites. Nemesis carries `standard.phantom_veil` (the alternating Intangible);
    # Reptomancer summons Daggers; the Dagger's `Explode` does **not** kill it (no `destroyCombatant`).
    ("nemesis", 185, 185, ["nemesis.tri_attack", "nemesis.tri_burn", "nemesis.scythe"]),
    ("reptomancer", 180, 190,
     ["reptomancer.spawn_dagger", "reptomancer.big_bite", "reptomancer.snake_strike"]),
    ("dagger", 20, 25, ["dagger.wound", "dagger.explode"]),'''

# The status **list** (not just the count) also has to learn the new row, and the trigger table has to
# know it is the one status here that carries a `TurnStarted` trigger.
OLD_STATUS_LIST = '''    "standard.plated_armor": [],'''
NEW_STATUS_LIST = '''    "standard.plated_armor": [],
    # §175: Nemesis's carrier -- the first content row using a `TurnStarted` trigger.
    "standard.phantom_veil": [],'''

OLD_TRIGGER_SET = '''                     "standard.time_warp", "standard.constricted"):'''
NEW_TRIGGER_SET = '''                     "standard.time_warp", "standard.constricted",
                     "standard.phantom_veil"):'''

OLD_TRIGGER_MAP = '''                        "standard.constricted": ["TurnEnded"]}[sid]'''
NEW_TRIGGER_MAP = '''                        "standard.constricted": ["TurnEnded"],
                        # §175: the first `TurnStarted` trigger in this package.
                        "standard.phantom_veil": ["TurnStarted"]}[sid]'''

OLD_POOL = '''    "enc_slavers": ["taskmaster", "slaver_red", "blue_slaver"],
}'''
NEW_POOL = '''    "enc_slavers": ["taskmaster", "slaver_red", "blue_slaver"],
    # §175: act 3's two, so every act's elite pool has the wiki's three.
    "enc_nemesis": ["nemesis"],
    "enc_reptomancer": ["reptomancer", "dagger", "dagger"],
}'''

OLD_TABLE = '''    "Elite3": ["enc_giant_head"],'''
NEW_TABLE = '''    "Elite3": ["enc_giant_head", "enc_nemesis", "enc_reptomancer"],'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in [
        (OLD_COUNTS, NEW_COUNTS),
        (OLD_COUNTS2, NEW_COUNTS2),
        (OLD_STATUSES, NEW_STATUSES),
        (OLD_ACTIONS, NEW_ACTIONS),
        (OLD_CARD, NEW_CARD),
        (OLD_MONSTERS, NEW_MONSTERS),
        (OLD_STATUS_LIST, NEW_STATUS_LIST),
        (OLD_TRIGGER_SET, NEW_TRIGGER_SET),
        (OLD_TRIGGER_MAP, NEW_TRIGGER_MAP),
        (OLD_POOL, NEW_POOL),
        (OLD_TABLE, NEW_TABLE),
    ]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("inventory: act 3 (8 actions, 1 card, 3 monsters, 2 encounters, 1 status, Elite3)")


if __name__ == "__main__":
    main()
