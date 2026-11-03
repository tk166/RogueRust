"""§190: extend the content gate's ascension table from 13 to 42 entries.

This table is the **second opinion**: every line is written from `native/wiki_asc/*.txt` (base,
ascension value, threshold), not read out of the content. If the content and this table disagree the
gate goes red -- which is the only way a transcription error is ever caught.
"""
import io
import json
import sys

sys.path.insert(0, "native")
import sts_content_check as chk  # noqa: E402

PATH = "native/sts_content_check.py"
SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

# action id -> (AscensionMin, facts)   [wiki numbers; see docs/spec/sts-act1-inventory.md §4.5]
NEW = {
    # Act 1 normal, damage tier 2
    "cultist.incantation": (2, [("status", "ritual", 4, "source")]),
    "jaw_worm.chomp": (2, [("damage", 12, "event")]),
    "jaw_worm.bellow": (2, [("status", "standard.strength", 4, "source"),
                            ("block", 6, "source")]),
    "acid_slime_m.corrosive_spit": (2, [("damage", 8, "event"),
                                        ("card", "slimed", 1, "DiscardPile", "event")]),
    "acid_slime_m.tackle": (2, [("damage", 12, "event")]),
    "acid_slime_s.tackle": (2, [("damage", 4, "event")]),
    "spike_slime_s.tackle": (2, [("damage", 6, "event")]),
    "spike_slime_m.flame_tackle": (2, [("damage", 10, "event"),
                                       ("card", "slimed", 1, "DiscardPile", "event")]),
    "fungi_beast.grow": (2, [("status", "standard.strength", 4, "source")]),
    "byrd.swoop": (2, [("damage", 14, "event")]),
    "chosen.debilitate": (2, [("damage", 12, "event"),
                              ("status", "standard.vulnerable", 2, "event")]),
    "orb_walker.laser": (2, [("damage", 11, "event"),
                             ("status", "standard.weak", 2, "event")]),
    "orb_walker.claw": (2, [("damage", 16, "event")]),
    "fat_gremlin.smash": (2, [("damage", 5, "event"),
                              ("status", "standard.weak", 1, "event")]),
    "sneaky_gremlin.puncture": (2, [("damage", 10, "event")]),
    "gremlin_wizard.ultimate_blast": (2, [("damage", 30, "event"),
                                          ("counter", "gremlin_wizard_charges", 0, False, "source")]),
    "shelled_parasite.double_strike": (2, [("damage", 7, "event"), ("damage", 7, "event")]),
    "shelled_parasite.suck": (2, [("damage", 12, "event"), ("block", 2, "source")]),
    "spire_growth.aggressive": (2, [("damage", 18, "event")]),
    "spire_growth.aggressive_heavy": (2, [("damage", 25, "event")]),
    # move-set tier 17
    "louse_red.grow": (17, [("status", "standard.strength", 4, "source")]),
    "louse_green.grow": (17, [("status", "standard.strength", 4, "source")]),
    # elite: damage tier 3 / move-set 18
    "gremlin_nob.skull_bash": (3, [("damage", 8, "event"),
                                   ("status", "standard.vulnerable", 2, "event")]),
    "gremlin_nob.rush": (3, [("damage", 16, "event")]),
    "gremlin_nob.bellow": (18, [("status", "standard.strength", 3, "source")]),
    "sentry.beam": (3, [("damage", 10, "event")]),
    # boss: damage tier 4 / move-set 19
    "slime_boss.slam": (4, [("damage", 38, "event")]),
    "slime_boss.goop_spray": (19, [("card", "slimed", 5, "DiscardPile", "event")]),
}


def main():
    # `byrd.peck` grows by one hit (1x5 -> 1x6), so its facts are produced, not typed.
    document = json.load(io.open(SRC, encoding="utf-8"))
    peck = next(a for a in document["EnemyActions"] if a["Id"] == "byrd.peck")
    NEW["byrd.peck"] = (2, chk.program_facts(peck["ProgramAsc"]["Root"]))

    text = io.open(PATH, encoding="utf-8").read()
    rows = "".join(
        '    "%s": %r,\n' % (key, value) for key, value in sorted(NEW.items())
    )
    anchor = "}\n\n\ndef check_ascension_variants(doc):"
    assert text.count(anchor) == 1
    text = text.replace(anchor, rows + anchor)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("checker: %d new rows" % len(NEW))


if __name__ == "__main__":
    main()
