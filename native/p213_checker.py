"""§213: pin the Chosen rewrite + `standard.hex` in `native/sts_content_check.py`'s inventories.

Every number here is copied from `native/wiki_asc/chosen.txt`; the action facts are copied from what
`program_facts` actually produced for the new programs (so the inventory says what the content says,
and the *wiki* numbers are the ones written into the content by `native/p213_chosen.py`).
"""
import io

P = 'native/sts_content_check.py'
text = io.open(P, encoding='utf-8').read()


def sub(old, new, what, count=1):
    global text
    got = text.count(old)
    assert got == count, "%s: expected %d, found %d" % (what, count, got)
    text = text.replace(old, new)


# ---- quantities ---------------------------------------------------------------------------------
sub('    # §208: +1 (`standard.flying`); §209: +1 (`standard.curl_up`).\n    "statuses": 42,',
    '    # §208: +1 (`standard.flying`); §209: +1 (`standard.curl_up`); §213: +1 (`standard.hex`).\n'
    '    "statuses": 43,', 'status count')

# ---- the Chosen roster row ----------------------------------------------------------------------
sub('    ("chosen", 48, 48, ["chosen.poke", "chosen.debilitate"]),',
    '''    # §213: wiki `Chosen` (Act 2 normal) -- HP 95-99 (A7 98-103), five moves:
    # Poke 5x2 (A2 6x2), Hex, Debilitate 10 + 2 Vulnerable (A2 12), Drain, Zap 18 (A2 21).
    ("chosen", 95, 99,
     ["chosen.poke", "chosen.hex", "chosen.debilitate", "chosen.drain", "chosen.zap"]),''',
    'chosen roster')

# ---- the five action facts ----------------------------------------------------------------------
sub('''    "chosen.poke": ("Attack", [("damage", 5, "event"), ("damage", 5, "event")]),''',
    '''    # §213: wiki `Chosen`. Four of the five moves carry an A2 damage row; `Hex` / `Drain` are
    # status-only (no A-row on the page).
    "chosen.poke": ("Attack", [("damage", 5, "event"), ("damage", 5, "event")]),
    "chosen.hex": ("Debuff", [("status", "standard.hex", 1, "event")]),
    "chosen.drain": ("Debuff", [("status", "standard.weak", 3, "event"),
                                ("status", "standard.strength", 3, "source")]),
    "chosen.zap": ("Attack", [("damage", 18, "event")]),''', 'chosen actions')

# ---- A2 rows ------------------------------------------------------------------------------------
sub("""    'maw.drool': [(17, [('status', 'standard.strength', 5, 'source')])],""",
    """    'maw.drool': [(17, [('status', 'standard.strength', 5, 'source')])],
    # §213: wiki `Chosen` -- Poke 5x2 -> A2 6x2, Debilitate 10 -> A2 12, Zap 18 -> A2 21.
    'chosen.poke': [(2, [('damage', 6, 'event'), ('damage', 6, 'event')])],
    'chosen.debilitate': [(2, [('damage', 12, 'event'),
                               ('status', 'standard.vulnerable', 2, 'event')])],
    'chosen.zap': [(2, [('damage', 21, 'event')])],""", 'chosen A2 rows')

# ---- `Hex` / `Drain` have no ascension row ------------------------------------------------------
sub("""    'maw.nom_nom': 'wiki The Maw: Nom Nom is 5 x ceil(turn/2), no A-row',""",
    """    'maw.nom_nom': 'wiki The Maw: Nom Nom is 5 x ceil(turn/2), no A-row',
    # §213: `Hex` applies a status and `Drain` moves statuses; neither has an A-row on the page.
    'chosen.hex': 'wiki Chosen: Hex applies the Hex debuff, no A-row',
    'chosen.drain': 'wiki Chosen: Drain is 3 Weak + 3 Strength, no A-row',""",
    'chosen exempt')

# ---- `standard.hex` in the modifier inventory + the trigger family ------------------------------
sub('''    # §209: Curl Up -- no modifier at all; its whole rule is the `DamageTaken` trigger below.
    "standard.curl_up": [],''',
    '''    # §209: Curl Up -- no modifier at all; its whole rule is the `DamageTaken` trigger below.
    "standard.curl_up": [],
    # §213: Hex -- no modifier either; the whole rule is a `CardPlayed` trigger that shuffles a
    # Dazed into the draw pile when the played card is **not** an Attack.
    "standard.hex": [],''', 'hex modifiers')

sub('''                     "standard.curl_up", "standard.plated_armor"):''',
    '''                     "standard.curl_up", "standard.plated_armor", "standard.hex"):''',
    'hex trigger family')

sub('''                        "standard.plated_armor": ["DamageTaken"]}[sid]''',
    '''                        "standard.plated_armor": ["DamageTaken"],
                        # §213: "whenever you play a non-Attack card" -- a CardPlayed trigger.
                        "standard.hex": ["CardPlayed"]}[sid]''', 'hex trigger expectation')

io.open(P, 'w', encoding='utf-8', newline='').write(text)
print("checker inventories updated for §213")
