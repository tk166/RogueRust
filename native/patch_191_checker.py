"""§191: the content gate follows the eight corrected bases, the six new variants, and `dazed`.

Every new line is written from the wiki (`native/wiki_asc/*.txt`), not read out of the content -- the
whole point of this table is to be the independent second opinion.
"""
import io

PATH = "native/sts_content_check.py"

FACT_FIXES = [
    # our old value -> the wiki's base
    ('"darkling.chomp": ("Attack", [("damage", 11, "event")]),',
     '"darkling.chomp": ("Attack", [("damage", 8, "event"), ("damage", 8, "event")]),'),
    ('"gremlin_leader.slash": ("Attack", [("damage", 16, "event")]),',
     '"gremlin_leader.slash": ("Attack", [("damage", 6, "event"), ("damage", 6, "event"),\n'
     '                                ("damage", 6, "event")]),'),
    ('"chosen.poke": ("Attack", [("damage", 6, "event"), ("damage", 6, "event")]),',
     '"chosen.poke": ("Attack", [("damage", 5, "event"), ("damage", 5, "event")]),'),
    ('"spiker.cut": ("Attack", [("damage", 8, "event")]),',
     '"spiker.cut": ("Attack", [("damage", 7, "event")]),'),
    ('"the_champ.heavy_slash": ("Attack", [("damage", 18, "event")]),',
     '"the_champ.heavy_slash": ("Attack", [("damage", 16, "event")]),'),
    ('"the_champ.execute": ("Attack", [("damage", 30, "event")]),',
     '"the_champ.execute": ("Attack", [("damage", 10, "event"), ("damage", 10, "event")]),'),
    ('"spire_growth.strategic": ("Debuff", [("status", "standard.constricted", 2, "event")]),',
     '"spire_growth.strategic": ("Debuff", [("status", "standard.constricted", 10, "event")]),'),
    ('"sentry.bolt": ("Attack", [("damage", 10, "event")]),',
     '"sentry.bolt": ("Debuff", [("card", "dazed", 2, "DiscardPile", "event")]),'),
]

CARD_ROW = '''    # §191：Sentry 的 Bolt 塞的就是这张（wiki: Unplayable. Ethereal.）。
    "dazed": {"Cost": 1, "Tags": ["status", "unplayable", "ethereal", "junk"], "Facts": []},
'''

ASC_ROWS = '''    # §191：基础值修对之后，这六条终于可以有升档（数字仍是 wiki 那一格）。
    "spiker.cut": (2, [("damage", 9, "event")]),
    "the_champ.heavy_slash": (4, [("damage", 18, "event")]),
    "chosen.poke": (2, [("damage", 6, "event"), ("damage", 6, "event")]),
    "darkling.chomp": (2, [("damage", 9, "event"), ("damage", 9, "event")]),
    "spire_growth.strategic": (2, [("status", "standard.constricted", 12, "event")]),
    "sentry.bolt": (18, [("card", "dazed", 3, "DiscardPile", "event")]),
'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in FACT_FIXES:
        if new in text:
            continue
        assert text.count(old) == 1, (text.count(old), old[:50])
        text = text.replace(old, new)
    if '"dazed"' not in text:
        anchor = '''    "ascenders_bane": {"Cost": 0, "Tags": ["curse", "unplayable", "ethereal"], "Facts": []},'''
        assert text.count(anchor) == 1
        text = text.replace(anchor, anchor + "\n" + CARD_ROW.rstrip("\n"))
    if '"sentry.bolt": (18,' not in text:
        anchor = "    \"slime_boss.goop_spray\": (19, [('card', 'slimed', 5, 'DiscardPile', 'event')]),"
        assert text.count(anchor) == 1
        text = text.replace(anchor, anchor + "\n" + ASC_ROWS.rstrip("\n"))
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("checker updated: 8 facts, dazed, 6 ascension rows")


if __name__ == "__main__":
    main()
