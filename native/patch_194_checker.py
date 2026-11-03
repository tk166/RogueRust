"""§194 checker: 9 new monsters, 38 new actions, 2 statuses, 2 cards, 22 new ascension variants,
and the wiki's three-per-act boss pools.

Every number here comes from `native/wiki_asc/<boss>.txt` (the transcription is in
`native/patch_194_bosses.py`'s docstring), **not** from the content -- this file is the independent
second copy, which is the only reason it can catch a transcription slip.

Also `tgt()` learns `sel.allAllies`: §194 is the first content that buffs the boss's *own* team
(Donu's Circle of Power, Deca's Square of Protection, the Collector's Buff, the Orb's Support Beam).
`sel.allEnemies` is the **opposing** team, so using it there would have buffed the player -- a
mistake this file can now name.
"""
import io

P = "native/sts_content_check.py"
src = io.open(P, encoding="utf-8").read()


def sub(old, new, what=""):
    global src
    assert src.count(old) == 1, "%s: %d occurrences of %r" % (what, src.count(old), old[:70])
    src = src.replace(old, new)


# ---------------------------------------------------------------- 1. selector vocabulary
sub('''        "sel.allEnemies": "allEnemies",''',
'''        "sel.allEnemies": "allEnemies",
        # §194: the source's **own** team. Every boss buff ("all enemies gain 3 Strength" in the
        # wiki's words) means this one; `allEnemies` is the opposing team and would buff the player.
        "sel.allAllies": "allAllies",''', what="tgt allAllies")

# ---------------------------------------------------------------- 2. counts
sub('    "statuses": 27,\n}', '    "statuses": 29,\n}', what="status count")
sub('''    "monsters": 37,''', '''    "monsters": 46,''', what="monster count")
sub('''    "encounters": 27,''', '''    "encounters": 33,''', what="encounter count")

# ---------------------------------------------------------------- 3. roster
sub('''    ("slime_boss", 140, 140, ["slime_boss.goop_spray", "slime_boss.preparing", "slime_boss.slam"]),
]''',
'''    ("slime_boss", 140, 140, ["slime_boss.goop_spray", "slime_boss.preparing", "slime_boss.slam"]),

    # ================= §194: the wiki's boss pools, three per act =================
    # Act 1 (wiki: HP 240 / AscHP 250). The wiki's pattern is Charging Up, Fierce Bash, Vent Steam,
    # Whirlwind; Mode Shift / Defensive Mode / Roll Attack / Twin Slam are the mode sequence.
    ("the_guardian", 240, 240, ["the_guardian.charging_up", "the_guardian.fierce_bash",
                                "the_guardian.vent_steam", "the_guardian.whirlwind"]),
    # Act 1 (HP 250 / 264): the cycle is **rotated** so `(round-1) % 7` matches the wiki from turn 3
    # on; turns 1-2 are the two opening rules (Activate, Divider).
    ("hexaghost", 250, 250, ["hexaghost.sear", "hexaghost.inferno", "hexaghost.sear",
                             "hexaghost.tackle", "hexaghost.sear", "hexaghost.inflame",
                             "hexaghost.tackle"]),
    # Act 2 (HP 420 / 440 -- this replaced an invented 330).
    ("the_champ", 420, 420, ["the_champ.heavy_slash", "the_champ.face_slap",
                             "the_champ.defensive_stance", "the_champ.gloat"]),
    # Act 2 (HP 300 / 320). The cycle starts at Flail because the two Orbs are already deployed.
    ("bronze_automaton", 300, 300, ["bronze_automaton.flail", "bronze_automaton.boost",
                                    "bronze_automaton.flail", "bronze_automaton.boost",
                                    "bronze_automaton.hyper_beam", "bronze_automaton.stunned"]),
    ("bronze_orb", 52, 52, ["bronze_orb.beam", "bronze_orb.support_beam"]),
    # Act 2 (HP 282 / 300).
    ("the_collector", 282, 282, ["the_collector.fireball", "the_collector.buff"]),
    ("torch_head", 38, 38, ["torch_head.tackle"]),
    # Act 3 (HP 300 / 320): Slash, Slash, Soul Strike, Slash -- 75/25 and never three Slashes.
    ("awakened_one", 300, 300, ["awakened_one.slash", "awakened_one.slash",
                                "awakened_one.soul_strike", "awakened_one.slash"]),
    # Act 3 (HP 250 / 265 each). The first **pair** of bosses.
    ("donu", 250, 250, ["donu.circle_of_power", "donu.beam"]),
    ("deca", 250, 250, ["deca.beam", "deca.square_of_protection"]),
]''', what="roster rows")

