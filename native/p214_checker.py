"""§214: pin Spiker + Spire Growth in `native/sts_content_check.py`'s inventories.

Numbers are the wiki's (`native/wiki_asc/shapes.txt`, `native/wiki_asc/spire_growth.txt`); the fact
lists are what `program_facts` reports for the programs `native/p214_shapes.py` wrote.
"""
import io

P = 'native/sts_content_check.py'
text = io.open(P, encoding='utf-8').read()


def sub(old, new, what, count=1):
    global text
    got = text.count(old)
    assert got == count, "%s: expected %d, found %d" % (what, count, got)
    text = text.replace(old, new)


# ---- roster: spiker's HP range becomes the wiki's 42-56, and spire growth lists three moves -------
sub('    ("spiker", 42, 42, ["spiker.cut", "spiker.spike"]),',
    '''    # §214: wiki `Shapes#Spiker` -- HP 42-56 (A7 44-60). The two moves are the wiki's `Attack` and
    # `Buff Thorns` (the ids are historical: `cut` = Attack, `spike` = Buff Thorns).
    ("spiker", 42, 56, ["spiker.cut", "spiker.spike"]),''', 'spiker roster')

sub("""    # `spire_growth.strategic` is still a real `EACT` row, and the gate checks that separately.
    ("spire_growth", 170, 170,
     ["spire_growth.aggressive", "spire_growth.aggressive_heavy"]),""",
    """    # §214: wiki `Spire Growth` -- three moves: Constrict (strategic), Quick Tackle (aggressive),
    # Smash (aggressive_heavy). `strategic` is now **listed** by the record, not just an EACT row.
    ("spire_growth", 170, 170,
     ["spire_growth.strategic", "spire_growth.aggressive", "spire_growth.aggressive_heavy"]),""",
    'spire roster')

# ---- action facts --------------------------------------------------------------------------------
sub('''    "spiker.spike": ("Attack", [("damage", 4, "event"), ("block", 2, "source")]),''',
    '''    # §214: `spike` is the wiki's `Buff Thorns` (+2 Thorns) -- the id is historical. The counter is
    # how "at most 6 times" is expressed (the AI rule reads it).
    "spiker.spike": ("Buff", [("status", "standard.thorns", 2, "source"),
                              ("counter", "thorns_buffs", 1, True, "source")]),''', 'spiker.spike facts')

# ---- A2 rows -------------------------------------------------------------------------------------
sub("""    'chosen.zap': [(2, [('damage', 21, 'event')])],""",
    """    'chosen.zap': [(2, [('damage', 21, 'event')])],
    # §214: wiki `Shapes#Spiker` -- Attack 7 -> A2 9.
    'spiker.cut': [(2, [('damage', 9, 'event')])],
    # §214: wiki `Spire Growth` -- Constrict 10 -> A2 12, Quick Tackle 16 -> A2 18, Smash 22 -> A2 25.
    'spire_growth.strategic': [(2, [('status', 'standard.constricted', 12, 'event')])],
    'spire_growth.aggressive': [(2, [('damage', 18, 'event')])],
    'spire_growth.aggressive_heavy': [(2, [('damage', 25, 'event')])],""", 'A2 rows')

# ---- `spiker.spike` (Buff Thorns) has no A-row ----------------------------------------------------
sub("""    'spiker.spike': 'this content is a simplification (4 dmg + 2 Block); wiki Spiker: Attack 7 -> A2: 9',""",
    """    'spiker.spike': 'wiki Shapes#Spiker: Buff Thorns is always +2 Thorns, no A-row',""",
    'spiker.spike exempt')

io.open(P, 'w', encoding='utf-8', newline='').write(text)
print("inventories updated for §214")