# ---------------------------------------------------------------- 4. actions
sub('''    "taskmaster.scouring_whip": ("Attack", [("damage", 7, "event"),
                                            ("card", "wound", 1, "DiscardPile", "event")]),
}''',
'''    "taskmaster.scouring_whip": ("Attack", [("damage", 7, "event"),
                                            ("card", "wound", 1, "DiscardPile", "event")]),

    # ================= §194: the six new bosses + two minions =================
    # --- The Guardian (wiki: 32/36, 5x4, 9 Block, 9/10, 8x2, 3 Sharp Hide at A19 4, 20 Block) ----
    "the_guardian.charging_up": ("Defend", [("block", 9, "source")]),
    "the_guardian.fierce_bash": ("Attack", [("damage", 32, "event")]),
    "the_guardian.vent_steam": ("Debuff", [("status", "standard.weak", 2, "event"),
                                           ("status", "standard.vulnerable", 2, "event")]),
    "the_guardian.whirlwind": ("Attack", [("damage", 5, "event"), ("damage", 5, "event"),
                                          ("damage", 5, "event"), ("damage", 5, "event"),
                                          ("counter", "guard_mode", 0, False, "source"),
                                          ("counter", "guard_step", 0, False, "source")]),
    "the_guardian.defensive_mode": ("Buff", [("block", 20, "source"),
                                             ("status", "standard.sharp_hide", 3, "source"),
                                             ("counter", "guard_mode", 1, False, "source"),
                                             ("counter", "guard_step", 0, False, "source")]),
    "the_guardian.roll_attack": ("Attack", [("damage", 9, "event"),
                                            ("counter", "guard_step", 1, False, "source")]),
    "the_guardian.twin_slam": ("Attack", [("damage", 8, "event"), ("damage", 8, "event"),
                                          ("modify", "standard.sharp_hide", -99, "source"),
                                          ("counter", "guard_step", 2, False, "source")]),
    # --- Hexaghost (wiki: (HP/12+1)x6, 6 + 1 Burn, 5x2, 12 Block + 2 Str, 2x6 + 3 Burn+) ---------
    "hexaghost.activate": ("Special", []),
    "hexaghost.divider": ("Attack", [("repeat", ("expr", "add"), "damage", 6, "event")]),
    "hexaghost.sear": ("Attack", [("damage", 6, "event"),
                                  ("card", "burn", 1, "DiscardPile", "event")]),
    "hexaghost.tackle": ("Attack", [("damage", 5, "event"), ("damage", 5, "event")]),
    "hexaghost.inflame": ("Defend", [("block", 12, "source"),
                                     ("status", "standard.strength", 2, "source")]),
    "hexaghost.inferno": ("Attack", [("damage", 2, "event"), ("damage", 2, "event"),
                                     ("damage", 2, "event"), ("damage", 2, "event"),
                                     ("damage", 2, "event"), ("damage", 2, "event"),
                                     ("card", "burn+", 3, "DiscardPile", "event")]),
    # --- The Champ's four new moves (wiki: Face Slap 12 + 2 Frail + 2 Vuln, Gloat 2 Str,
    #     Taunt 2 Weak + 2 Vuln, Anger clears debuffs + 6 Str) -----------------------------------
    "the_champ.face_slap": ("Attack", [("damage", 12, "event"),
                                       ("status", "standard.frail", 2, "event"),
                                       ("status", "standard.vulnerable", 2, "event")]),
    "the_champ.gloat": ("Buff", [("status", "standard.strength", 2, "source")]),
    "the_champ.taunt": ("Debuff", [("status", "standard.weak", 2, "event"),
                                   ("status", "standard.vulnerable", 2, "event")]),
    "the_champ.anger": ("Buff", [("modify", "standard.weak", -99, "source"),
                                 ("modify", "standard.vulnerable", -99, "source"),
                                 ("modify", "standard.frail", -99, "source"),
                                 ("status", "standard.strength", 6, "source"),
                                 ("counter", "champ_phase", 1, False, "source"),
                                 ("counter", "champ_exec", 0, False, "source")]),
    # --- Bronze Automaton (wiki: Flail 7x2, Boost 3 Str + 9 Block, HYPER BEAM 45, Stunned) --------
    "bronze_automaton.flail": ("Attack", [("damage", 7, "event"), ("damage", 7, "event")]),
    "bronze_automaton.boost": ("Defend", [("status", "standard.strength", 3, "source"),
                                          ("block", 9, "source")]),
    "bronze_automaton.hyper_beam": ("Attack", [("damage", 45, "event")]),
    "bronze_automaton.stunned": ("Special", []),
    # --- Bronze Orb (wiki: Beam 8, Support Beam +12 Block to allies) ------------------------------
    "bronze_orb.beam": ("Attack", [("damage", 8, "event")]),
    "bronze_orb.support_beam": ("Defend", [("block", 12, "allAllies")]),
    # --- The Collector (wiki: Fireball 18, Buff +3 Str + 15 Block, Mega Debuff 3/3/3) -------------
    "the_collector.fireball": ("Attack", [("damage", 18, "event")]),
    "the_collector.buff": ("Defend", [("status", "standard.strength", 3, "allAllies"),
                                      ("block", 15, "source")]),
    "the_collector.mega_debuff": ("Debuff", [("status", "standard.weak", 3, "event"),
                                             ("status", "standard.vulnerable", 3, "event"),
                                             ("status", "standard.frail", 3, "event")]),
    "torch_head.tackle": ("Attack", [("damage", 7, "event")]),
    # --- Awakened One (wiki: Slash 20, Soul Strike 6x4, Dark Echo 40, Tackle 10x3, Sludge 18+Void) -
    "awakened_one.slash": ("Attack", [("damage", 20, "event")]),
    "awakened_one.soul_strike": ("Attack", [("damage", 6, "event"), ("damage", 6, "event"),
                                            ("damage", 6, "event"), ("damage", 6, "event")]),
    "awakened_one.rebirth": ("Special", [("heal", ("expr", "max"), "source"),
                                         ("modify", "standard.curiosity", -99, "source"),
                                         ("counter", "ao_phase", 1, False, "source"),
                                         ("counter", "ao_started", 0, False, "source"),
                                         ("counter", "ao_toggle", 0, False, "source")]),
    "awakened_one.dark_echo": ("Attack", [("damage", 40, "event"),
                                          ("counter", "ao_started", 1, False, "source"),
                                          ("counter", "ao_toggle", 0, False, "source")]),
    "awakened_one.tackle": ("Attack", [("damage", 10, "event"), ("damage", 10, "event"),
                                       ("damage", 10, "event"),
                                       ("counter", "ao_toggle", 1, False, "source")]),
    "awakened_one.sludge": ("Attack", [("damage", 18, "event"),
                                       ("card", "void", 1, "DiscardPile", "event"),
                                       ("counter", "ao_toggle", 0, False, "source")]),
    # --- Donu / Deca (wiki: Beam 10x2 both, Circle of Power +3 Str, Square 16 Block) --------------
    "donu.circle_of_power": ("Buff", [("status", "standard.strength", 3, "allAllies")]),
    "donu.beam": ("Attack", [("damage", 10, "event"), ("damage", 10, "event")]),
    "deca.beam": ("Debuff", [("damage", 10, "event"), ("damage", 10, "event"),
                             ("card", "dazed", 2, "DiscardPile", "event")]),
    "deca.square_of_protection": ("Defend", [("block", 16, "allAllies")]),
}''', what="action rows")

# ---------------------------------------------------------------- 5. cards
sub('''    "combust+": {"Cost": 1, "Tags": ["power"],
                 "Facts": [("status", "standard.combust", 7, "source")]},
}''',
'''    "combust+": {"Cost": 1, "Tags": ["power"],
                 "Facts": [("status", "standard.combust", 7, "source")]},

    # ================= §194: the two junk cards the new bosses add =================
    # Hexaghost's Inferno shuffles **upgraded** Burns in (wiki: "Adds 3 Burns+"): 4 damage at turn
    # end instead of 2.
    "burn+": {"Cost": 1, "Tags": ["status", "unplayable", "junk"],
              "Facts": [("lifecycle", "dealDamage", 4)]},
    # Awakened One's Sludge adds a Void. The wiki's Void also makes you lose 1 Energy when drawn;
    # nothing here can say "the card that just moved is this one", so that half is absent -- and the
    # card's own text says only what happens.
    "void": {"Cost": 1, "Tags": ["status", "unplayable", "ethereal", "junk"],
             "Facts": []},
}''', what="card rows")

# ---------------------------------------------------------------- 6. statuses
sub('''    "standard.lose_strength": [],
    "standard.lose_dexterity": [],
}''',
'''    "standard.lose_strength": [],
    "standard.lose_dexterity": [],
    # ================= §194 =================
    # Sharp Hide / Curiosity are the two the new bosses need, and both are `CardPlayed` triggers
    # filtered by a card tag -- the same shape as `standard.enrage`, which is why they are inert
    # here (no passive modifier; the whole effect is a trigger).
    "standard.sharp_hide": [],
    "standard.curiosity": [],
}''', what="status rows")

# ---------------------------------------------------------------- 7. pools
sub('''    "Boss": ["enc_slime_boss"],
    "Boss2": ["enc_the_champ"],
    "Boss3": ["enc_time_eater"],
}''',
'''    # §194: the wiki's "one of three, at random" per act. Act 1 lost the act-3 boss it never should
    # have had (Time Eater sat in `Boss`), and acts 2/3 stop replaying one invented boss.
    "Boss": ["enc_slime_boss", "enc_the_guardian", "enc_hexaghost"],
    "Boss2": ["enc_the_champ", "enc_bronze_automaton", "enc_the_collector"],
    "Boss3": ["enc_time_eater", "enc_awakened_one", "enc_donu_and_deca"],
}''', what="act tables")

sub('''INV_BOSS_POOL = {
    "enc_slime_boss": ["slime_boss"],
    # §129: two bosses now, so the floor-16 pick is a real choice.
    "enc_time_eater": ["time_eater"],
    # §130: act 2's boss.
    "enc_the_champ": ["the_champ"],
}''',
'''INV_BOSS_POOL = {
    # Act 1.
    "enc_slime_boss": ["slime_boss"],
    "enc_the_guardian": ["the_guardian"],
    "enc_hexaghost": ["hexaghost"],
    # Act 2. The Champ is the same id but a **different fight** since §194 (HP 420, four more
    # moves): it used to be an invented 330-HP three-move boss.
    "enc_the_champ": ["the_champ"],
    # The orbs are deployed with the boss (the encounter roster is what lets a minion act, §138).
    "enc_bronze_automaton": ["bronze_automaton", "bronze_orb", "bronze_orb"],
    "enc_the_collector": ["the_collector", "torch_head", "torch_head"],
    # Act 3.
    "enc_time_eater": ["time_eater"],
    "enc_awakened_one": ["awakened_one"],
    # The first **pair**: two bosses in one fight, which is what the wiki's Donu and Deca are.
    "enc_donu_and_deca": ["donu", "deca"],
}''', what="boss pool")

# ---------------------------------------------------------------- 8. ascension variants
sub("""    'the_champ.heavy_slash': [(4, [('damage', 18, 'event')])],
}""",
"""    'the_champ.heavy_slash': [(4, [('damage', 18, 'event')])],
    # ================= §194 =================
    # The Guardian (wiki: Fierce Bash 32->A4 36, Roll Attack 9->A4 10, Sharp Hide 3->A19 4).
    'the_guardian.fierce_bash': [(4, [('damage', 36, 'event')])],
    'the_guardian.roll_attack': [(4, [('damage', 10, 'event'),
                                      ('counter', 'guard_step', 1, False, 'source')])],
    'the_guardian.defensive_mode': [(19, [('block', 20, 'source'),
                                          ('status', 'standard.sharp_hide', 4, 'source'),
                                          ('counter', 'guard_mode', 1, False, 'source'),
                                          ('counter', 'guard_step', 0, False, 'source')])],
    # Hexaghost (Sear 1 Burn->A19 2, Tackle 5x2->A4 6x2, Inflame 2 Str->A19 3, Inferno 2x6->A4 3x6).
    'hexaghost.sear': [(19, [('damage', 6, 'event'),
                             ('card', 'burn', 2, 'DiscardPile', 'event')])],
    'hexaghost.tackle': [(4, [('damage', 6, 'event'), ('damage', 6, 'event')])],
    'hexaghost.inflame': [(19, [('block', 12, 'source'),
                                ('status', 'standard.strength', 3, 'source')])],
    'hexaghost.inferno': [(4, [('damage', 3, 'event'), ('damage', 3, 'event'),
                               ('damage', 3, 'event'), ('damage', 3, 'event'),
                               ('damage', 3, 'event'), ('damage', 3, 'event'),
                               ('card', 'burn+', 3, 'DiscardPile', 'event')])],
    # The Champ (Face Slap 12->A4 14, Gloat 2->A4 3->A19 4, Anger 6->A4 9->A19 12,
    # Defensive Stance 15/5 ->A9 18/6 ->A19 20/7).
    'the_champ.face_slap': [(4, [('damage', 14, 'event'),
                                 ('status', 'standard.frail', 2, 'event'),
                                 ('status', 'standard.vulnerable', 2, 'event')])],
    'the_champ.gloat': [(4, [('status', 'standard.strength', 3, 'source')]),
                        (19, [('status', 'standard.strength', 4, 'source')])],
    'the_champ.anger': [(4, [('modify', 'standard.weak', -99, 'source'),
                             ('modify', 'standard.vulnerable', -99, 'source'),
                             ('modify', 'standard.frail', -99, 'source'),
                             ('status', 'standard.strength', 9, 'source'),
                             ('counter', 'champ_phase', 1, False, 'source'),
                             ('counter', 'champ_exec', 0, False, 'source')]),
                        (19, [('modify', 'standard.weak', -99, 'source'),
                              ('modify', 'standard.vulnerable', -99, 'source'),
                              ('modify', 'standard.frail', -99, 'source'),
                              ('status', 'standard.strength', 12, 'source'),
                              ('counter', 'champ_phase', 1, False, 'source'),
                              ('counter', 'champ_exec', 0, False, 'source')])],
    'the_champ.defensive_stance': [(9, [('block', 18, 'source'),
                                        ('status', 'standard.metallicize', 6, 'source')]),
                                   (19, [('block', 20, 'source'),
                                         ('status', 'standard.metallicize', 7, 'source')])],
    # Bronze Automaton (Flail 7x2->A4 8x2, Boost Str 3->A4 4 and Block 9->A9 12, HYPER BEAM 45->A4 50).
    'bronze_automaton.flail': [(4, [('damage', 8, 'event'), ('damage', 8, 'event')])],
    'bronze_automaton.boost': [(4, [('status', 'standard.strength', 4, 'source'),
                                    ('block', 9, 'source')]),
                               (9, [('status', 'standard.strength', 4, 'source'),
                                    ('block', 12, 'source')])],
    'bronze_automaton.hyper_beam': [(4, [('damage', 50, 'event')])],
    # The Collector (Fireball 18->A4 21, Buff Str 3->A4 4->A19 5 and Block 15->A9 18->A19 23,
    # Mega Debuff 3/3/3 ->A19 5/5/5).
    'the_collector.fireball': [(4, [('damage', 21, 'event')])],
    'the_collector.buff': [(4, [('status', 'standard.strength', 4, 'allAllies'),
                                ('block', 15, 'source')]),
                           (9, [('status', 'standard.strength', 4, 'allAllies'),
                                ('block', 18, 'source')]),
                           (19, [('status', 'standard.strength', 5, 'allAllies'),
                                 ('block', 23, 'source')])],
    'the_collector.mega_debuff': [(19, [('status', 'standard.weak', 5, 'event'),
                                        ('status', 'standard.vulnerable', 5, 'event'),
                                        ('status', 'standard.frail', 5, 'event')])],
    # Time Eater (Reverberate 7x3->A4 8x3, Head Slam +2 Slimed at A19, Ripple +Frail at A19).
    'time_eater.reverberate': [(4, [('damage', 8, 'event'), ('damage', 8, 'event'),
                                    ('damage', 8, 'event')])],
    'time_eater.head_slam': [(19, [('damage', 26, 'event'),
                                   ('card', 'slimed', 2, 'DiscardPile', 'event')])],
    'time_eater.ripple': [(19, [('block', 20, 'source'),
                                ('status', 'standard.weak', 1, 'event'),
                                ('status', 'standard.vulnerable', 1, 'event'),
                                ('status', 'standard.frail', 1, 'event')])],
    # Donu / Deca (Beam 10x2->A4 12x2 both; Square of Protection +3 Plated Armor at A19).
    'donu.beam': [(4, [('damage', 12, 'event'), ('damage', 12, 'event')])],
    'deca.beam': [(4, [('damage', 12, 'event'), ('damage', 12, 'event'),
                       ('card', 'dazed', 2, 'DiscardPile', 'event')])],
    'deca.square_of_protection': [(19, [('block', 16, 'allAllies'),
                                        ('status', 'standard.plated_armor', 3, 'allAllies')])],
}""", what="ascension variants")

io.open(P, "w", encoding="utf-8", newline="").write(src)
print("checker patched for §194")
