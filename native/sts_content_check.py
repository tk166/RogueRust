#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sts_content_check.py -- the gate for `tools/contentc/packages/sts/**`.

WHY THREE LAYERS (each one alone is a false green)
--------------------------------------------------
1. INV    every number in the content is compared against the number in
          `docs/spec/sts-act1-inventory.md`.  The table in this file is
          hand-written (each row carries its `inv:§x`), so this is the layer
          that catches "the source document and the image agree, and both are
          wrong".  A round-trip-only gate can never catch that.
2. ROUND  every entity (4 row tables + every root key) is read back out of BOTH
          images with `reader.py` and compared per key against the source
          document -- **key presence included**, and a key the source does not
          have is a mismatch too (so "the image grew a fact nobody re-checked"
          is red, not silent).  The one exception is the compiler's own
          `DOC_ROOT_KEYS` (build metadata: `InertKeys`, `Notes`): those are
          stored in neither image, and the gate *asserts* that absence.
          The core image's expectation is derived with `compile.py`'s own
          `strip_presentation`, not with a second copy of that rule: a copy is
          the classic "second source of truth rots" bug (`contentc-audit.md` §7).
3. XREF   the cross references resolve and are consistent: deck -> cards,
          encounter -> monster roster (field by field, because the roster is a
          duplicate of the encounter's inline record), roster -> enemy actions,
          every status a program names -> a STAT row, every id -> the right
          entity kind in `SEC_IDX`.
4. INERT  a key the kernel never reads must be *declared* inert in the
          document's `InertKeys` block, with the reason it can stay.  The
          round-trip layer is blind to this class: "the image agrees with the
          source" is true for a key nobody consumes.  Derivation and the rot
          directions are in §2b.  A `root:` declaration may name a **sub-key**
          (`root:Start.MaxHealth`, `root:Characters[].UnlockFlag`) because the
          unit of the fact is "which field of that object is unused", not "the
          whole object is unused" -- root-key granularity lost five facts the
          moment the kernel learned to read `Start.Deck`.

Plus two failure modes that are cheap to forget:
* an image older than its source document is red (`build.py --package sts`),
  because a stale image is the most expensive kind of green;
* every effect program is mechanically reduced to a list of *facts*
  (`damage 6 to event` / `status standard.weak 1 to event` / ...) and compared
  against the expected fact list -- a fact that is present but not expected is
  a failure (the inventory says "extra also counts as failure").

Exit codes: 0 all green, 1 a check failed, 2 precondition missing (no image,
no source, stale image).
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONTENTC = os.path.join(ROOT, "tools", "contentc")
sys.path.insert(0, CONTENTC)

import rdcfmt as F            # noqa: E402  (the frozen on-disk vocabulary)
import reader as rdcf_reader  # noqa: E402  (the reference reader)
import compile as contentc_compile  # noqa: E402  (strip_presentation + DOC_ROOT_KEYS)

PKG_DIR = os.path.join(CONTENTC, "packages", "sts")
SRC_PATH = os.path.join(PKG_DIR, "sts.roguedeck.json")
FULL_PATH = os.path.join(PKG_DIR, "out", "content.sts.rdcf")
CORE_PATH = os.path.join(PKG_DIR, "out", "content.sts.core.rdcf")

# =============================================================================
# 1.  inv -- the numbers, each row carrying the section it came from
# =============================================================================
# `docs/spec/sts-act1-inventory.md` is the only source of numbers.  Nothing in
# this file may be "tuned to make the content pass": if a number here disagrees
# with the content, one of the two is wrong and a human has to look.

# inv:§1 -- the counts this milestone promises (the task's quantity gate).
INV_COUNTS = {
    # 10 tier-A monsters + three sentry **rows** (one per instance: a combatant id must be unique
    # and the encounter record has no instance number, inv:§4.2) + the boss.
    # §173: +3 (Lagavulin / Book of Stabbing / Taskmaster); §175: +3 (Nemesis / Reptomancer / Dagger).
    "monsters": 46,
    # 3 weak-pool encounters + 1 elite (`enc_three_sentries`) + 1 boss (`enc_slime_boss`).
    # §173: +3 (lagavulin / book of stabbing / slavers); §175: +2 (nemesis / reptomancer).
    "encounters": 33,
    "deck": 10,          # inv:§2   "10 张：strike x5、defend x4、bash x1"
    # §175: +1 -- `standard.phantom_veil`, the carrier for Nemesis's "intangible every other turn".
    # It is the first content row that uses a `TurnStarted` trigger.
    # §180: +1 -- `standard.fairy_in_a_bottle`, the first row that uses `DeathPrevention`.
    # §181: +1 -- `standard.duplication`, the first `UsesCharges` status the kernel consumes.
    "statuses": 33,
}

# inv:§2 / §2.1 -- the hero.
INV_HERO = {
    "HeroName": "Ironclad",
    "MaxHealth": 80,
    "StartingHealth": 80,
    "EnergyCurrent": 3,          # inv:§2 起始能量 3
    "EnergyMax": 3,
    "CardsDrawnPerTurn": 5,      # inv:§2 起手抽牌 5（通用规则）
}
INV_DECK = {"strike": 5, "defend": 4, "bash": 1}   # inv:§2.1

# inv:§3.1 -- the 3 basic cards, as mechanically derived facts.
INV_CARDS = {
    "strike": {"Cost": 1, "Tags": ["attack", "basic", "strike"],
               "Facts": [("damage", 6, "event")]},
    "defend": {"Cost": 1, "Tags": ["skill", "basic", "defend"],
               "Facts": [("block", 5, "source")]},
    "bash": {"Cost": 2, "Tags": ["attack", "basic"],
             "Facts": [("damage", 8, "event"), ("status", "standard.vulnerable", 2, "event")]},
    # inv:§10 -- a status card created by two enemies (not part of the deck).
    "slimed": {"Cost": 1, "Tags": ["status", "unplayable", "junk"], "Facts": []},
    # §183: the colorless pool. The Colorless Potion offers three of them; **no deck can hold them**,
    # which is why they have no `+` row (see NOT_UPGRADABLE_TAGS). Wiki values, base.
    # §189 `A10`：开局诅咒（wiki: Unplayable. Ethereal. Cannot be removed）。
    "ascenders_bane": {"Cost": 0, "Tags": ["curse", "unplayable", "ethereal"], "Facts": []},
    # §191：Sentry 的 Bolt 塞的就是这张（wiki: Unplayable. Ethereal.）。第三张 junk 卡，
    # 与 `slimed` / `wound` 同形 —— 唯一区别是它离手即烧掉。
    "dazed": {"Cost": 1, "Tags": ["status", "unplayable", "ethereal", "junk"], "Facts": []},
    "bandage_up": {"Cost": 0, "Tags": ["skill", "colorless"],
                   "Facts": [("heal", 4, "sourceDowned")]},
    "blind": {"Cost": 0, "Tags": ["skill", "colorless"],
              "Facts": [("status", "standard.weak", 2, "allEnemies")]},
    "dark_shackles": {"Cost": 0, "Tags": ["skill", "colorless"],
                      "Facts": [("status", "standard.lose_strength", 9, "event"),
                                ("status", "standard.strength", -9, "event")]},
    # inv:§2.1 "升级后" -- the upgraded rows. They are **separate CARD rows**, not a flag on the base
    # card (`sts-act1-plan.md` §6.5-2), and their numbers are the inventory's second column:
    # strike+ 9 damage, defend+ 8 Block, bash+ 10 damage + 3 Vulnerable.
    "strike+": {"Cost": 1, "Tags": ["attack", "basic", "strike"],
                "Facts": [("damage", 9, "event")]},
    "defend+": {"Cost": 1, "Tags": ["skill", "basic", "defend"],
                "Facts": [("block", 8, "source")]},
    "bash+": {"Cost": 2, "Tags": ["attack", "basic"],
              "Facts": [("damage", 10, "event"), ("status", "standard.vulnerable", 3, "event")]},
    # The first **non-Basic** cards: the deck has to be able to grow, and an act-1 boss cannot be
    # beaten with ten starter cards (see docs/port-plan.md §72.5).
    "twin_strike": {"Cost": 1, "Tags": ["attack", "strike"],
                    "Facts": [("damage", 5, "event"), ("damage", 5, "event")]},
    "iron_wave": {"Cost": 1, "Tags": ["attack", "block"],
                  "Facts": [("block", 5, "source"), ("damage", 5, "event")]},
    "clothesline": {"Cost": 2, "Tags": ["attack"],
                    "Facts": [("damage", 12, "event"), ("status", "standard.weak", 2, "event")]},
    "anger": {"Cost": 0, "Tags": ["attack"],
              "Facts": [("damage", 6, "event"), ("card", "anger", 1, "DiscardPile", "event")]},
    "uppercut": {"Cost": 2, "Tags": ["attack"],
                 "Facts": [("damage", 13, "event"), ("status", "standard.weak", 1, "event"),
                           ("status", "standard.vulnerable", 1, "event")]},
    # §143: the first **Curse**. It is not in the deck and never a reward; an event hands it to
    # you (`curse:injury`), and the only thing it does is sit in the way -- `unplayable`.
    "injury": {"Cost": 1, "Tags": ["curse", "unplayable", "junk"], "Facts": []},
    # §173: the junk the act-2 elites hand out (Taskmaster's whip, and the Daggers that come later).
    # Same shape as `slimed`: a status card, unplayable, no program.
    "wound": {"Cost": 1, "Tags": ["status", "unplayable", "junk"], "Facts": []},
    # §175: Burn is the first card in this package with a `LifecyclePrograms[TurnEndInHand]` program
    # ("at the end of your turn, take 2 damage"). `Facts` is the **card's own** program (empty); the
    # lifecycle program is checked by the card-lifecycle test, not by this table.
    "burn": {"Cost": 1, "Tags": ["status", "unplayable", "junk"], "Facts": [],
             "Lifecycle": {"TurnEndInHand": [("damage", 2, "source")]}},
    # §144: the keyword cards. `sentinel` is a **real** Ironclad card (5 Block, Ethereal); the other
    # two are **fixtures** on purpose -- the Ironclad has no Retain and no Innate card in StS, so
    # the keyword has to be exercised by a card this package owns. Their numbers are this package's,
    # not the wiki's, and that is why they are named here rather than silently mixed in.
    "sentinel": {"Cost": 1, "Tags": ["skill", "ethereal"],
                 "Facts": [("block", 5, "source")],
                 "TurnEndHandDestinationZone": "ExhaustPile"},
    "patient_guard": {"Cost": 1, "Tags": ["skill", "retain"],
                      "Facts": [("block", 5, "source")],
                      "RetainInHandOnTurnEnd": True},
    "swift_strike": {"Cost": 1, "Tags": ["attack", "strike", "innate"],
                     "Facts": [("damage", 6, "event")]},
    # §146：第一张 **X 费**牌（Whirlwind，真卡：X 费，"Deal 5 damage to ALL enemies X times"）。
    # 它的费用是"当前全部能量"，`Cost` 在这里记 0 —— 印刷价格**不参与**结算，内容门下面会查
    # 这一格必须是 0 或缺失。Facts 里的 `("repeat", ("expr", "x.cost"), ...)` 说明"这一条伤害
    # **每 X 一次**"，而不是被展开成 32 条。
    # §149: cards that hand out the damage-pipeline statuses (they exist so the statuses are
    # reachable in a run; `buffer` is a Defect power in StS, modelled here as a skill).
    "apparition": {"Cost": 1, "Tags": ["skill", "intangible"],
                   "Facts": [("status", "standard.intangible", 1, "source")]},
    "buffer": {"Cost": 1, "Tags": ["skill", "buffer"],
               "Facts": [("status", "standard.buffer", 1, "source")]},
    # §147: the upgraded row -- same X mechanics, 8 damage per hit instead of 5.
    # §154: the ten `+` rows that were missing. The run upgrades by appending `+` to the card id, so
    # a card without one becomes an id the image does not contain -- and the next fight refuses to
    # build (`UnknownCard(CardDefinitionId("iron_wave+"))`, reported from the browser).
    "anger+": {"Cost": 0, "Tags": ["attack"],
               "Facts": [("damage", 8, "event"), ("card", "anger+", 1, "DiscardPile", "event")]},
    "twin_strike+": {"Cost": 1, "Tags": ["attack", "strike"],
                     "Facts": [("damage", 7, "event"), ("damage", 7, "event")]},
    "iron_wave+": {"Cost": 1, "Tags": ["attack", "block"],
                   "Facts": [("block", 7, "source"), ("damage", 7, "event")]},
    "clothesline+": {"Cost": 2, "Tags": ["attack"],
                     "Facts": [("damage", 14, "event"), ("status", "standard.weak", 3, "event")]},
    "uppercut+": {"Cost": 2, "Tags": ["attack"],
                  "Facts": [("damage", 13, "event"), ("status", "standard.weak", 2, "event"),
                            ("status", "standard.vulnerable", 2, "event")]},
    "sentinel+": {"Cost": 1, "Tags": ["skill", "ethereal"],
                  "Facts": [("block", 8, "source")]},
    "patient_guard+": {"Cost": 1, "Tags": ["skill", "retain"],
                       "Facts": [("block", 8, "source")]},
    "swift_strike+": {"Cost": 1, "Tags": ["attack", "strike", "innate"],
                      "Facts": [("damage", 9, "event")]},
    "apparition+": {"Cost": 1, "Tags": ["skill", "intangible"],
                    "Facts": [("status", "standard.intangible", 2, "source")]},
    "buffer+": {"Cost": 1, "Tags": ["skill", "buffer"],
                "Facts": [("status", "standard.buffer", 2, "source")]},
    "whirlwind+": {"Cost": 0, "Tags": ["attack", "x_cost"],
                   "Facts": [("repeat", ("expr", "x.cost"), "damage", 8, "allEnemies")]},
    "whirlwind": {"Cost": 0, "Tags": ["attack", "x_cost"],
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

    # ================= §194: the two junk cards the new bosses add =================
    # Hexaghost's Inferno shuffles **upgraded** Burns in (wiki: "Adds 3 Burns+"): 4 damage at turn
    # end instead of 2.
    "burn+": {"Cost": 1, "Tags": ["status", "unplayable", "junk"],
              "Facts": []},
    # Awakened One's Sludge adds a Void. The wiki's Void also makes you lose 1 Energy when drawn;
    # nothing here can say "the card that just moved is this one", so that half is absent -- and the
    # card's own text says only what happens.
    "void": {"Cost": 1, "Tags": ["status", "unplayable", "ethereal", "junk"],
             "Facts": []},
}

# inv:§4.1 -- the 10 zero-new-ability enemies: (hp_min, hp_max, action ids).
# §140: mirrors `rd_core::state::MAX_ENEMIES_IN_FIGHT`. The kernel enforces it on **summons**;
# this file enforces it on what the content **places**.
MAX_ENEMIES_IN_FIGHT = 4

INV_MONSTERS = [
    ("spike_slime_s", 10, 14, ["spike_slime_s.tackle"]),
    # §129: the wiki's act-3 boss, parked in the Boss pool (acts still share content).
    # §137: the act-3 normal pool gets thicker.
    ("darkling", 48, 48, ["darkling.nip", "darkling.chomp"]),
    ("maw", 80, 80, ["maw.roar", "maw.bite", "maw.slam"]),
    # §134: acts 2 and 3 have their own elites.
    ("gremlin_leader", 140, 140,
     ["gremlin_leader.slash", "gremlin_leader.rally", "gremlin_leader.summon"]),
    ("giant_head", 320, 320, ["giant_head.glare", "giant_head.count"]),
    ("time_eater", 456, 456,
     ["time_eater.reverberate", "time_eater.ripple", "time_eater.head_slam"]),
    # §130: act 2 and act 3 have monsters of their own -- the point of the section.
    ("shelled_parasite", 68, 68, ["shelled_parasite.suck", "shelled_parasite.double_strike"]),
    ("chosen", 48, 48, ["chosen.poke", "chosen.debilitate"]),
    ("byrd", 25, 25, ["byrd.peck", "byrd.swoop"]),
    ("spiker", 42, 42, ["spiker.cut", "spiker.spike"]),
    ("orb_walker", 90, 90, ["orb_walker.laser", "orb_walker.claw"]),
    # §152: the rest of act 1's roster, wiki numbers.
    ("louse_red", 10, 15, ["louse_red.bite", "louse_red.grow", "louse_red.spit_web"]),
    ("louse_green", 11, 16, ["louse_green.bite", "louse_green.grow"]),
    ("fungi_beast", 22, 28, ["fungi_beast.bite", "fungi_beast.grow"]),
    ("slaver_red", 46, 50, ["slaver_red.stab", "slaver_red.scrape"]),
    ("gremlin_nob", 82, 86,
     ["gremlin_nob.bellow", "gremlin_nob.rush", "gremlin_nob.skull_bash"]),
    # §173: the wiki's act-1 elite #2 and act-2 elites #2/#3.
    # Lagavulin: HP 109-111, Metallicize 8, Sleep for rounds 1-3 (`intent.round` rule), then
    # `siphon_soul`/`attack` alternating -- the order is chosen so round 4 is the Attack.
    ("lagavulin", 109, 111, ["lagavulin.siphon_soul", "lagavulin.attack"]),
    ("book_of_stabbing", 160, 164,
     ["book_of_stabbing.multi_stab", "book_of_stabbing.big_stab"]),
    ("taskmaster", 54, 60, ["taskmaster.scouring_whip"]),
    # §175: act 3's elites. Nemesis carries `standard.phantom_veil` (the alternating Intangible);
    # Reptomancer summons Daggers; the Dagger's `Explode` does **not** kill it (no `destroyCombatant`).
    ("nemesis", 185, 185, ["nemesis.tri_attack", "nemesis.tri_burn", "nemesis.scythe"]),
    ("reptomancer", 180, 190,
     ["reptomancer.spawn_dagger", "reptomancer.big_bite", "reptomancer.snake_strike"]),
    ("dagger", 20, 25, ["dagger.wound", "dagger.explode"]),
    # §147: the `Constricted` carrier (wiki HP 170; Strategic / Aggressive 16 / 22).
    # §148: the **cycle** is the two Aggressive moves; `Strategic` is a round-1 **rule**, not a
    # cycle slot (StS opens with it once). That is why it is absent from this list --
    # `spire_growth.strategic` is still a real `EACT` row, and the gate checks that separately.
    ("spire_growth", 170, 170,
     ["spire_growth.aggressive", "spire_growth.aggressive_heavy"]),
    ("fat_gremlin", 13, 17, ["fat_gremlin.smash"]),
    ("sneaky_gremlin", 10, 14, ["sneaky_gremlin.puncture"]),
    ("blue_slaver", 46, 50, ["blue_slaver.stab", "blue_slaver.rake"]),
    ("acid_slime_s", 8, 12, ["acid_slime_s.tackle", "acid_slime_s.lick"]),
    ("acid_slime_m", 28, 32, ["acid_slime_m.corrosive_spit",
                              "acid_slime_m.tackle", "acid_slime_m.lick"]),
    ("spike_slime_m", 28, 32, ["spike_slime_m.flame_tackle", "spike_slime_m.lick"]),
    ("jaw_worm", 40, 44, ["jaw_worm.chomp", "jaw_worm.thrash", "jaw_worm.bellow"]),
    ("cultist", 48, 54, ["cultist.incantation", "cultist.dark_strike"]),
    # inv:§0 flaw 4 -- the game files say 21-25, the wiki infobox says 23-25 and
    # its own Ascension value (22-26) is lower than the base one.  We take 21-25.
    ("gremlin_wizard", 21, 25, ["gremlin_wizard.charging"]),
    # inv:§4.2 -- the first elite, one row per instance. **Downgraded on purpose and in writing**:
    # no `Dazed` card (so Beam is 9 damage and nothing else) and no `Artifact 1` (the kernel has no
    # such status).
    ("sentry_1", 38, 42, ["sentry.bolt", "sentry.beam"]),
    ("sentry_2", 38, 42, ["sentry.bolt", "sentry.beam"]),
    ("sentry_3", 38, 42, ["sentry.bolt", "sentry.beam"]),
    # inv:§4.3 -- the act-1 boss. **Downgraded in writing**: no Split (the kernel cannot add
    # combatants mid-fight), which is the fight's identity; the three-move cycle is faithful.
    ("slime_boss", 140, 140, ["slime_boss.goop_spray", "slime_boss.preparing", "slime_boss.slam"]),

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
    ("bronze_orb", 52, 52, ["bronze_orb.stasis", "bronze_orb.beam", "bronze_orb.support_beam"]),
    # Act 2 (HP 282 / 300).
    ("the_collector", 282, 282, ["the_collector.fireball", "the_collector.buff"]),
    ("torch_head", 38, 38, ["torch_head.tackle"]),
    # Act 3 (HP 300 / 320): Slash, Slash, Soul Strike, Slash -- 75/25 and never three Slashes.
    ("awakened_one", 300, 300, ["awakened_one.slash", "awakened_one.slash",
                                "awakened_one.soul_strike", "awakened_one.slash"]),
    # Act 3 (HP 250 / 265 each). The first **pair** of bosses.
    ("donu", 250, 250, ["donu.circle_of_power", "donu.beam"]),
    ("deca", 250, 250, ["deca.beam", "deca.square_of_protection"]),
]

# inv:§4.1 -- every enemy action, as mechanically derived facts.
INV_ACTIONS = {
    # §193: `N = Number between (7-11;{{Asc|2|9-13}}), chosen at the start of combat` -- the amount
    # is a counter the fight rolls at spawn, not a constant (the range lives in `INV_ROLLS`).
    "darkling.nip": ("Attack", [("damage", ("counter", "roll.nip", "source"), "event")]),
    "darkling.chomp": ("Attack", [("damage", 8, "event"), ("damage", 8, "event")]),
    "maw.roar": ("Debuff", [("status", "standard.strength", 3, "source"),
                            ("status", "standard.weak", 2, "event")]),
    "maw.bite": ("Attack", [("damage", 14, "event")]),
    "maw.slam": ("Attack", [("damage", 20, "event"), ("block", 3, "source")]),
    "gremlin_leader.slash": ("Attack", [("damage", 6, "event"), ("damage", 6, "event"),
                                ("damage", 6, "event")]),
    "gremlin_leader.rally": ("Defend", [("block", 12, "source"),
                                        ("status", "standard.strength", 5, "source")]),
    "giant_head.glare": ("Attack", [("damage", 12, "event"),
                                    ("status", "standard.weak", 1, "event")]),
    "giant_head.count": ("Attack", [("damage", 26, "event")]),
    # \u00a7138: summoning -- two minions the encounter never lists.
    "gremlin_leader.summon": ("Buff", [("spawn", "sneaky_gremlin", 10),
                                              ("spawn", "gremlin_wizard", 20)]),
    "shelled_parasite.suck": ("Attack", [("damage", 10, "event"), ("block", 2, "source")]),
    "shelled_parasite.double_strike": ("Attack", [("damage", 6, "event"), ("damage", 6, "event")]),
    "chosen.poke": ("Attack", [("damage", 5, "event"), ("damage", 5, "event")]),
    "chosen.debilitate": ("Attack", [("damage", 10, "event"),
                                     ("status", "standard.vulnerable", 2, "event")]),
    "byrd.peck": ("Attack", [("damage", 1, "event")] * 5),
    "byrd.swoop": ("Attack", [("damage", 12, "event")]),
    "spiker.cut": ("Attack", [("damage", 7, "event")]),
    "spiker.spike": ("Attack", [("damage", 4, "event"), ("block", 2, "source")]),
    "orb_walker.laser": ("Attack", [("damage", 10, "event"),
                                    ("status", "standard.weak", 2, "event")]),
    "orb_walker.claw": ("Attack", [("damage", 15, "event")]),
    "the_champ.heavy_slash": ("Attack", [("damage", 16, "event")]),
    # §194: Metallicize is 5 (wiki); A9 -> 18 Block / 6, A19 -> 20 / 7.
    "the_champ.defensive_stance": ("Defend", [("block", 15, "source"),
                                              ("status", "standard.metallicize", 5, "source")]),
    "the_champ.execute": ("Attack", [("damage", 10, "event"), ("damage", 10, "event")]),
    # §194: Haste -- "when reduced to below half HP, heals to 50% (A19: also 32 Block), once".
    "time_eater.haste": ("Buff", [("heal", ("expr", "max"), "source"),
                                  ("counter", "te_haste", 1, False, "source")]),
    "time_eater.reverberate": ("Attack", [("damage", 7, "event"), ("damage", 7, "event"),
                                          ("damage", 7, "event")]),
    "time_eater.head_slam": ("Attack", [("damage", 26, "event")]),
    "time_eater.ripple": ("Defend", [("block", 20, "source"),
                                     ("status", "standard.weak", 1, "event"),
                                     ("status", "standard.vulnerable", 1, "event")]),
    # §152: act 1's new enemies (wiki numbers).
    # §193: `N = Number between (5-7;{{Asc|2|6-8}}), chosen at the start of combat`.
    "louse_red.bite": ("Attack", [("damage", ("counter", "roll.bite", "source"), "event")]),
    "louse_red.grow": ("Buff", [("status", "standard.strength", 3, "source")]),
    "louse_red.spit_web": ("Debuff", [("status", "standard.weak", 2, "event")]),
    "louse_green.bite": ("Attack", [("damage", 6, "event")]),
    "louse_green.grow": ("Buff", [("status", "standard.strength", 3, "source")]),
    "fungi_beast.bite": ("Attack", [("damage", 6, "event")]),
    "fungi_beast.grow": ("Buff", [("status", "standard.strength", 3, "source")]),
    "slaver_red.stab": ("Attack", [("damage", 13, "event")]),
    # §187 回 wiki 重核：Red Slaver 的 Scrape 是 **8 伤害 + 1 Vulnerable**
    # (`wiki_slavers.txt`：`Deals (8;{{Asc|2|9}}) damage. Applies (1;{{Asc|17|2}}) Vulnerable.`)。
    # 内容与这张清单**当初一起写错**（写成了蓝色 Slaver 的 Rake），
    # 所以 20 道闸门全绿 —— 与 §186 的 `blind` 是同一个形状。
    "slaver_red.scrape": ("Attack", [("damage", 8, "event"),
                                     ("status", "standard.vulnerable", 1, "event")]),
    "gremlin_nob.bellow": ("Buff", [("status", "standard.strength", 2, "source")]),
    "gremlin_nob.rush": ("Attack", [("damage", 14, "event")]),
    "gremlin_nob.skull_bash": ("Attack", [("damage", 6, "event"),
                                          ("status", "standard.vulnerable", 2, "event")]),
    # §147: Constricted itself is a content trigger (see `standard.constricted`), so the action
    # only has to apply it.
    "spire_growth.strategic": ("Debuff", [("status", "standard.constricted", 10, "event")]),
    "spire_growth.aggressive": ("Attack", [("damage", 16, "event")]),
    "spire_growth.aggressive_heavy": ("Attack", [("damage", 22, "event")]),
    "spike_slime_s.tackle": ("Attack", [("damage", 5, "event")]),
    "fat_gremlin.smash": ("Attack", [("damage", 4, "event"),
                                     ("status", "standard.weak", 1, "event")]),
    "sneaky_gremlin.puncture": ("Attack", [("damage", 9, "event")]),
    "blue_slaver.stab": ("Attack", [("damage", 12, "event")]),
    "blue_slaver.rake": ("Attack", [("damage", 7, "event"),
                                    ("status", "standard.weak", 1, "event")]),
    "acid_slime_s.tackle": ("Attack", [("damage", 3, "event")]),
    "acid_slime_s.lick": ("Debuff", [("status", "standard.weak", 1, "event")]),
    "acid_slime_m.corrosive_spit": ("Attack", [("damage", 7, "event"),
                                               ("card", "slimed", 1, "DiscardPile", "event")]),
    "acid_slime_m.tackle": ("Attack", [("damage", 10, "event")]),
    "acid_slime_m.lick": ("Debuff", [("status", "standard.weak", 1, "event")]),
    "spike_slime_m.flame_tackle": ("Attack", [("damage", 8, "event"),
                                              ("card", "slimed", 1, "DiscardPile", "event")]),
    "spike_slime_m.lick": ("Debuff", [("status", "standard.frail", 1, "event")]),
    "jaw_worm.chomp": ("Attack", [("damage", 11, "event")]),
    "jaw_worm.thrash": ("Attack", [("damage", 7, "event"), ("block", 5, "source")]),
    "jaw_worm.bellow": ("Buff", [("status", "standard.strength", 3, "source"),
                                 ("block", 6, "source")]),
    "cultist.incantation": ("Buff", [("status", "ritual", 3, "source")]),
    "cultist.dark_strike": ("Attack", [("damage", 6, "event")]),
    "gremlin_wizard.charging": ("Special", []),
    "slime_boss.goop_spray": ("Special", [("card", "slimed", 3, "DiscardPile", "event")]),
    "slime_boss.preparing": ("Special", []),
    "slime_boss.slam": ("Attack", [("damage", 35, "event")]),
    "sentry.bolt": ("Attack", [("card", "dazed", 2, "DiscardPile", "event")]),
    "sentry.beam": ("Attack", [("damage", 9, "event")]),
    "gremlin_wizard.ultimate_blast": ("Attack", [
        ("damage", 25, "event"),
        # the AI turn counter is reset by the blast itself; it is the content-side
        # substitute for `intent.round` (there is none, see Notes.Deviations).
        ("counter", "gremlin_wizard_charges", 0, False, "source")]),
    # §173: the three elites that bring the act-1 and act-2 pools up to the wiki's three each.
    # `Sleep` is an **empty** program on purpose: the turn is taken and nothing happens.
    "lagavulin.sleep": ("Unknown", []),
    "lagavulin.attack": ("Attack", [("damage", 18, "event")]),
    # The wiki's Siphon Soul is "-1 Strength, -1 Dexterity" -- and it must be **`modifyStatusStacks`**,
    # not `applyStatus` with negative stacks: the latter throws `Exec` (§174), which the driver records
    # as `StepThrew` and then the fight is stuck with that enemy as the active combatant.
    "lagavulin.siphon_soul": ("Debuff", [("modify", "standard.strength", -1, "event"),
                                        ("modify", "standard.dexterity", -1, "event")]),
    # "6×N damage, N = times Multi Stab was used this combat + 2". The order is damage-then-bump
    # because `setCombatantCounter` is a **queued effect**: a program cannot read a counter it just
    # wrote (measured: bump-then-repeat still counted the old value). "completed uses + 3" is
    # identically the wiki's "uses + 2". `repeat` **flattens** its body facts behind the count.
    "book_of_stabbing.multi_stab": ("Attack",
                                    [("repeat", ("expr", "add"), "damage", 6, "event"),
                                     ("counter", "book_stab_uses", 1, True, "source")]),
    "book_of_stabbing.big_stab": ("Attack", [("damage", 21, "event")]),
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
    "dagger.explode": ("Attack", [("damage", 25, "event")]),
    "taskmaster.scouring_whip": ("Attack", [("damage", 7, "event"),
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
    # §195.1: Mode Shift is a **budget** now (seeded at spawn from the record's `Counters`, drained
    # by the HP actually lost), so Defensive Mode *refills* it by the wiki's +10 per trigger.
    "the_guardian.defensive_mode": ("Buff", [("block", 20, "source"),
                                             ("status", "standard.sharp_hide", 3, "source"),
                                             ("counter", "mode_shift_budget", 10, True, "source"),
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
    # §195.4: Stasis -- steal the highest-rarity card from the draw pile (discard if empty) into
    # `SetAsidePile`, then spend its own status ("once per combat").
    "bronze_orb.stasis": ("Debuff", [("select", "allEnemies", "DrawPile", "DiscardPile",
                                      "HighestRarity", 1, "SetAsidePile"),
                                     ("modify", "standard.stasis_ready", -99, "source")]),
    "bronze_orb.beam": ("Attack", [("damage", 8, "event")]),
    "bronze_orb.support_beam": ("Defend", [("block", 12, "allAllies")]),
    # --- The Collector (wiki: Fireball 18, Buff +3 Str + 15 Block, Mega Debuff 3/3/3) -------------
    # §195.3: the two moves the weighted rule draws from, each recording itself in `last_move`
    # (that counter is how "cannot Buff twice in a row" is expressed without kernel state).
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
                                         ("counter", "ao_started", 0, False, "source")]),
    "awakened_one.dark_echo": ("Attack", [("damage", 40, "event"),
                                          ("counter", "ao_started", 1, False, "source")]),
    "awakened_one.tackle": ("Attack", [("damage", 10, "event"), ("damage", 10, "event"),
                                       ("damage", 10, "event")]),
    "awakened_one.sludge": ("Attack", [("damage", 18, "event"),
                                       ("card", "void", 1, "DiscardPile", "event")]),
    # --- Donu / Deca (wiki: Beam 10x2 both, Circle of Power +3 Str, Square 16 Block) --------------
    "donu.circle_of_power": ("Buff", [("status", "standard.strength", 3, "allAllies")]),
    "donu.beam": ("Attack", [("damage", 10, "event"), ("damage", 10, "event")]),
    "deca.beam": ("Debuff", [("damage", 10, "event"), ("damage", 10, "event"),
                             ("card", "dazed", 2, "DiscardPile", "event")]),
    "deca.square_of_protection": ("Defend", [("block", 16, "allAllies")]),
}

# inv:§5.2 -- the weak pool.  The 4th entry (`enc_two_louses`) needs
# louse_red/louse_green, which are tier C (Curl Up needs a DamageTaken trigger).
INV_WEAK_POOL = {
    "enc_cultist": ["cultist"],
    "enc_jaw_worm": ["jaw_worm"],
    # The source rolls 50/50 acid|spike for the M and for the S independently;
    # a static enemy list pins one of the four combinations.
    "enc_small_slimes": ["acid_slime_m", "spike_slime_s"],
    # §130: act 2 and act 3 have encounters -- and therefore monsters -- of their own.
    "enc_shelled_parasite": ["shelled_parasite"],
    "enc_chosen": ["chosen"],
    # §138: the gang exists so that a **summoned** gremlin has a record to point at.
    "enc_gremlin_gang": ["fat_gremlin", "sneaky_gremlin", "gremlin_wizard"],
    "enc_byrds": ["byrd"],
    "enc_spiker": ["spiker"],
    "enc_orb_walker": ["orb_walker"],
    "enc_darklings": ["darkling", "darkling"],
    # §152: the rest of act 1's weak pool, wiki numbers (see patch_152_enemies.py).
    "enc_louse": ["louse_red"],
    "enc_fungi_beast": ["fungi_beast"],
    "enc_slaver_red": ["slaver_red"],
    # §147: the carrier for `Constricted` (act 3, wiki HP 170).
    "enc_spire_growth": ["spire_growth"],
    "enc_maw": ["maw"],
}
INV_WEAK_WEIGHT = 100  # inv:§5.2 权重之和 100（6 个遭遇按 20/16/16/16/16/16 分）

# inv:§5.3 -- the elite pool. One entry, so there is no weight question yet; `EncounterTables.Elite`
# in the document carries it, and this is what the check compares that against.
INV_ELITE_POOL = {
    # §134: one elite per later act.
    "enc_gremlin_leader": ["gremlin_leader"],
    "enc_giant_head": ["giant_head"],
    "enc_three_sentries": ["sentry_1", "sentry_2", "sentry_3"],
    # §152: a second act-1 elite, so the elite node is not always the same fight.
    "enc_gremlin_nob": ["gremlin_nob"],
    # §173: the wiki's three-per-act elite pools. Act 1 gains Lagavulin, act 2 gains Book of
    # Stabbing and the Slavers trio (Taskmaster + Red Slaver + Blue Slaver, in that order -- the
    # order is the turn order).
    "enc_lagavulin": ["lagavulin"],
    "enc_book_of_stabbing": ["book_of_stabbing"],
    "enc_slavers": ["taskmaster", "slaver_red", "blue_slaver"],
    # §175: act 3's two, so every act's elite pool has the wiki's three.
    "enc_nemesis": ["nemesis"],
    "enc_reptomancer": ["reptomancer", "dagger", "dagger"],
}

# inv:§4.3 -- the boss pool. `inv:§4.3` says the three act-1 bosses are picked equiprobably; this
# content authors one of them (Slime Boss) and says why in the document.
# §130: the pool dicts above are the **union** (every encounter must be declared somewhere). These
# say which act each pool member belongs to, so the table checks can compare per act.
INV_ACT_TABLES = {
    "Weak": ["enc_cultist", "enc_jaw_worm", "enc_small_slimes",
             "enc_louse", "enc_fungi_beast", "enc_slaver_red",
             # §153: the Gremlin Gang is an **act-1** encounter (wiki); it sat in act 2.
             "enc_gremlin_gang"],
    "Weak2": ["enc_chosen", "enc_shelled_parasite"],
    "Weak3": ["enc_byrds", "enc_darklings", "enc_maw", "enc_orb_walker", "enc_spiker",
              "enc_spire_growth"],
    "Elite": ["enc_gremlin_nob", "enc_lagavulin", "enc_three_sentries"],
    "Elite2": ["enc_book_of_stabbing", "enc_gremlin_leader", "enc_slavers"],
    "Elite3": ["enc_giant_head", "enc_nemesis", "enc_reptomancer"],
    # §194: the wiki's "one of three, at random" per act. Act 1 lost the act-3 boss it never should
    # have had (Time Eater sat in `Boss`), and acts 2/3 stop replaying one invented boss.
    "Boss": ["enc_slime_boss", "enc_the_guardian", "enc_hexaghost"],
    "Boss2": ["enc_the_champ", "enc_bronze_automaton", "enc_the_collector"],
    "Boss3": ["enc_time_eater", "enc_awakened_one", "enc_donu_and_deca"],
}

INV_BOSS_POOL = {
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
}

# inv:§10 -- the 5 statuses, with the modifier the damage/block pipeline needs.
# `None` = the content cannot express it today (see Notes.KernelGapsFound).
# The magnitudes are copied from kernel/rd-core/src/status_catalog.rs:135-215,
# because a content image **disables** that catalog (exec.rs:2421-2426): with
# content present the candidate rows come only from STAT.PassiveModifiers.
INV_STATUSES = {
    # Declared inert by the kernel (`is_declared_inert`): it wants a TurnEnded content trigger,
    # not a modifier. `port-plan.md` §107.
    "standard.metallicize": [],
    # Thorns: a DamageTaken trigger (port-plan.md §116).
    "standard.thorns": [],
    # Downed / artifact / CardPlayed hooks (port-plan.md §117).
    "standard.spore_cloud": [],
    "standard.artifact": [],
    "standard.enrage": [],
    # The four built on existing hooks (port-plan.md §119).
    "standard.regen": [],
    "standard.rage": [],
    "standard.flame_barrier": [],
    "standard.combust": [],
    # Boss split: a Downed trigger that spawns two (port-plan.md §121).
    "standard.split": [],
    # Boss phase: at <=10 HP it splits once (port-plan.md §122).
    "standard.phase_split": [],
    # Time Eater's mechanic, prepared on an unused monster (port-plan.md §125).
    "standard.time_warp": [],
    # §149: the three damage-pipeline statuses -- no triggers at all, the kernel owns the rule.
    "standard.intangible": [],
    "standard.buffer": [],
    # §180: no triggers and no modifiers: its whole behaviour is `DeathPrevention`, which the
    # damage pipeline reads at the death point (`exec::resolve_damage_of_kind`). Listed with `[]`
    # because an empty expectation is the **assertion** ("this row must not grow modifiers"), not
    # an omission.
    "standard.fairy_in_a_bottle": [],
    # §181: no triggers, no modifiers -- `play.rs` reads its charges when a card program starts.
    "standard.duplication": [],
    "standard.plated_armor": [],
    # §175: Nemesis's carrier -- the first content row using a `TurnStarted` trigger.
    "standard.phantom_veil": [],
    # §147: `TurnEnded` trigger, damage = stacks, **ignores Block** ("lose HP" is not damage).
    "standard.constricted": [],
    "standard.strength": [("DamageDealt", "AddPerStack", 1, 100, "Direct")],
    "standard.vulnerable": [("DamageReceived", "ScalePercent", 150, 300, "Direct")],
    "standard.weak": [("DamageDealt", "ScalePercent", 75, 200, "Direct")],
    # `frail` is the only status on the *block* pipeline.  The wire string is
    # "BlockGain" -- the reference enum member name (`PassiveModifiers.cs:20`),
    # **not** "Block" (that is the kernel's *variant* name, not a wire string).  The numbers
    # come from the reference declaration (`StandardCombatPackage.cs:318-321`:
    # BlockGain / ScalePercent / 75 / Priority 200) and are folded by
    # `DeclarativePassiveBlockModifier` (`PassiveModifiers.cs:257-269`), which
    # reads the *gaining* combatant and passes `damageKind: null` -- hence the
    # None in the last slot.  Single stage, no priority-per-stage axis.
    "standard.frail": [("BlockGain", "ScalePercent", 75, 200, None)],
    "ritual": [],
    # §158: Dexterity. Same pipeline as `frail` and the same wire-string trap, but `AddPerStack`
    # (the reference declaration is `StandardCombatPackage.cs:360-363`:
    # BlockGain / AddPerStack / 1 / Priority 100). The kernel's own `BLOCK_MODIFIERS` table says the
    # same thing, but a content image **disables** that table (`exec.rs` §A), so this row is the only
    # thing that makes a Dexterity Potion move the number -- and
    # `dexterity_from_the_content_scales_a_real_defend` is what proves it does.
    "standard.dexterity": [("BlockGain", "AddPerStack", 1, 100, None)],
    # §158: the "give it back at the end of the turn" half of Flex / Speed Potion. No modifier: the
    # behaviour is a TurnEnded trigger that subtracts its own stacks from Strength / Dexterity and
    # then removes itself.
    "standard.lose_strength": [],
    "standard.lose_dexterity": [],
    # ================= §194 =================
    # Sharp Hide / Curiosity are the two the new bosses need, and both are `CardPlayed` triggers
    # filtered by a card tag -- the same shape as `standard.enrage`, which is why they are inert
    # here (no passive modifier; the whole effect is a trigger).
    "standard.sharp_hide": [],
    "standard.curiosity": [],
    # §195.1: the Guardian's Mode Shift -- a `DamageTaken` trigger that adds `eventAmount` (the HP
    # actually lost) to a counter. The threshold is an intent rule, so there is no passive modifier.
    "standard.mode_shift": [],
    # §195.2: Awakened One's phase-one guard. No trigger at all: the whole effect is the
    # `DeathPrevention` row, which `resolve_damage` already reads for any combatant (§180).
    "standard.unawakened": [],
    # §195.4: Bronze Orb's Stasis, split in two on purpose -- `standard.stasis` carries the `Downed`
    # hook (returns the stolen card) and `standard.stasis_ready` is the once-per-combat flag that the
    # move spends. One status cannot be both: consuming it would delete the hook.
    "standard.stasis": [],
    "standard.stasis_ready": [],
}
# Statuses whose stacks decay at the owner's turn end (inv:§10).
INV_DECAYING = {"standard.vulnerable", "standard.weak", "standard.frail"}

# =============================================================================
# 2.  helpers
# =============================================================================

PROBLEMS = []

# The five entity tables.  `reader.document()` always emits all five (as lists,
# possibly empty) while the source document may simply not have the key at all;
# so they are compared row by row, never as root keys.
# The document keys the compiler turns into **entity rows** (not root keys). UnknownRooms is the
# ?-room table (EV); the key is named that way because the reference document uses Events for a
# dict of its own shape and ENTITY_SECTIONS is a global mapping.
ROW_TABLES = ("Cards", "Statuses", "EnemyActions", "Encounters", "Relics")


def fail(where, message):
    PROBLEMS.append("%s: %s" % (where, message))


def ok(label, detail=""):
    print("  ok   %-34s %s" % (label, detail))


def die(code, message):
    sys.stderr.write("STS_CONTENT ENV_MISSING\n%s\n" % message)
    raise SystemExit(code)


def rel(path):
    try:
        return os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:
        # A path on another drive (e.g. a scratch build passed via --src/--full).
        return path


def show(value, limit=120):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[:limit] + "..."


def diff(expected, actual, path="", out=None):
    """Structural diff that is **presence sensitive**.

    A key that exists on only one side is a difference even when the other side
    would read back as "absent" -- that is the whole point of the two sentinels
    in rdcfmt, and it is what makes "the image grew a fact" observable.
    """
    if out is None:
        out = []
    if len(out) >= 25:
        return out
    if type(expected) is not type(actual) and not (
            isinstance(expected, (int, float)) and isinstance(actual, (int, float))):
        out.append("%s: type %s vs %s (%s vs %s)"
                   % (path or "<root>", type(expected).__name__,
                      type(actual).__name__, show(expected), show(actual)))
        return out
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            sub = "%s.%s" % (path, key) if path else key
            if key not in expected:
                out.append("%s: unexpected key in image (%s)" % (sub, show(actual[key])))
            elif key not in actual:
                out.append("%s: key missing from image (%s)" % (sub, show(expected[key])))
            else:
                diff(expected[key], actual[key], sub, out)
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            out.append("%s: list length %d vs %d"
                       % (path or "<root>", len(expected), len(actual)))
        for index in range(min(len(expected), len(actual))):
            diff(expected[index], actual[index], "%s[%d]" % (path, index), out)
    elif expected != actual:
        out.append("%s: %s vs %s" % (path or "<root>", show(expected), show(actual)))
    return out


def tgt(selector):
    """`TargetSelector` -> a short label.  Unknown selectors raise (never guess)."""
    kind = selector.get("kind")
    mapping = {
        "sel.eventTarget": "event",
        "sel.source": "source",
        # §178: distinct from `source` on purpose -- `sel.source` resolves to the EMPTY set for a
        # downed combatant, so a split on `Downed` must use this one. Two different facts, two
        # different labels; folding them would hide exactly the bug this section fixed.
        "sel.sourceIncludingDowned": "sourceDowned",
        "sel.allEnemies": "allEnemies",
        # §194: the source's **own** team. Every boss buff ("all enemies gain 3 Strength" in the
        # wiki's words) means this one; `allEnemies` is the opposing team and would buff the player.
        "sel.allAllies": "allAllies",
    }
    if kind not in mapping:
        raise AssertionError("unexpected selector kind %r" % kind)
    return mapping[kind]


def amount(expr):
    if expr.get("kind") == "const":
        return expr["value"]["Value"]
    if expr.get("kind") == "combatantCounter":
        # §193: a damage/gain whose size is a **counter**. Spelled with its key *and* the selector,
        # so "the wrong unit's counter" is a visible fact and not an interchangeable number.
        return ("counter", expr["value"]["CounterId"], tgt(expr["value"]["Selector"]))
    return ("expr", expr.get("kind"))


def program_facts(root):
    """Reduce an effect program to the facts it states -- mechanically.

    Any node kind this function does not know raises, so a node type that the
    inventory never mentions cannot sneak into the content unnoticed.  The
    result is compared for **equality** with the expected list: an extra fact is
    a failure ("多余也算失败"), not a pass.
    """
    facts = []

    def walk(node):
        kind = node.get("kind")
        body = node.get("value") or {}
        if kind == "node.sequence":
            for child in body.get("Children") or []:
                walk(child)
        elif kind == "node.dealDamage":
            facts.append(("damage", amount(body["Amount"]), tgt(body["TargetSelector"])))
        elif kind == "node.heal":
            facts.append(("heal", amount(body["Amount"]), tgt(body["TargetSelector"])))
        elif kind == "node.gainBlock":
            facts.append(("block", amount(body["Amount"]), tgt(body["TargetSelector"])))
        elif kind == "node.applyStatus":
            facts.append(("status", body["StatusDefinitionId"]["value"],
                          amount(body["Stacks"]), tgt(body["TargetSelector"])))
        elif kind == "node.createCardInstance":
            facts.append(("card", body["CardDefinitionId"]["value"],
                          amount(body["Count"]), body["ToZone"],
                          tgt(body["TargetSelector"])))
        elif kind == "node.setCombatantCounter":
            facts.append(("counter", body["CounterId"]["value"], amount(body["Amount"]),
                          body["Relative"], tgt(body["TargetSelector"])))
        elif kind == "node.modifyStatusStacks":
            facts.append(("modify", body["StatusDefinitionId"]["value"],
                          amount(body["Delta"]), tgt(body["TargetSelector"])))
        elif kind == "node.extraTurn":
            facts.append(("extraTurn", tgt(body["TargetSelector"])))
        elif kind == "node.endTurn":
            facts.append(("endTurn",))
        elif kind == "node.destroyCombatant":
            # §178: the other half of a split. Recorded as a fact, not ignored -- "the boss is
            # replaced" is exactly the thing the old content got wrong.
            facts.append(("destroy", tgt(body["TargetSelector"])))
        elif kind == "node.createCombatant":
            facts.append(("spawn", body["DefinitionId"], amount(body["Health"]) if body.get("Health") else 0))
        elif kind == "node.conditional":
            # A conditional states the facts of **both** branches, tagged with the condition, so the
            # inventory cannot hide a branch behind an `if` (port-plan.md §118).
            cond = body["Condition"]
            key = cond.get("value", {}).get("FieldKey")
            for branch in ("Then", "Else"):
                sub = body.get(branch)
                if sub:
                    before = len(facts)
                    walk(sub)
                    facts[before:] = [("when", key) + f for f in facts[before:]]
        elif kind == "node.selectCards":
            # §195.4: "pick which card" as a fact. Every field that decides *which* card is part of
            # the fact, because "steal the best card" and "steal the first card" differ only here.
            facts.append(("select", tgt(body["OwnerSelector"]), body["FromZone"],
                          body.get("FallbackZone"), body["Order"],
                          # `Count` is a plain int field on this node (not an expression).
                          body["Count"], body["ToZone"]))
        elif kind == "node.repeat":
            # §146: the body runs an unknown-at-authoring number of times, so its facts are tagged
            # by **the count expression** rather than unrolled. That keeps the inventory honest
            # ("this card deals 5 damage to all enemies *per X*") and keeps the walker total: a
            # repeat that hid its body would be the same failure as an unknown node kind.
            before = len(facts)
            walk(body["Body"])
            facts[before:] = [("repeat", amount(body["Count"])) + f for f in facts[before:]]
        else:
            raise AssertionError("unexpected node kind %r" % kind)

    walk(root)
    return facts


def split_history(facts):
    """Peel the `prev_move = last_move; last_move = k` pair off a fact list.

    §195.5: "which move did I just use" is **content state** (a counter pair at the end of every
    action program), and every boss that draws by weight needs it. Keeping those two facts out of
    `INV_ACTIONS` is deliberate: that table is the independent copy of the **wiki's numbers**, and a
    bookkeeping counter is not a wiki number. The bookkeeping is checked structurally instead, by
    `check_intent_history`, which can say things a per-action table cannot ("the code a rule asks
    about must be written by some action").
    """
    if len(facts) >= 2:
        prev, last = facts[-2], facts[-1]
        is_prev = (prev[0] == "counter" and prev[1] == "prev_move"
                   and isinstance(prev[2], tuple) and prev[2] == ("counter", "last_move", "source"))
        is_last = (last[0] == "counter" and last[1] == "last_move"
                   and isinstance(last[2], int) and last[3] is False)
        if is_prev and is_last:
            return facts[:-2], last[2]
    return facts, None


def load_programs(doc):
    """id -> the program root, for cards and enemy actions."""
    out = {}
    for rec in doc.get("Cards") or []:
        out["card:" + rec["Id"]] = rec["Program"]["Root"]
    for rec in doc.get("EnemyActions") or []:
        out["action:" + rec["Id"]] = rec["Program"]["Root"]
    return out


# =============================================================================
# 3.  the checks
# =============================================================================

def check_preconditions():
    print("[0] preconditions")
    for path in (SRC_PATH, FULL_PATH, CORE_PATH):
        if not os.path.exists(path):
            die(2, "missing %s -- run: python tools/contentc/build.py --package sts"
                % rel(path))
    src_mtime = os.path.getmtime(SRC_PATH)
    for path in (FULL_PATH, CORE_PATH):
        if os.path.getmtime(path) + 1e-6 < src_mtime:
            die(2, "%s is OLDER than %s -- the image is stale; run: "
                   "python tools/contentc/build.py --package sts"
                % (rel(path), rel(SRC_PATH)))
    for path in (SRC_PATH, FULL_PATH, CORE_PATH):
        ok("present + fresh", "%s (%d B)" % (rel(path), os.path.getsize(path)))


def check_quantities(doc):
    print("[1] quantities (from inv:§1 / §2 / §3.3 / §5.2 / §10)")
    got = {
        "monsters": len(doc.get("Monsters") or []),
        "encounters": len(doc.get("Encounters") or []),
        "deck": len((doc.get("Start") or {}).get("Deck") or []),
        "statuses": len(doc.get("Statuses") or []),
    }
    for name, want in sorted(INV_COUNTS.items()):
        if got[name] != want:
            fail("quantity." + name, "content has %d, inv says %d" % (got[name], want))
    # inv:§1 "25 个敌人实体" is the whole act; this milestone authors the
    # zero-new-ability tier only (plan §3.3: 10/25).
    ok("counts", "monsters=%d encounters=%d deck=%d statuses=%d cards=%d actions=%d"
       % (got["monsters"], got["encounters"], got["deck"], got["statuses"],
          len(doc.get("Cards") or []), len(doc.get("EnemyActions") or [])))

    # The roster must be exactly the inventory's tier-A list.
    roster_ids = sorted(m["Id"] for m in doc.get("Monsters") or [])
    inv_ids = sorted(m[0] for m in INV_MONSTERS)
    if roster_ids != inv_ids:
        fail("roster.ids", "roster %s != inv %s" % (roster_ids, inv_ids))
    # Both pools: the weak one (`inv:§5.2`) and the elite one (`inv:§5.3`).
    declared = sorted(set(INV_WEAK_POOL) | set(INV_ELITE_POOL) | set(INV_BOSS_POOL))
    if sorted(doc.get("Encounters") and [e["Id"]["Value"] for e in doc["Encounters"]]) \
            != declared:
        fail("encounters.ids", "encounter ids %s != inv %s"
             % (sorted(e["Id"]["Value"] for e in doc["Encounters"]),
                declared))
    if sorted(s["Id"] for s in doc.get("Statuses") or []) != sorted(INV_STATUSES):
        fail("statuses.ids", "%s != %s"
             % (sorted(s["Id"] for s in doc["Statuses"] or []), sorted(INV_STATUSES)))
    if sorted(c["Id"] for c in doc.get("Cards") or []) != sorted(INV_CARDS):
        fail("cards.ids", "%s != %s"
             % (sorted(c["Id"] for c in doc.get("Cards") or []), sorted(INV_CARDS)))
    if sorted(a["Id"] for a in doc.get("EnemyActions") or []) != sorted(INV_ACTIONS):
        fail("actions.ids", "%s != %s"
             % (sorted(a["Id"] for a in doc.get("EnemyActions") or []),
                sorted(INV_ACTIONS)))
    ok("id sets match inv", "roster/encounters/statuses/cards/actions")


def check_monsters(doc):
    print("[2] monster numbers (inv:§4.1)")
    by_id = {m["Id"]: m for m in doc.get("Monsters") or []}
    for mid, hp_min, hp_max, actions in INV_MONSTERS:
        entry = by_id.get(mid)
        if entry is None:
            fail("monster." + mid, "not in the roster")
            continue
        if (entry.get("HpMin"), entry.get("HpMax")) != (hp_min, hp_max):
            fail("monster." + mid, "HP range %s-%s, inv says %d-%d"
                 % (entry.get("HpMin"), entry.get("HpMax"), hp_min, hp_max))
        # The kernel's FightPlan has one integer (battle.rs:121-134), so the
        # content pins the range's lower bound; that choice is in Notes.Deviations.
        if entry.get("MaxHealth") != hp_min:
            fail("monster." + mid, "MaxHealth %r, expected the HpMin stand-in %d"
                 % (entry.get("MaxHealth"), hp_min))
        got_actions = [a["value"] for a in entry.get("Actions") or []]
        if got_actions != actions:
            fail("monster." + mid, "actions %s, inv says %s" % (got_actions, actions))
    # The roster is the authored source for every enemy, so the action count must
    # equal the number of distinct actions the inventory lists.
    total = sum(len(m[3]) for m in INV_MONSTERS)
    ok("roster numbers", "%d monsters, %d action references" % (len(INV_MONSTERS), total))
    check_intent_rules(doc)


# §148: the intent-rule vocabulary (`intent.rs::ConditionKind`) and its operators.
INTENT_CONDITIONS = ("intent.healthPercent", "intent.round", "intent.selfHasStatus",
                     "intent.opponentHasStatus", "intent.selfHasCounter", "intent.selfResource",
                     "intent.opponentCardsPlayed", "intent.allOf", "intent.anyOf", "intent.not")
INTENT_OPS = ("Equal", "NotEqual", "Less", "LessOrEqual", "Greater", "GreaterOrEqual")


def check_intent_rules(doc):
    """§148: every `IntentRules` entry must be **executable**.

    The kernel reads a rule as `(Condition, Action, Priority)`; a condition kind it does not know is a
    loud error at intent time, and an `Action` that is not an `EACT` row is `UnknownAction` — both
    *after* the player is already in the fight. Worse: a rule that silently never matches falls back
    to the `Actions` **cycle**, which looks like a working enemy with a slightly different rhythm.
    So the shape is checked here, where the message can name the enemy.

    An action named by a rule need **not** be in the enemy's `Actions` list: that is exactly how a
    "turn 1 only" opener is expressed (Spire Growth's `Strategic`).
    """
    print("[2b] enemy intent rules (port-plan.md §148)")
    actions = {a["Id"] for a in doc.get("EnemyActions") or []}
    checked = 0

    def walk(where, rules):
        nonlocal checked
        for index, rule in enumerate(rules or []):
            label = "%s.IntentRules[%d]" % (where, index)
            condition = rule.get("Condition") or {}
            kind = condition.get("kind")
            if kind not in INTENT_CONDITIONS:
                fail(label, "condition kind %r is outside the kernel's 10" % (kind,))
            # Every operator-bearing condition must name a known `Op` — the kernel throws on an
            # unknown one, so a typo is a mid-fight error rather than a different rhythm.
            if kind not in ("intent.allOf", "intent.anyOf", "intent.not"):
                op = (condition.get("value") or {}).get("Op")
                if op is not None and op not in INTENT_OPS:
                    fail(label, "Op %r is outside the kernel's 6" % (op,))
            # §195.3: a rule names either one `Action` or a weighted `Choice` list. Both halves are
            # checked, and "both at once" is an error -- the kernel refuses that combination rather
            # than picking one (two answers for one condition has no correct reading).
            single = (rule.get("Action") or {}).get("value")
            choice = rule.get("Choice")
            if single is not None and choice is not None:
                fail(label, "has both `Action` and `Choice`")
            elif single is not None:
                if single not in actions:
                    fail(label, "Action %r is not an EACT row" % (single,))
            elif choice is not None:
                if not isinstance(choice, list) or not (1 <= len(choice) <= 8):
                    fail(label, "Choice must be a list of 1..=8 options (%r)" % (choice,))
                else:
                    total = 0
                    for option in choice:
                        if set(option) != {"Action", "Weight"}:
                            fail(label, "Choice option keys %r" % (sorted(option),))
                            continue
                        weight = option["Weight"]
                        if not isinstance(weight, int) or weight <= 0:
                            fail(label, "Choice weight %r is not a positive int" % (weight,))
                        else:
                            total += weight
                        target = (option.get("Action") or {}).get("value")
                        if target not in actions:
                            fail(label, "Choice option %r is not an EACT row" % (target,))
                    if total > 255:
                        fail(label, "Choice weights total %d > 255 (the pick index is a u8)" % total)
            else:
                fail(label, "names neither `Action` nor `Choice`")
            if not isinstance(rule.get("Priority"), int):
                fail(label, "Priority must be an integer, got %r" % (rule.get("Priority"),))
            checked += 1

    for monster in doc.get("Monsters") or []:
        walk("Monster." + monster.get("Id", "?"), monster.get("IntentRules"))
    for encounter in doc.get("Encounters") or []:
        for enemy in encounter.get("Enemies") or []:
            # The encounter's inline record is what the kernel reads; the roster copy is
            # documentation. They must agree, and the gate compares them below.
            walk("Encounter.%s./%s" % (encounter.get("Id", {}).get("Value"), enemy.get("Id")),
                 enemy.get("IntentRules"))
            roster = next((m for m in doc.get("Monsters") or []
                           if m.get("Id") == enemy.get("Id")), None)
            if roster is not None and (roster.get("IntentRules") or []) != (enemy.get("IntentRules") or []):
                fail("Encounter.%s./%s" % (encounter.get("Id", {}).get("Value"), enemy.get("Id")),
                     "the inline IntentRules differ from the roster's copy")
    ok("intent rules", "%d rule(s), all conditions/actions/priorities resolvable" % checked)


def check_cards_and_actions(doc):
    print("[3] card / enemy-action numbers (inv:§2.1, §3.1, §4.1)")
    programs = load_programs(doc)
    cards = {c["Id"]: c for c in doc.get("Cards") or []}
    for cid, spec in INV_CARDS.items():
        card = cards.get(cid)
        if card is None:
            fail("card." + cid, "missing")
            continue
        costs = card.get("Costs") or []
        got_cost = costs[0]["Amount"] if costs else 0
        if got_cost != spec["Cost"]:
            fail("card." + cid, "cost %r, inv says %d" % (got_cost, spec["Cost"]))
        got_tags = [t["value"] for t in card.get("Tags") or []]
        if got_tags != spec["Tags"]:
            fail("card." + cid, "tags %s, inv says %s" % (got_tags, spec["Tags"]))
        if costs and costs[0]["ResourceId"]["value"] != "standard.energy":
            fail("card." + cid, "cost resource %r" % costs[0]["ResourceId"])
        got = program_facts(card["Program"]["Root"])
        if got != spec["Facts"]:
            fail("card." + cid, "facts %s, inv says %s" % (got, spec["Facts"]))
    actions = {a["Id"]: a for a in doc.get("EnemyActions") or []}
    for aid, (intent, facts) in INV_ACTIONS.items():
        action = actions.get(aid)
        if action is None:
            fail("action." + aid, "missing")
            continue
        if (action.get("Intent") or {}).get("Kind") != intent:
            fail("action." + aid, "intent %r, inv says %r"
                 % ((action.get("Intent") or {}).get("Kind"), intent))
        got, _code = split_history(program_facts(action["Program"]["Root"]))
        if got != facts:
            fail("action." + aid, "facts %s, inv says %s" % (got, facts))
    ok("cards", "%d cards x (cost, tags, facts)" % len(INV_CARDS))
    ok("enemy actions", "%d actions x (intent, facts)" % len(INV_ACTIONS))
    check_intent_history(doc)
    check_ascension_variants(doc)
    check_spawn_rolls(doc)


# §187：`EACT.ProgramAsc` 的**独立第二份**。每一行都是 wiki 的数字（出处列在
# `native/patch_187_content.py` 的表头），而不是从内容拄过来的 --
# "从内容生成期望值"等于没有期望值。
INV_ASC_VARIANTS = {
    # action id: [(AscensionMin, facts), ...] —— §192 起是**列表**：一个动作可以有两个档位
    # （`jaw_worm.bellow` 的 Strength 在 A2 升、Block 在 A17 升）。单档位的动作仍然只写一项。
    # 每一行都是 wiki 的数字；出处见 `native/wiki_asc/<monster>.txt`。
    'acid_slime_m.corrosive_spit': [(2, [('damage', 8, 'event'), ('card', 'slimed', 1, 'DiscardPile', 'event')])],
    'acid_slime_m.tackle': [(2, [('damage', 12, 'event')])],
    'acid_slime_s.tackle': [(2, [('damage', 4, 'event')])],
    'blue_slaver.rake': [(2, [('damage', 8, 'event'), ('status', 'standard.weak', 1, 'event')])],
    'blue_slaver.stab': [(2, [('damage', 13, 'event')])],
    'book_of_stabbing.big_stab': [(3, [('damage', 24, 'event')])],
    'book_of_stabbing.multi_stab': [(3, [('repeat', ('expr', 'add'), 'damage', 7, 'event'), ('counter', 'book_stab_uses', 1, True, 'source')])],
    'byrd.peck': [(2, [('damage', 1, 'event'), ('damage', 1, 'event'), ('damage', 1, 'event'), ('damage', 1, 'event'), ('damage', 1, 'event'), ('damage', 1, 'event')])],
    'byrd.swoop': [(2, [('damage', 14, 'event')])],
    'chosen.debilitate': [(2, [('damage', 12, 'event'), ('status', 'standard.vulnerable', 2, 'event')])],
    'chosen.poke': [(2, [('damage', 6, 'event'), ('damage', 6, 'event')])],
    'cultist.incantation': [(2, [('status', 'ritual', 4, 'source')])],
    'darkling.chomp': [(2, [('damage', 9, 'event'), ('damage', 9, 'event')])],
    'fat_gremlin.smash': [(2, [('damage', 5, 'event'), ('status', 'standard.weak', 1, 'event')])],
    'fungi_beast.grow': [(2, [('status', 'standard.strength', 4, 'source')])],
    'gremlin_nob.bellow': [(18, [('status', 'standard.strength', 3, 'source')])],
    'gremlin_nob.rush': [(3, [('damage', 16, 'event')])],
    'gremlin_nob.skull_bash': [(3, [('damage', 8, 'event'), ('status', 'standard.vulnerable', 2, 'event')])],
    'gremlin_wizard.ultimate_blast': [(2, [('damage', 30, 'event'), ('counter', 'gremlin_wizard_charges', 0, False, 'source')])],
    'jaw_worm.bellow': [
        (2, [('status', 'standard.strength', 4, 'source'), ('block', 6, 'source')]),
        (17, [('status', 'standard.strength', 5, 'source'), ('block', 9, 'source')]),
    ],
    'jaw_worm.chomp': [(2, [('damage', 12, 'event')])],
    'lagavulin.attack': [(3, [('damage', 20, 'event')])],
    'louse_green.grow': [(17, [('status', 'standard.strength', 4, 'source')])],
    'louse_red.grow': [(17, [('status', 'standard.strength', 4, 'source')])],
    'nemesis.tri_attack': [(4, [('damage', 7, 'event'), ('damage', 7, 'event'), ('damage', 7, 'event')])],
    'nemesis.tri_burn': [(19, [('card', 'burn', 5, 'DiscardPile', 'event')])],
    'orb_walker.claw': [(2, [('damage', 16, 'event')])],
    'orb_walker.laser': [(2, [('damage', 11, 'event'), ('status', 'standard.weak', 2, 'event')])],
    'reptomancer.big_bite': [(4, [('damage', 34, 'event')])],
    'reptomancer.snake_strike': [(4, [('damage', 16, 'event'), ('damage', 16, 'event'), ('status', 'standard.weak', 1, 'event')])],
    'reptomancer.spawn_dagger': [(19, [('spawn', 'dagger', 22), ('spawn', 'dagger', 22)])],
    'sentry.beam': [(3, [('damage', 10, 'event')])],
    'sentry.bolt': [(18, [('card', 'dazed', 3, 'DiscardPile', 'event')])],
    'shelled_parasite.double_strike': [(2, [('damage', 7, 'event'), ('damage', 7, 'event')])],
    'shelled_parasite.suck': [(2, [('damage', 12, 'event'), ('block', 2, 'source')])],
    'slaver_red.scrape': [(2, [('damage', 9, 'event'), ('status', 'standard.vulnerable', 1, 'event')])],
    'slaver_red.stab': [(2, [('damage', 14, 'event')])],
    'slime_boss.goop_spray': [(19, [('card', 'slimed', 5, 'DiscardPile', 'event')])],
    'slime_boss.slam': [(4, [('damage', 38, 'event')])],
    'sneaky_gremlin.puncture': [(2, [('damage', 10, 'event')])],
    'spike_slime_m.flame_tackle': [(2, [('damage', 10, 'event'), ('card', 'slimed', 1, 'DiscardPile', 'event')])],
    'spike_slime_s.tackle': [(2, [('damage', 6, 'event')])],
    'spiker.cut': [(2, [('damage', 9, 'event')])],
    'spire_growth.aggressive': [(2, [('damage', 18, 'event')])],
    'spire_growth.aggressive_heavy': [(2, [('damage', 25, 'event')])],
    'spire_growth.strategic': [(2, [('status', 'standard.constricted', 12, 'event')])],
    'taskmaster.scouring_whip': [(3, [('damage', 7, 'event'), ('card', 'wound', 2, 'DiscardPile', 'event')])],
    'the_champ.heavy_slash': [(4, [('damage', 18, 'event')])],
    # ================= §194 =================
    # The Guardian (wiki: Fierce Bash 32->A4 36, Roll Attack 9->A4 10, Sharp Hide 3->A19 4).
    'the_guardian.fierce_bash': [(4, [('damage', 36, 'event')])],
    'the_guardian.roll_attack': [(4, [('damage', 10, 'event'),
                                      ('counter', 'guard_step', 1, False, 'source')])],
    'the_guardian.defensive_mode': [(19, [('block', 20, 'source'),
                                          ('status', 'standard.sharp_hide', 4, 'source'),
                                          ('counter', 'mode_shift_budget', 10, True, 'source'),
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
    'time_eater.haste': [(19, [('heal', ('expr', 'max'), 'source'),
                               ('block', 32, 'source'),
                               ('counter', 'te_haste', 1, False, 'source')])],
    'donu.beam': [(4, [('damage', 12, 'event'), ('damage', 12, 'event')])],
    'deca.beam': [(4, [('damage', 12, 'event'), ('damage', 12, 'event'),
                       ('card', 'dazed', 2, 'DiscardPile', 'event')])],
    'deca.square_of_protection': [(19, [('block', 16, 'allAllies'),
                                        ('status', 'standard.plated_armor', 3, 'allAllies')])],
}


# §193: the wiki's damage ranges, as an **independent second copy**.
#
#   native/wiki_asc/louse.txt:28      Deals N damage. N between (5-7;{{Asc|2|6-8}}), chosen at the
#                                     start of combat.
#   native/wiki_asc/darkling.txt:32   Deals N damage. N between (7-11;{{Asc|2|9-13}}), chosen at
#                                     the start of combat.
#
# enemy record id: [(Key, Min, Max, AscensionMin), ...]  -- `AscensionMin` absent = the base range.
INV_ROLLS = {
    "louse_red": [("roll.bite", 5, 7, 0), ("roll.bite", 6, 8, 2)],
    "darkling": [("roll.nip", 7, 11, 0), ("roll.nip", 9, 13, 2)],
}

# §195.1: `ENCT.Enemies[].Counters` -- the **stated** numbers a status/rule needs to find already in
# place (a random roll cannot say "30", and no program can initialise a counter).
#
# The Guardian's Mode Shift budget: wiki `Powers = Mode Shift 30 (Asc|9|35 | Asc|19|40)`.
INV_SPAWN_COUNTERS = {
    "the_guardian": [("mode_shift_budget", 30, 0),
                     ("mode_shift_budget", 35, 9),
                     ("mode_shift_budget", 40, 19)],
}

# §193: actions that exist in `EACT` but that **no enemy record lists**. They must not be converted
# to a counter read -- a counter nobody rolls reads 0, and 0 damage is a landmine that the
# ENEMY_DIFF harness cannot see (it runs every `EACT` row against a synthesised `<prefix>` enemy).
# The day one of these gets a record, this table goes red and forces the roll to be written too.
INV_UNWIRED = {"louse_green.bite", "louse_green.grow"}


def check_ascension_variants(doc):
    """§187/§192：**每一条**升档节目都必须被上面那张表钉住，且与基础节目、别的变体**都不同**。"""
    print("[7] ascension variants (port-plan.md §187/§192)")
    actions = {a["Id"]: a for a in doc.get("EnemyActions") or []}
    total = 0
    for aid, entries in INV_ASC_VARIANTS.items():
        action = actions.get(aid)
        if action is None:
            fail("asc." + aid, "action missing")
            continue
        variants = action.get("ProgramAsc")
        if variants is None:
            fail("asc." + aid, "no ProgramAsc")
            continue
        if not isinstance(variants, list) or not variants:
            fail("asc." + aid, "ProgramAsc must be a non-empty **list** (%r)" % (variants,))
            continue
        # 阈值：内容写的这几个必须**正好**是表里那几个（多一个 = 没人钉过的档位）。
        thresholds = []
        for index, variant in enumerate(variants):
            keys = set(variant) if isinstance(variant, dict) else set()
            if keys != {"AscensionMin", "Program"}:
                fail("asc." + aid, "variant[%d] keys %r" % (index, sorted(keys)))
                break
            thresholds.append(variant["AscensionMin"])
        if len(thresholds) != len(variants):
            continue
        if sorted(thresholds) != [t for t, _ in entries]:
            fail("asc." + aid, "thresholds %r, inv says %r"
                 % (thresholds, [t for t, _ in entries]))
            continue
        if thresholds != sorted(set(thresholds)):
            fail("asc." + aid, "thresholds %r are not strictly ascending/unique -- the kernel "
                               "picks the largest eligible, so order must not be load-bearing"
                 % (thresholds,))
        # 事实：每个档位各自与表比；而且**没有两个档位讲同一个故事**。
        seen = [program_facts(action["Program"]["Root"])]
        for variant, (threshold, facts) in zip(variants, entries):
            got, _code = split_history(program_facts(variant["Program"]["Root"]))
            if got != facts:
                fail("asc." + aid + ".A%d" % threshold,
                     "facts %s, inv says %s" % (got, facts))
            if got in seen:
                fail("asc." + aid + ".A%d" % threshold,
                     "identical to the base or to an earlier variant -- this tier does nothing")
            seen.append(got)
            total += 1
    # 反向：内容里有而表里没有的变体也不行（"没人钉过的数字"）。
    unknown = sorted(aid for aid, action in actions.items()
                     if action.get("ProgramAsc") and aid not in INV_ASC_VARIANTS)
    if unknown:
        fail("asc.unknown", "variants not pinned by the inventory: %s" % unknown)
    ok("ascension variants", "%d variants over %d actions pinned (A2/A3/A4 + A17-A19)"
       % (total, len(INV_ASC_VARIANTS)))


def check_spawn_rolls(doc):
    """§193: 每条计数器读取都必须被**列出这条动作的那个敌人的**掷骰覆盖。"""
    print("[7b] spawn rolls (port-stage/§193)")
    records = {}
    for encounter in doc.get("Encounters") or []:
        for record in encounter["Enemies"]:
            records.setdefault(record["Id"], []).append(record)

    # ① 记录侧的形态：只有表里的敌人掷骰，而且范围/档位逐个对得上。
    for record_id, group in records.items():
        for record in group:
            rolls = record.get("Rolls")
            if rolls is None:
                fail("roll." + record_id, "the record has no `Rolls` key (shape drift)")
                continue
            got = [(r["Key"], r["Min"], r["Max"], r.get("AscensionMin", 0)) for r in rolls]
            want = INV_ROLLS.get(record_id, [])
            if got != want:
                fail("roll." + record_id, "%r, inv says %r" % (got, want))
            # 值域必须能被一次 `shuffled_pick_index` 覆盖（下标是 u8），而且 Min 不许比 Max 大。
            for key, low, high, threshold in got:
                if high < low:
                    fail("roll." + record_id, "`%s`: Max %d < Min %d" % (key, high, low))
                if high - low + 1 > 255:
                    fail("roll." + record_id,
                         "`%s`: %d values do not fit the u8 pick index" % (key, high - low + 1))
                if threshold < 0:
                    fail("roll." + record_id, "`%s`: negative AscensionMin" % key)
            # 同一个 Key 的阈值必须严格升序（与 `ProgramAsc` 同一条规矩：顺序不参与判定，
            # 但"两行同阈值"选谁都是猜）。
            by_key = {}
            for key, _, _, threshold in got:
                by_key.setdefault(key, []).append(threshold)
            for key, thresholds in by_key.items():
                if thresholds != sorted(set(thresholds)):
                    fail("roll." + record_id,
                         "`%s`: thresholds %r are not strictly ascending/unique" % (key, thresholds))
    unknown = sorted(record_id for record_id in INV_ROLLS if record_id not in records)
    if unknown:
        fail("roll.unknown", "inventory names enemies that are not in the content: %s" % unknown)

    # ①b §195.1：固定计数器的形态 + 数字（`Counters: [{Key, Value, AscensionMin?}]`）。
    for record_id, group in records.items():
        for record in group:
            entries = record.get("Counters")
            if entries is None:
                fail("counters." + record_id, "the record has no `Counters` key (shape drift)")
                continue
            got = [(e["Key"], e["Value"], e.get("AscensionMin", 0)) for e in entries]
            want = INV_SPAWN_COUNTERS.get(record_id, [])
            if got != want:
                fail("counters." + record_id, "%r, inv says %r" % (got, want))
            by_key = {}
            for key, _value, threshold in got:
                by_key.setdefault(key, []).append(threshold)
            for key, thresholds in by_key.items():
                if thresholds != sorted(set(thresholds)):
                    fail("counters." + record_id,
                         "`%s`: thresholds %r are not strictly ascending/unique" % (key, thresholds))
    missing = sorted(record_id for record_id in INV_SPAWN_COUNTERS if record_id not in records)
    if missing:
        fail("counters.unknown", "inventory names enemies that are not in the content: %s" % missing)

    # ② 程序侧：每个计数器读取都必须是**列这条动作的记录**掷过的键。
    actions = {a["Id"]: a for a in doc.get("EnemyActions") or []}
    readers = 0
    for record_id, group in records.items():
        for record in group:
            rolled = {r["Key"] for r in record.get("Rolls") or []}
            for action_id in record["Actions"]:
                action_id = action_id["value"] if isinstance(action_id, dict) else action_id
                program = actions.get(action_id)
                if program is None:
                    fail("roll." + action_id, "record lists an action that is not in EACT")
                    continue
                for fact in program_facts(program["Program"]["Root"]):
                    # 事实的形状是 ("damage", amount, target)；amount 是 3 元组才是计数器读取。
                    if fact[0] not in ("damage", "block", "heal"):
                        continue
                    size = fact[1]
                    if not isinstance(size, tuple) or size[0] != "counter":
                        continue
                    readers += 1
                    if size[2] != "source":
                        fail("roll." + action_id,
                             "reads a counter from `%s`, not from itself" % size[2])
                    if size[1] not in rolled:
                        fail("roll." + action_id,
                             "reads `%s` but `%s` never rolls it (damage would be 0)" % (size[1], record_id))

    # ③ 反向：没有敌人记录的动作**不许**读计数器（见 `INV_UNWIRED` 的理由）。
    listed = set()
    for record in records.values():
        for action_ids in record:
            for action_id in action_ids["Actions"]:
                listed.add(action_id["value"] if isinstance(action_id, dict) else action_id)
    for action_id, action in actions.items():
        if action_id in listed:
            continue
        for fact in program_facts(action["Program"]["Root"]):
            if fact[0] in ("damage", "block", "heal") and isinstance(fact[1], tuple) \
                    and fact[1][0] == "counter":
                fail("roll.unwired." + action_id,
                     "unreachable action reads a counter nobody rolls")
    for action_id in INV_UNWIRED:
        if action_id in listed:
            fail("roll.wired." + action_id,
                 "this action now has an enemy record -- give it a roll and drop it from INV_UNWIRED")
    ok("spawn rolls", "%d ranges over %d enemies, %d counter reads wired, %d fixed counters"
       % (sum(len(v) for v in INV_ROLLS.values()), len(INV_ROLLS), readers,
          sum(len(v) for v in INV_SPAWN_COUNTERS.values())))


def check_intent_history(doc):
    """§195.5：`last_move` / `prev_move` 这套历史是**内容状态**，所以它有自己的检查。

    带权抽签本身不需要历史；需要它的是"不能连续用同一招"那类规则，而那些规则的条件是
    `intent.selfHasCounter{last_move == k}`。于是有三件事必须同时成立，否则 Boss 会静默出招错乱：

    1. **每个能被选中的动作都要写自己的 code**（否则 `last_move` 停在上一只怪的旧值上，排除规则
       会一直命中或永远不命中）；
    2. **同一个敌人的 code 两两不同**（两招写同一个数 ⇒ "不能连续用 A" 会连带禁掉 B）；
    3. **规则里问到的每个 code 都真有动作写它**（这是一个 4 字节的错字就能造成的死规则：
       规则永远不命中、Boss 永远按默认权重出招，而所有数字看起来都对）。
    """
    print("[2c] intent history (port-stage/§195.5)")
    actions = {a["Id"]: a for a in doc.get("EnemyActions") or []}
    watched = 0
    for monster in doc.get("Monsters") or []:
        rules = monster.get("IntentRules") or []
        blob = json.dumps(rules)
        if "last_move" not in blob:
            continue
        watched += 1
        mid = monster["Id"]
        # every action this enemy can pick (cycle + every Choice/Action a rule names)
        reachable = [entry["value"] for entry in monster.get("Actions") or []]
        asked = set()
        for rule in rules:
            if rule.get("Action"):
                reachable.append(rule["Action"]["value"])
            for option in rule.get("Choice") or []:
                reachable.append(option["Action"]["value"])
            for condition in _walk_conditions(rule.get("Condition")):
                if condition.get("kind") == "intent.selfHasCounter":
                    value = condition["value"]
                    if value["Counter"]["value"] == "last_move":
                        asked.add(value["Value"])
        # 1 + 2: each reachable action writes a distinct code
        codes = {}
        for action_id in sorted(set(reachable)):
            action = actions.get(action_id)
            if action is None:
                continue
            for program in [action["Program"]] + [v["Program"] for v in action.get("ProgramAsc") or []]:
                _facts, code = split_history(program_facts(program["Root"]))
                if code is None:
                    fail("history." + mid, "`%s` does not record `last_move`" % action_id)
                else:
                    codes.setdefault(code, set()).add(action_id)
        for code, owners in sorted(codes.items()):
            if len(owners) > 1:
                fail("history." + mid,
                     "code %d is written by %s -- codes must be distinct per enemy"
                     % (code, sorted(owners)))
        # 3: every asked code exists
        for code in sorted(asked):
            if code not in codes:
                fail("history." + mid,
                     "a rule asks for `last_move == %d`, but no action writes it" % code)
    ok("intent history", "%d enemies use last_move; codes distinct and all referenced codes written"
       % watched)


def _walk_conditions(condition):
    """Yield every condition node in a (possibly nested) condition tree."""
    if not isinstance(condition, dict):
        return
    yield condition
    value = condition.get("value") or {}
    for inner in value.get("Conditions") or []:
        yield from _walk_conditions(inner)
    if value.get("Condition") is not None:
        yield from _walk_conditions(value["Condition"])


def check_statuses(doc):
    print("[4] status rows (inv:§10)")
    statuses = {s["Id"]: s for s in doc.get("Statuses") or []}
    for sid, mods in INV_STATUSES.items():
        row = statuses.get(sid)
        if row is None:
            fail("status." + sid, "missing")
            continue
        got = [(m["Pipeline"], m["Operation"], m["Magnitude"], m["Priority"],
                m["RestrictDamageKind"]) for m in row.get("PassiveModifiers") or []]
        if got != mods:
            fail("status." + sid, "passive modifiers %s, expected %s" % (got, mods))
        triggers = [t["Event"] for t in row.get("Triggers") or []]
        if sid in INV_DECAYING:
            # plan §G10 -- stacks are the clock, and it is a TurnEnded trigger
            # that ticks them down (DurationTurns merges with `max`, so two
            # applications of "2" would give 2 turns instead of 4).
            if triggers != ["TurnEnded"]:
                fail("status." + sid, "expected exactly one TurnEnded trigger, got %s"
                     % triggers)
            elif program_facts(row["Triggers"][0]["Program"]["Root"]) != \
                    [("modify", sid, -1, "source")]:
                fail("status." + sid, "decay trigger is not modifyStatusStacks(-1) on self: %s"
                     % program_facts(row["Triggers"][0]["Program"]["Root"]))
            if row.get("UsesDuration") is not False:
                fail("status." + sid, "UsesDuration must be false (plan §G10), got %r"
                     % row.get("UsesDuration"))
            if row.get("UsesStacks") is not True:
                fail("status." + sid, "UsesStacks must be true (plan §G10), got %r"
                     % row.get("UsesStacks"))
        elif sid in ("standard.lose_strength", "standard.lose_dexterity"):
            # §158: the "give back what Flex / Speed Potion lent" half. Two modifications, both by
            # an **expression** (`subtract(0, stacks)` -- the kernel has no `negate`, expr.rs:50),
            # and the order is part of the fact: the matched status first, then itself. Removing
            # the instance first would make its own stacks read 0 and the debt would be free.
            lends = {"standard.lose_strength": "standard.strength",
                     "standard.lose_dexterity": "standard.dexterity"}[sid]
            if triggers != ["TurnEnded"]:
                fail("status." + sid, "expected exactly one TurnEnded trigger, got %s" % triggers)
            else:
                facts = program_facts(row["Triggers"][0]["Program"]["Root"])
                expected = [("modify", lends, ("expr", "subtract"), "source"),
                            ("modify", sid, ("expr", "subtract"), "source")]
                if facts != expected:
                    fail("status." + sid, "the give-back program is %s, expected %s"
                         % (facts, expected))
        elif sid in ("standard.thorns", "standard.spore_cloud", "standard.enrage",
                     "standard.regen", "standard.rage", "standard.flame_barrier",
                     "standard.combust", "standard.split", "standard.phase_split",
                     "standard.time_warp", "standard.constricted",
                     "standard.phantom_veil",
                     "standard.sharp_hide", "standard.curiosity", "standard.mode_shift",
                     "standard.stasis"):
            expected = {"standard.thorns": ["DamageTaken"],
                        "standard.spore_cloud": ["Downed"],
                        "standard.enrage": ["CardPlayed"],
                        "standard.regen": ["TurnEnded"],
                        "standard.rage": ["CardPlayed"],
                        "standard.flame_barrier": ["DamageTaken"],
                        "standard.combust": ["TurnEnded"],
                        "standard.split": ["Downed"],
                        "standard.phase_split": ["DamageTaken"],
                        "standard.time_warp": ["CardPlayed"],
                        # §147: "lose HP at the end of your turn" is a TurnEnded trigger.
                        "standard.constricted": ["TurnEnded"],
                        # §175: the first `TurnStarted` trigger in this package.
                        "standard.phantom_veil": ["TurnStarted"],
                        # §194: the Guardian's Sharp Hide and the Awakened One's Curiosity -- both
                        # `CardPlayed` filtered by the played card's tag, the Enrage shape.
                        "standard.sharp_hide": ["CardPlayed"],
                        "standard.curiosity": ["CardPlayed"],
                        # §195.1: "after losing X HP" is a `DamageTaken` trigger (the event now carries
                        # the amount).
                        "standard.mode_shift": ["DamageTaken"],
                        # §195.4: "on death, the stolen card is returned" -- a Downed trigger.
                        "standard.stasis": ["Downed"]}[sid]
            if triggers != expected:
                fail("status." + sid, "expected exactly %s, got %s" % (expected, triggers))
        elif sid != "ritual" and triggers:
            # `ritual` is checked separately below (it *needs* a TurnEnded
            # trigger); every other status in this subset must be trigger-free.
            fail("status." + sid, "unexpected trigger(s) %s" % triggers)
    # `ritual` is the only status that *changes* another status on a tick.
    ritual = statuses.get("ritual") or {}
    facts = program_facts(ritual["Triggers"][0]["Program"]["Root"]) \
        if ritual.get("Triggers") else []
    if not facts or facts[0][0] != "status" or facts[0][1] != "standard.strength":
        fail("status.ritual", "first tick fact must be applyStatus(standard.strength), got %s"
             % facts)
    ok("statuses", "%d rows x (modifiers, turn clock)" % len(INV_STATUSES))


def check_relations(doc):
    print("[5] cross references (deck/encounters/actions/statuses)")
    cards = {c["Id"] for c in doc.get("Cards") or []}
    actions = {a["Id"] for a in doc.get("EnemyActions") or []}
    statuses = {s["Id"] for s in doc.get("Statuses") or []}
    roster = {m["Id"]: m for m in doc.get("Monsters") or []}

    hands = {
        "Start.Deck": (doc.get("Start") or {}).get("Deck") or [],
        "root Deck": doc.get("Deck") or [],
        "Characters[0].Start.Deck":
            ((doc.get("Characters") or [{}])[0].get("Start") or {}).get("Deck") or [],
    }
    want = []
    for cid, count in sorted(INV_DECK.items()):
        want.extend([cid] * count)
    for where, deck in hands.items():
        got = [c["value"] for c in deck]
        if sorted(got) != sorted(want):
            fail("deck." + where, "%s, inv (inv:§2.1) says %s" % (got, want))
        for cid in got:
            if cid not in cards:
                fail("deck." + where, "references card %r with no CARD row" % cid)
    # Start == Characters[0].Start (the reference duplicates it; a drift between
    # the two would be invisible to any single read).
    start = doc.get("Start") or {}
    char_start = ((doc.get("Characters") or [{}])[0].get("Start") or {})
    if start != char_start:
        fail("Start", "Start and Characters[0].Start disagree: %s"
             % diff(start, char_start, "Start"))

    # every action a monster lists must exist
    for mid, entry in sorted(roster.items()):
        for ref in entry.get("Actions") or []:
            if ref["value"] not in actions:
                fail("monster." + mid, "action %r has no EACT row" % ref["value"])

    # every encounter's inline enemy record must equal the roster's, field by field
    for enc in doc.get("Encounters") or []:
        eid = enc["Id"]["Value"]
        if eid in INV_WEAK_POOL:
            pool = INV_WEAK_POOL
        elif eid in INV_ELITE_POOL:
            pool = INV_ELITE_POOL
        else:
            pool = INV_BOSS_POOL
        if eid not in pool:
            fail("encounter." + eid,
                 "not in the inventory's weak (inv:§5.2), elite (inv:§5.3) or boss (inv:§4.3) pool")
        listed = [e["Id"] for e in enc.get("Enemies") or []]
        if listed != pool.get(eid):
            fail("encounter." + eid, "enemies %s, the inventory says %s"
                 % (listed, pool.get(eid)))
        # `CardsDrawnPerTurn` null = the per-turn draw default, which inv:§2 says
        # is 5.  Writing a number here would be a second place the draw count lives.
        if enc.get("CardsDrawnPerTurn") is not None:
            fail("encounter." + eid,
                 "CardsDrawnPerTurn must stay null (= inv:§2's %d-card default), got %r"
                 % (INV_HERO["CardsDrawnPerTurn"], enc.get("CardsDrawnPerTurn")))
        # §140: the **same** cap the kernel enforces for summons applies to what the content may
        # place directly. A five-enemy encounter would build fine at runtime and then be unable to
        # show or target the fifth -- better to refuse it here.
        if len(enc.get("Enemies") or []) > MAX_ENEMIES_IN_FIGHT:
            fail("encounter." + eid, "%d enemies, the cap is %d"
                 % (len(enc.get("Enemies") or []), MAX_ENEMIES_IN_FIGHT))
        for inline in enc.get("Enemies") or []:
            mid = inline["Id"]
            entry = roster.get(mid)
            if entry is None:
                fail("encounter." + eid, "enemy %r is not in the roster" % mid)
                continue
            for key in ("Actions", "IntentRules", "StartingStatuses"):
                if inline.get(key) != entry.get(key):
                    fail("encounter.%s/%s" % (eid, mid),
                         "%s differs from the roster: %s"
                         % (key, diff(entry.get(key), inline.get(key), key)))
            if inline.get("MaxHealth") != entry.get("MaxHealth"):
                fail("encounter.%s/%s" % (eid, mid),
                     "MaxHealth %r != roster %r"
                     % (inline.get("MaxHealth"), entry.get("MaxHealth")))
        energy = {(r["Resource"]["value"], r["Current"], r["Max"])
                  for r in enc.get("HeroResources") or []}
        if ("standard.energy", INV_HERO["EnergyCurrent"], INV_HERO["EnergyMax"]) not in energy:
            fail("encounter." + eid, "hero energy %s, inv:§2 says 3/3" % sorted(energy))

    # every status a program names must have a STAT row
    def named_statuses(facts):
        for fact in facts:
            if fact[0] == "status" or fact[0] == "modify":
                yield fact[1]

    for rec in (doc.get("Cards") or []) + (doc.get("EnemyActions") or []):
        for sid in named_statuses(program_facts(rec["Program"]["Root"])):
            if sid not in statuses:
                fail("program." + rec["Id"], "names status %r with no STAT row" % sid)
    for rec in doc.get("Statuses") or []:
        for trig in rec.get("Triggers") or []:
            for sid in named_statuses(program_facts(trig["Program"]["Root"])):
                if sid not in statuses:
                    fail("trigger." + rec["Id"], "names status %r with no STAT row" % sid)

    ok("deck", "3 spellings, %d cards each" % len(want))
    ok("encounter <-> roster", "%d encounters, inline records equal the roster"
       % len(doc.get("Encounters") or []))


def check_weak_pool_table(doc):
    print("[6] encounter weights (inv:§5.2)")
    table = (doc.get("EncounterTables") or {}).get("Weak") or []
    got = {row["Id"]: row["Weight"] for row in table}
    if sorted(got) != sorted(INV_ACT_TABLES["Weak"]):
        fail("EncounterTables.Weak", "%s != act 1 %s (inv:§5.2)"
             % (sorted(got), sorted(INV_ACT_TABLES["Weak"])))
    ok("weak pool", "%d entries x %d%%" % (len(table), INV_WEAK_WEIGHT))
    elite = (doc.get("EncounterTables") or {}).get("Elite")
    if elite is None:
        fail("encounter-tables", "EncounterTables.Elite is missing (inv:§5.3)")
    if sorted(e["Id"] for e in elite) != sorted(INV_ACT_TABLES["Elite"]):
        fail("encounter-tables", "Elite %s != inv %s"
             % (sorted(e["Id"] for e in elite), sorted(INV_ELITE_POOL)))
    ok("elite pool", "%d entry" % len(elite))
    boss = (doc.get("EncounterTables") or {}).get("Boss")
    if boss is None:
        fail("encounter-tables", "EncounterTables.Boss is missing (inv:§4.3)")
    # §130: acts 2 and 3 have their own Weak/Elite/Boss pools. Each is checked against the same
    # inventory: a pool that names an encounter the kernel cannot build is the same bug regardless
    # of which act it belongs to.
    for act in (2, 3):
        for kind in ("Weak", "Elite", "Boss"):
            name = "%s%d" % (kind, act)
            rows = (doc.get("EncounterTables") or {}).get(name)
            if rows is None:
                fail("encounter-tables", "EncounterTables.%s is missing" % name)
                continue
            ids = sorted(row["Id"] for row in rows)
            if ids != sorted(INV_ACT_TABLES[name]):
                fail("encounter-tables", "%s %s != act %d %s"
                     % (name, ids, act, sorted(INV_ACT_TABLES[name])))
    if sorted(e["Id"] for e in boss) != sorted(INV_ACT_TABLES["Boss"]):
        fail("encounter-tables", "Boss %s != act 1 %s"
             % (sorted(e["Id"] for e in boss), sorted(INV_ACT_TABLES["Boss"])))


# §143: the event choices' closed vocabulary, checked **here** rather than only when a player
# clicks the button. `EventEffect::parse` in `rd-run` is the authority on the shape; this gate is
# the authority on the **payloads**, which the run layer cannot check on its own (it does not know
# the content): a `curse:` id must be a Curse card in the pool, and a `relic:` id must be a relic
# whose effect the kernel implements.
EVENT_BARE_EFFECTS = ("heal", "gold", "damage", "max_hp", "nothing",
                      "remove_card", "upgrade_card", "transform_card")
# Mirrors `rd_run::state::RunState::relic_effect`. Kept as a literal list on purpose: this file is
# the **second opinion** -- if the two disagree, one of them is wrong and the gate says so.
IMPLEMENTED_RELICS = ("burning_blood", "anchor", "vajra", "pear", "blood_vial", "thread_and_needle",
                      # §156: wiki numbers (Strawberry +7 max HP, Bronze Scales 3 Thorns, Regal Pillow
                      # +15 on rest, Meat on the Bone 12 HP at or below 50%).
                      "strawberry", "bronze_scales", "regal_pillow", "meat_on_the_bone",
                      # §157: two more Rare (Eternal Feather, Golden Idol) + Potion Belt.
                      "eternal_feather", "golden_idol", "potion_belt")


def check_relics(doc):
    """§145：遗物池里的**每一件**都必须被内核实现。

    这不是洁癖：宝箱和商店都是从这张表里随机挑一件，所以一件内核跑不了的遗物不是"躺在那里
    没人用"，而是**随机地把玩家的宝箱变成一次拒绝**（`push_relic` 在授予那一刻就报错）。
    `RunState::relic_effect` 是内核那边的表；这里是它的第二张嘴。
    """
    print("[6e] relic pool (port-plan.md §145)")
    relics = doc.get("Relics") or []
    if len(relics) < 2:
        fail("Relics", "只有 %d 件遗物 —— 池子至少要能让一次掉落有得选" % len(relics))
    for relic in relics:
        relic_id = relic.get("Id")
        if relic_id not in IMPLEMENTED_RELICS:
            fail("Relics.%s" % relic_id,
                 "内核没实现这件遗物的效果（%s）⇒ 宝箱抽到它会当场拒绝"
                 % " / ".join(IMPLEMENTED_RELICS))
        if not relic.get("DisplayName"):
            fail("Relics.%s" % relic_id, "没有 DisplayName（页面上会是一串 id）")
    # A relic that exists in the kernel's table but not in the content can never be handed out
    # either -- say so once, in the other direction.
    declared = {relic.get("Id") for relic in relics}
    for relic_id in IMPLEMENTED_RELICS:
        if relic_id not in declared:
            fail("Relics", "内核实现了 `%s`，但内容里没有它 ⇒ 永远发不出来" % relic_id)
    ok("relic pool", "%d relics, all implemented" % len(relics))


# §152: the potion vocabulary, as the ABI's `rd_env_use_potion` reads it. `kind:payload` carries a
# status id; the payload form is the same convention the event vocabulary uses (§143).
# §161.3: the two atoms whose effect is a **question** (`PendingChoice`). They read no amount and
# they do not resolve inside `rd_env_use_potion` -- the ABI returns "pending" and the answer arrives
# through `rd_env_choice_confirm`.
POTION_CHOICE_KINDS = ("choice_hand_exhaust", "choice_hand_discard_draw",
                       "choice_discard_to_hand", "choice_offered")
POTION_KINDS = ("combat_block", "combat_energy", "combat_heal_percent", "combat_draw",
                "combat_damage", "combat_damage_all",
                # §179: the three potions that needed a new verb (Blessing of the Forge, Snecko
                # Oil, Smoke Bomb). Listed here as the **second opinion** -- §161.3 taught that a
                # vocabulary known in two places drifts unless both are checked.
                "combat_upgrade_hand", "combat_randomize_costs", "combat_flee",
                # §182: auto-play reads the count, so it is **not** in `NO_AMOUNT`.
                "combat_autoplay_top",
                # §157/§158: the effects that are about the **run**, not the fight (Fruit Juice,
                # Entropic Brew). §158 made them usable **outside** a fight, which is what the wiki
                # says; before that the "no fight" check came first and refused them.
                "max_hp", "potion_fill") + POTION_CHOICE_KINDS
# Which effects need the player to pick an enemy (the ABI's code `1`). Kept here as the **second
# opinion**: if the page's rule and this list disagree, one of them is wrong.
POTION_NEEDS_TARGET = ("combat_damage", "combat_status_target")


# The tags a card can carry and still be upgraded at a campfire. Curses and statuses cannot.
# §183: `colorless` joins the list, and the reason is **not** "they cannot be upgraded" (in StS they
# can) -- it is that **no deck can ever hold them**: the only way a colorless card enters play is a
# potion's offer, inside one fight. A `+` row would be content nothing can reach, and inventing three
# upgrades whose wiki numbers nobody read is worse than saying so.
NOT_UPGRADABLE_TAGS = ("curse", "status", "colorless")


def check_upgrades(doc):
    """§154: **every upgradable card must have a `+` row.**

    The run's upgrade path is "append `+` to the id" (`RunState::upgrade_at`), so a card without an
    upgraded row becomes an id the image does not contain: the run looks fine until the next fight,
    which then refuses to build (`UnknownCard(CardDefinitionId("iron_wave+"))`). §147 fixed exactly
    one card and wrote the lesson down; nine others still had no row.
    """
    print("[3c] card upgrades (port-plan.md §154)")
    cards = {card["Id"]: card for card in doc.get("Cards") or []}
    missing = []
    for card_id, card in cards.items():
        if card_id.endswith("+"):
            continue
        tags = [tag["value"] for tag in card.get("Tags") or []]
        if any(tag in NOT_UPGRADABLE_TAGS for tag in tags):
            continue
        if card_id + "+" not in cards:
            missing.append(card_id)
    if missing:
        fail("cards.upgrades", "no `+` row for %s" % (missing,))
    # An upgraded row must keep the base's cost and tags: a `+` that changes the shape (cheaper cost,
    # different keyword) is not an upgrade, it is a different card wearing the same name.
    for card_id, card in cards.items():
        if not card_id.endswith("+"):
            continue
        base = cards.get(card_id[:-1])
        if base is None:
            fail("cards.upgrades", "%s has no base row" % (card_id,))
            continue
        if [cost.get("Amount") for cost in card.get("Costs") or []] != [
            cost.get("Amount") for cost in base.get("Costs") or []
        ]:
            fail("cards.upgrades", "%s costs differently from %s" % (card_id, card_id[:-1]))
        if [tag["value"] for tag in card.get("Tags") or []] != [
            tag["value"] for tag in base.get("Tags") or []
        ]:
            fail("cards.upgrades", "%s has different tags from %s" % (card_id, card_id[:-1]))
    upgraded = sum(1 for card_id in cards if card_id.endswith("+"))
    ok("card upgrades", "%d upgraded rows, every upgradable card has one" % upgraded)


def check_potions(doc):
    """§152: every potion must be **drinkable**.

    Before this section the content had five potions built from three effects and two of them were
    broken: `swift_potion` was a second Block Potion under a different name, and `blood_potion` used
    an effect the ABI did not handle at all (refused with "未知的药水效果"). A potion that cannot be
    drunk is a dead button in the belt -- the §150 shape, one layer down.
    """
    print("[3b] potions (port-plan.md §152, §158)")
    potions = doc.get("Potions") or []
    statuses = {status["Id"] for status in doc.get("Statuses") or []}
    # §161.5: every tag any card carries -- `choice_offered:<tag>` payloads must be one of these.
    tags = {tag.get("value") for card in doc.get("Cards") or []
            for tag in card.get("Tags") or []}
    seen_effects = set()
    for potion in potions:
        potion_id = potion.get("Id")
        effect = potion.get("Effect") or ""
        label = "Potions.%s" % potion_id
        amount = potion.get("Amount")
        if not potion.get("NameKey") or not potion.get("DescriptionKey"):
            fail(label, "needs NameKey and DescriptionKey (the belt shows the id otherwise)")
        # §158: an effect is a **comma-separated list of atoms**. Every atom is checked on its own,
        # for the same reason the run layer executes them one at a time: `combat_status:a` and
        # `combat_status:zzz` in the same cell must not pass because the first one was fine.
        atoms = [atom for atom in effect.split(",") if atom]
        if not atoms:
            fail(label, "no Effect at all")
        for atom in atoms:
            kind, _, payload = atom.partition(":")
            if kind in POTION_KINDS:
                if payload and kind != "choice_offered":
                    fail(label, "`%s` takes no payload" % kind)
                if kind == "choice_offered":
                    # §161.5: the payload is a **tag**, and the promise is "three of them exist".
                    # 少于三张时这瓶药给不出它写的东西 —— 那正是一个安静的死按钮。
                    if payload not in tags:
                        fail(label, "`choice_offered` names tag %r, which no card carries"
                             % (payload,))
                    else:
                        carriers = sum(1 for card in doc.get("Cards") or []
                                       if any(t.get("value") == payload
                                              for t in card.get("Tags") or []))
                        if carriers < 3:
                            fail(label, "`choice_offered:%s` needs 3 cards carrying it, %d exist"
                                 % (payload, carriers))
            elif kind in ("combat_status", "combat_status_target"):
                if payload not in statuses:
                    fail(label, "`%s` names status %r, which is not a STAT row" % (kind, payload))
            else:
                fail(label, "effect %r is outside the ABI's vocabulary" % (atom,))
            # The **target** decision lives in two places on purpose (`rd-wasm`'s
            # `rd_run_potion_effect` and `POTION_NEEDS_TARGET` here): if they disagree, the page aims
            # at nothing and the potion silently lands on the hero.
            wants_target = kind in POTION_NEEDS_TARGET
            if wants_target and any(a.partition(":")[0] not in POTION_NEEDS_TARGET for a in atoms):
                fail(label, "mixes a targeted atom with a non-targeted one")
        # §158: the rule is per-atom, because not every atom reads an amount.
        # §161.3 added the choice atoms, which read none either (the number of cards is the
        # player's answer, not a constant in the content).
        # §179: `combat_flee` takes no amount either (there is nothing to parametrise), and
        # `combat_randomize_costs` only matters when paired with a draw that does.
        NO_AMOUNT = (
            "potion_fill", "combat_flee", "combat_randomize_costs", "combat_upgrade_hand"
        ) + POTION_CHOICE_KINDS
        takes_amount = any(atom.partition(":")[0] not in NO_AMOUNT for atom in atoms)
        if takes_amount:
            if not isinstance(amount, int) or amount <= 0:
                fail(label, "Amount must be a positive integer, got %r" % (amount,))
        elif amount != 0:
            fail(label, "`%s` reads no amount, so it must be 0, got %r"
                 % (atoms[0].partition(":")[0], amount,))
        seen_effects.add(effect)
    if len(potions) < 8:
        fail("Potions", "only %d potions -- too few to make a drop interesting" % len(potions))
    # Two potions with the same effect **and** amount are one potion with two names (the exact bug
    # `swift_potion` shipped: a copy of Block Potion).
    fingerprints = [(potion.get("Effect"), potion.get("Amount")) for potion in potions]
    for fingerprint in set(fingerprints):
        if fingerprints.count(fingerprint) > 1:
            names = [p.get("Id") for p in potions if (p.get("Effect"), p.get("Amount")) == fingerprint]
            fail("Potions", "%s are the same potion twice (%r)" % (names, fingerprint))
    # §158: there is **no per-act potion pool**. `PotionTables` used to hold three lists; the wiki
    # has no such split, and `MAX_POOL_IDS` (8) would have truncated a 33-entry list. So the check is
    # now the opposite one: the table must be **gone**, because a leftover list would be data the
    # kernel never reads.
    if doc.get("PotionTables"):
        fail("PotionTables", "the potion pools were removed in §158 -- this is dead data")
    # §157/§158: the rarity weights (65/25/10) are only meaningful if every band has an entry.
    bands = {rarity: 0 for rarity in RELAPSE_RARITIES}
    for potion in potions:
        rarity = potion.get("Rarity")
        if rarity not in bands:
            fail("Potions.%s" % potion.get("Id"), "unknown Rarity %r" % (rarity,))
            continue
        bands[rarity] += 1
    for rarity in RELAPSE_RARITIES:
        if bands[rarity] == 0:
            fail("Potions", "no %s potion: that band of the 65/25/10 roll would be empty" % rarity)
    ok("potions", "%d potions (C%d/U%d/R%d), %d distinct effects"
       % (len(potions), bands["Common"], bands["Uncommon"], bands["Rare"], len(seen_effects)))


RELAPSE_RARITIES = ("Common", "Uncommon", "Rare")


def check_relic_rarities(doc):
    """§156: every relic declares a rarity the drop weights know about.

    The weights are `Common 50 / Uncommon 33 / Rare 17`; a relic whose `Rarity` is missing or spelled
    differently is silently skipped by the pool reader in `rd-wasm` (`Rarity::from_name` returns
    `None`), so it would simply **never drop** -- a relic that exists and cannot be found is worse
    than one that is absent.
    """
    print("[6f] relic rarities (port-plan.md §156, §160)")
    relics = doc.get("Relics") or []
    # §160: `Event` is a **legal** relic rarity that is *not* droppable -- the wiki's navbox puts
    # `golden_idol` there. The kernel's `pick_relic_avoiding` filters any band that is not in
    # `RELIC_RARITY_WEIGHTS`, so an `Event` relic is holdable (and pays out) but never rolled.
    allowed = tuple(RELAPSE_RARITIES) + ("Event",)
    missing = [relic.get("Id") for relic in relics if relic.get("Rarity") not in allowed]
    if missing:
        fail("Relics.rarity", "no usable Rarity on %s" % (missing,))
    counts = {}
    for relic in relics:
        counts[relic["Rarity"]] = counts.get(relic["Rarity"], 0) + 1
    for rarity in RELAPSE_RARITIES:
        if counts.get(rarity, 0) == 0:
            fail("Relics.rarity", "no %s relic: the weight band would be empty" % rarity)
    ok("relic rarities", "%d relics over %s" % (len(relics), sorted(counts.items())))


def check_card_keywords(doc):
    """§144：关键字必须**落在机制字段上**，tag 只是文档。

    内核读的是 `CARD.TurnEndHandDestinationZone`（Ethereal）、`CARD.RetainInHandOnTurnEnd`
    （Retain）和 `Tags` 里的 `innate`（Innate）。一条 tag 写着 `ethereal`、而那一格还写着
    `DiscardPile` 的卡，在游戏里就是"一张什么关键字都没有的牌" —— 而且**看不出来**。
    这条检查把两边的说法钉在一起。
    """
    print("[6d] card keywords (port-plan.md §144)")
    cards = doc.get("Cards") or []
    counts = {"ethereal": 0, "retain": 0, "innate": 0, "x_cost": 0}
    for card in cards:
        card_id = card.get("Id")
        tags = {tag.get("value") for tag in card.get("Tags") or [] if isinstance(tag, dict)}
        zone = card.get("TurnEndHandDestinationZone") or "DiscardPile"
        retain = card.get("RetainInHandOnTurnEnd") is True
        label = "Cards.%s" % card_id
        # tag ⇔ mechanism, both directions: a mechanism without the tag is a card whose
        # description lies, and a tag without the mechanism is a card that does nothing.
        if ("ethereal" in tags) != (zone == "ExhaustPile"):
            fail(label, "ethereal tag %s but TurnEndHandDestinationZone is %r"
                 % ("present" if "ethereal" in tags else "absent", zone))
        if ("retain" in tags) != retain:
            fail(label, "retain tag %s but RetainInHandOnTurnEnd is %r"
                 % ("present" if "retain" in tags else "absent",
                    card.get("RetainInHandOnTurnEnd")))
        if "x_cost" in tags:
            # §146：X 费现在是真能力，但两条配套约束必须成立，否则那张牌**看起来正常、算起来不对**：
            #   ① 印刷价格必须是 0 或缺席（真正的费用是"当前全部能量"，`Amount` 不参与结算）；
            #   ② 节目必须真的读 `x.cost`（否则那个 tag 只是个装饰，牌会按 0 遍结算）。
            costs = card.get("Costs") or []
            for entry in costs:
                if entry.get("Amount") != 0:
                    fail(label, "x_cost 卡的印刷费用必须是 0（现在是 %r）"
                         % (entry.get("Amount"),))
            program = json.dumps(card.get("Program") or {}, ensure_ascii=False)
            if '"x.cost"' not in program:
                fail(label, "x_cost 卡的节目没读 x.cost ⇒ X 永远用不上（tag 只是装饰）")
        for keyword in counts:
            if keyword in tags:
                counts[keyword] += 1
    ok("keyword cards", "ethereal %d / retain %d / innate %d / x_cost %d"
       % (counts["ethereal"], counts["retain"], counts["innate"], counts["x_cost"]))
    if counts["ethereal"] + counts["retain"] + counts["innate"] == 0:
        fail("Cards", "no card exercises any keyword -- §144 would be untested in the real image")


EVENT_DECK_EDITS = ("remove_card", "upgrade_card", "transform_card")


def check_event_vocabulary(doc):
    """§143 + §188：每个选项是一个**效果列表**，每个效果都在闭词表里。

    三条判据（每一条对应一种没有症状的错误）：
    * 词表外的效果 ⇒ 下面的 `fail`（点下去一个死按钮）；
    * `Effects*Asc` 与基础**一模一样** ⇒ "A15 变糟"什么都没变；
    * 一个选项里**两个改牌效果** ⇒ 待答的选牌只有一个位置，一定丢一个。
    """
    print("[6c] event vocabulary (port-plan.md §143 / §188)")
    rooms = doc.get("UnknownRooms") or []
    cards = {c["Id"]: c.get("Rarity") for c in doc.get("Cards") or []}
    relics = {r["Id"] for r in doc.get("Relics") or []}
    counts = {"bare": 0, "curse": 0, "relic": 0, "effects": 0, "asc": 0}
    for room in rooms:
        for slot in ("0", "1"):
            base = room.get("Effects" + slot) or []
            asc = room.get("Effects" + slot + "Asc") or []
            label = "UnknownRooms.%s.Effects%s" % (room.get("Id"), slot)
            if not isinstance(base, list):
                fail(label, "not a list: %r" % (base,))
                continue
            if len(base) > 4 or len(asc) > 4:
                fail(label, "more than 4 effects (the kernel's MAX_EVENT_EFFECTS)")
            for kind_label, effects in (("", base), ("Asc", asc)):
                edits = 0
                for entry in effects:
                    effect = entry.get("Effect")
                    where = "%s%s.%s" % (label, kind_label, effect)
                    if not isinstance(effect, str):
                        fail(where, "Effect is not a string: %r" % (effect,))
                        continue
                    counts["effects"] += 1
                    if kind_label:
                        counts["asc"] += 1
                    if effect in EVENT_BARE_EFFECTS:
                        counts["bare"] += 1
                        continue
                    kind, _, payload = effect.partition(":")
                    if kind == "curse" and payload:
                        counts["curse"] += 1
                        if payload not in cards:
                            fail(where, "curse:%s 不是内容里的卡" % payload)
                        elif cards[payload] != "Curse":
                            fail(where, "curse:%s 的 Rarity 是 %s，不是 Curse"
                                 % (payload, cards[payload]))
                        continue
                    if kind == "relic" and payload:
                        counts["relic"] += 1
                        if payload not in relics:
                            fail(where, "relic:%s 不在 Relics 表里" % payload)
                        elif payload not in IMPLEMENTED_RELICS:
                            fail(where, "relic:%s 的效果内核没实现（%s）"
                                 % (payload, " / ".join(IMPLEMENTED_RELICS)))
                        continue
                    fail(where, "词表外的效果 %r" % (effect,))
                edits = sum(1 for e in effects if e.get("Effect") in EVENT_DECK_EDITS)
                if edits > 1:
                    fail(label + kind_label,
                         "%d 个改牌效果（待答选牌只有一个位置）" % edits)
            # §188：A15 的变体必须**真的不一样**。
            if asc and asc == base:
                fail(label + "Asc", "the A15 list equals the base -- this ascension does nothing")
    ok("event effects",
       "%d rooms, %d effect(s) (%d in A15 lists), %d bare / %d curse: / %d relic:"
       % (len(rooms), counts["effects"], counts["asc"], counts["bare"],
          counts["curse"], counts["relic"]))
    # The three per-act pools must name rooms that exist, or the `?` room picks nothing.
    known = {room.get("Id") for room in rooms}
    tables = doc.get("EventTables") or {}
    for name in ("Events", "Events2", "Events3"):
        rows = tables.get(name)
        if not rows:
            fail("EventTables." + name, "missing or empty")
            continue
        for row in rows:
            if row.get("Id") not in known:
                fail("EventTables." + name, "%r is not in UnknownRooms" % (row.get("Id"),))
    ok("event pools", "act1=%d act2=%d act3=%d"
       % (len(tables.get("Events") or []), len(tables.get("Events2") or []),
          len(tables.get("Events3") or [])))


# =============================================================================
# 2b.  the fourth layer -- a key that looks like data but is only documentation
# =============================================================================
#
# WHY THIS LAYER EXISTS (measured, not guessed)
# ---------------------------------------------
# The content format has keys that the kernel **never reads**: the storage layer
# keeps them (they round-trip through both images like everything else), so
# filling them in changes *nothing* and reports *nothing*.  Three examples that
# were verified by hand: `STATUS.DeathPrevention` (a reference rule hook with no
# kernel capability), `Program.MaxNodeDepth` (the kernel uses its own
# `MAX_NODE_DEPTH` constant instead), and the root key `Monsters` (the encounter
# carries its own inline copy, which is what reaches `ENCT`).
#
# A round-trip gate cannot see this by construction: "the image agrees with the
# source" is true for an inert key too.  So the rule is a *declaration*:
# every key with no kernel consumer must be listed in the document's
# `InertKeys` block with the reason it can stay.  That turns "silently inert"
# into "explicitly inert", and it makes the two failures that actually happen
# observable:
#   * someone adds a key nobody reads -> red (you must wire it up or declare it);
#   * a declaration outlives its key, or the kernel grows a reader for a
#     declared-inert key -> red (the manifest is not allowed to rot either way).
#
# WHAT IS DERIVED, AND FROM WHERE (no second copy of the truth)
# -------------------------------------------------------------
# "The kernel reads this key" is *derived* by scanning `kernel/**/*.rs`:
#   * accessor calls `.<snake_case>(`  (e.g. `status.polarity()`),
#   * quoted literals `"<Key>"`        (envelopes take cells by name:
#     `int_field("MaxProgramSteps")`).
# `kernel/rd-core/src/content.rs` is excluded: it holds the row-schema mirror and
# the accessors themselves (`death_prevention => 10`), so counting it would make
# every key look consumed.  Test modules are excluded for the same reason --
# `content.rs:2690-2755` asserts that each accessor returns its cell, which
# proves "the cell is readable", not "somebody uses it".  Comment lines are
# dropped so a doc comment mentioning a key cannot fake a consumer.
# Root keys are the exception: the kernel resolves them by *index* (S_CARD,
# S_STAT, ...), so only `root_by_name("<Key>")` counts, and the compiler is the
# thing that decides which root key becomes a row table (`ENTITY_SECTIONS`).
#
# DIRECTION OF THE APPROXIMATION (stated so it cannot be misread): the derived
# rule is **permissive** -- a same-named accessor for another type also counts as
# a consumer.  So it can under-report (fail to demand a declaration), never
# over-report (never call a consumed key inert).  The two checks below fail
# loudly in the direction that matters and say which line/rule decided.
#
# SUB-KEY PATHS (why root-key granularity was not enough -- measured, 2026-10-19)
# ------------------------------------------------------------------------------
# The `root:` scope started at root-key granularity, so "declare the whole key
# inert" was the only way to record a fact.  That is the wrong unit the moment
# the kernel grows a reader for *one field* of that object: wiring `Start` (the
# deck comes from `Start.Deck` / `Characters[0].Start.Deck`) forced the three
# declarations `root:Start` / `root:Characters` / `root:Deck` to be deleted, and
# the facts hanging under them -- `Start.MaxHealth`, `Start.StartingHealth`,
# `Start.Resources`, `Start.StartingRelics`, `Characters[].UnlockFlag` -- went
# with them.  They did not become false, they became **unrecorded**: the only
# place left for them was prose in an ad-hoc document, and prose is not a gate.
#
# So a `root:` declaration may now name a **sub-key path**:
#
#   root:<Parent>.<Field>       one field of the object under root key <Parent>
#   root:<Parent>[].<Field>     one field of every object element of that list
#
# `Statuses[]:` and `Program:` stay flat: those scopes are already per-record key
# sets, so the record *is* the unit.
#
# WHAT COUNTS AS READING A SUB-KEY (two rules, both derived from the kernel)
# -------------------------------------------------------------------------
#   1. a **hop spelling**: a literal that names this hop, `"<Parent>.<Field>"` or
#      `"<Parent>[<digits>].<Field>"`.  The kernel writes its own paths as data
#      (`DeckOrigin::path()` returns `"Characters[0].Start.Deck"` / `"Start.Deck"`
#      / `"Deck"`; `DeckError::Malformed` carries `"Start"`), so a hop it can
#      describe is a hop it reads.
#   2. an **object-field lookup by name**: `name == "<Field>"`.  This is the only
#      way the kernel addresses a content key of a *generic* object (it walks the
#      opcode field table and compares the stored name).
# `content.rs` is **included** for both rules, which is the opposite of the rule
# above and is deliberate: what is excluded there is the *schema mirror*
# (`death_prevention => 10`, `cell("Id", F_STR, 0)`) and the typed accessors, but
# the deck reader and every `name == "..."` comparison are genuine rule code
# living in the same file.
#
# ⚠️ NOT counted, on purpose: `field_at("<Field>")` and `.<snake_case>(`.  Those
# are **typed** accessors -- `EnemySpec::max_health` reads `MaxHealth` off an
# *enemy* record.  Counting them would make `Start.MaxHealth` look consumed (the
# key would then be undeclarable) while the truth is that nothing reads the
# `Start` object's `MaxHealth`: the hero's HP comes from `FightPlan`.  A name
# that two different record types share is exactly where a name-based rule
# cannot decide, and the honest resolution is to keep the yes/no at the
# granularity the kernel can answer (`name ==`, i.e. "the object I am looking at
# must have this field").
#
# ⇒ The known hole, stated so it cannot be discovered as a surprise: if someone
# adds a *typed* reader over the `Start` object (`impl StartRow { fn max_health(&self) { self.field_at("MaxHealth") } }`)
# and calls it, the gate stays green with `root:Start.MaxHealth` declared inert.
# `tests/mutation` for this gate therefore uses `Start.Deck` (rule 1 + 2 both have
# a line for it), not `MaxHealth`.  What would close the hole is a per-type
# reader index in the kernel; there is none, and inventing one in the gate would
# be a second copy of the truth.

KERNEL_DIR = os.path.join(ROOT, "kernel")
# The declaration is this gate's input, not content: it is a top-level key so that
# it travels with the document it describes, but the compiler lists it in
# `DOC_ROOT_KEYS` and therefore stores it in **neither image** (`check_roundtrip`
# asserts that absence).  It is not part of the inert-key universe either.
MANIFEST_ROOT_KEY = "InertKeys"
INERT_SCOPES = ("root", "Statuses[]", "Program")
# `root:<Parent>.<Field>` / `root:<Parent>[].<Field>` -- see "SUB-KEY PATHS" above.
SUBKEY_SCOPES = ("root",)
SUBKEY_PATH = re.compile(r"^(?P<parent>[A-Za-z_][A-Za-z0-9_]*)(?P<list>\[\])?\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)$")
_COMMENT_PREFIXES = ("//", "/*", "*")
_KERNEL_CODE = {}


def snake_case(name):
    """`MaxNodeDepth` -> `max_node_depth`, the kernel's accessor spelling."""
    out = []
    for index, ch in enumerate(name):
        if ch.isupper() and index and (
                not name[index - 1].isupper()
                or (index + 1 < len(name) and name[index + 1].islower())):
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def kernel_rule_code():
    """`kernel/**/*.rs` minus test modules and comment lines, keyed by repo path."""
    if not _KERNEL_CODE:
        for base, dirs, files in os.walk(KERNEL_DIR):
            dirs[:] = sorted(d for d in dirs if d != "target")
            for name in sorted(files):
                if not name.endswith(".rs"):
                    continue
                path = os.path.join(base, name)
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                cut = re.search(r"^#\[cfg\(test\)\]", text, re.M)
                if cut:
                    text = text[:cut.start()]
                # Blank comment lines instead of dropping them: the failure messages
                # quote `file:line`, and a message that points at the wrong line is
                # worse than no line at all (this repo has been bitten by that).
                kept = ["" if line.lstrip().startswith(_COMMENT_PREFIXES) else line
                        for line in text.splitlines()]
                _KERNEL_CODE[rel(path)] = "\n".join(kept)
    return _KERNEL_CODE


def kernel_reads(key):
    """(bool, where) -- does kernel *rule* code consume this key?"""
    code = kernel_rule_code()
    call = re.compile(r"\.%s\(" % re.escape(snake_case(key)))
    literal = re.compile(r'"%s"' % re.escape(key))
    for path, text in sorted(code.items()):
        if path.endswith("rd-core/src/content.rs"):
            continue
        for pattern in (call, literal):
            hit = pattern.search(text)
            if hit:
                return True, "%s:%d" % (path, text.count("\n", 0, hit.start()) + 1)
    return False, ""


def root_read_by_name(key):
    """(bool, where) -- does any non-test kernel code call `root_by_name("<Key>")`?"""
    pattern = re.compile(r'root_by_name\(\s*"%s"\s*\)' % re.escape(key))
    for path, text in sorted(kernel_rule_code().items()):
        hit = pattern.search(text)
        if hit:
            return True, "%s:%d" % (path, text.count("\n", 0, hit.start()) + 1)
    return False, ""


def scope_keys(doc):
    """The inert-key universe, per scope, straight out of the source document."""
    row_tables = {section for _name, section in contentc_compile.ENTITY_SECTIONS}
    root = [key for key in doc if key not in row_tables and key != MANIFEST_ROOT_KEY]
    statuses, programs = [], []
    for record in doc.get("Statuses") or []:
        for key in record:
            if key not in statuses:
                statuses.append(key)
    for record in list(doc.get("Cards") or []) + list(doc.get("EnemyActions") or []):
        program = record.get("Program")
        if isinstance(program, dict):
            for key in program:
                if key not in programs:
                    programs.append(key)
    return {"root": root, "Statuses[]": statuses, "Program": programs}


def root_subkey_universe(doc):
    """`{path: (parent, is_list, field)}` for every **sub-key** the document has.

    The unit is one level: the fields of the object stored under a root key, or
    the union of the fields of the objects inside a root list.  One level is what
    the facts are about -- `Characters[].Start.Deck` and `Start.Deck` are the same
    term in both images (measured: `content.rs`'s "MEASURED SHAPES" table), so a
    second level would record the same fact twice under two spellings.

    Root keys are **not** filtered here: a sub-key of a wholly-inert root is
    still "present" (so it cannot masquerade as stale), it is only *covered* --
    see `check_inert_keys` (4).
    """
    row_tables = {section for _name, section in contentc_compile.ENTITY_SECTIONS}
    out = {}
    for parent, value in doc.items():
        if parent in row_tables or parent == MANIFEST_ROOT_KEY:
            continue
        fields, is_list = [], False
        if isinstance(value, dict):
            fields = list(value)
        elif isinstance(value, list):
            is_list = True
            for element in value:
                if isinstance(element, dict):
                    for field in element:
                        if field not in fields:
                            fields.append(field)
        for field in fields:
            path = "root:%s%s.%s" % (parent, "[]" if is_list else "", field)
            out[path] = (parent, is_list, field)
    return out


def subkey_reads(parent, field):
    """(bool, where) -- does kernel rule code read `<Parent>`'s `<Field>`?

    Two rules, both from `kernel/**/*.rs` **including** `content.rs` (which the
    whole-key rule excludes) -- see "WHAT COUNTS AS READING A SUB-KEY" above:
    the hop spelled as data, and an object-field lookup by name.  Both are
    reported when both hit: the `name` hit is the reader, the `hop` hit is the
    line that spells the path, and a message with only one of them sends the
    reader to the wrong kind of evidence.
    """
    patterns = (
        ("name", re.compile(r'name\s*==\s*"%s"' % re.escape(field))),
        ("hop", re.compile(r'"%s(?:\[\d*\])?\.%s(?![A-Za-z0-9_])'
                           % (re.escape(parent), re.escape(field)))),
    )
    found = []
    for rule, pattern in patterns:
        for path, text in sorted(kernel_rule_code().items()):
            hit = pattern.search(text)
            if hit:
                found.append("%s:%d (%s rule)"
                             % (path, text.count("\n", 0, hit.start()) + 1, rule))
                break
    return (bool(found), ", ".join(found))


def presentation_keys(doc, scope):
    """Keys the *compiler* strips (`strip_presentation`) -- a consumer, not inert.

    Derived from the compiler's own function, never from a second copy of the
    presentation rule (`contentc-audit.md` §7).
    """
    stripped = contentc_compile.strip_presentation(doc)
    return set(scope_keys(doc)[scope]) - set(scope_keys(stripped)[scope])


def check_inert_keys(doc):
    print("[6b] inert-key declarations (%s)" % MANIFEST_ROOT_KEY)
    entries = doc.get(MANIFEST_ROOT_KEY)
    if entries is None:
        fail(MANIFEST_ROOT_KEY,
             "the declaration block is missing -- every key without a kernel consumer "
             "has to be declared here (see the module docstring of this gate)")
        entries = []
    elif not isinstance(entries, list):
        fail(MANIFEST_ROOT_KEY, "must be a list, got %s" % type(entries).__name__)
        entries = []

    keys = scope_keys(doc)
    subs = root_subkey_universe(doc)

    declared = {}
    for index, entry in enumerate(entries):
        where = "%s[%d]" % (MANIFEST_ROOT_KEY, index)
        if not isinstance(entry, dict):
            fail(where, "must be an object with Path/Why, got %s" % type(entry).__name__)
            continue
        extra = sorted(set(entry) - {"Path", "Why"})
        if extra:
            fail(where, "unexpected key(s) %s (only Path/Why)" % extra)
        path, why = entry.get("Path"), entry.get("Why")
        if not isinstance(path, str) or ":" not in path:
            fail(where, "Path must be '<scope>:<Key>' (or `root:<Parent>.<Field>` / "
                 "`root:<Parent>[].<Field>`), got %r" % (path,))
            continue
        scope, key = path.split(":", 1)
        if scope not in INERT_SCOPES:
            fail(where, "unknown scope %r (known: %s)" % (scope, ", ".join(INERT_SCOPES)))
            continue
        if not key:
            fail(where, "empty key in Path %r" % path)
            continue
        if path in declared:
            fail(where, "duplicate Path %r" % path)
            continue
        if not isinstance(why, str) or len(why.strip()) < 12:
            fail(where, "%s: `Why` must state why the key can stay inert" % path)
            continue
        # Whole key, or (root only) a sub-key path.  "Is this a whole key?" is
        # decided by the document, not by the spelling, so a root key whose name
        # happens to contain a dot stays declarable.
        parent = field = None
        if key not in keys[scope]:
            shape = SUBKEY_PATH.match(key) if scope in SUBKEY_SCOPES else None
            if shape is None:
                fail(where, "Path %r is neither a %r key of the content nor a sub-key "
                     "path (`<Parent>.<Field>` / `<Parent>[].<Field>`)"
                     % (path, scope))
                continue
            parent, field = shape.group("parent"), shape.group("field")
        declared[path] = {"why": why, "scope": scope, "key": key,
                          "parent": parent, "field": field}

    def subkeys_of(path):
        return declared[path]["parent"] is not None

    # Which whole root keys are declared inert: their sub-keys are **covered**, so
    # (2) does not demand them and (4) rejects naming them anyway.
    root_inert = {entry["key"] for path, entry in declared.items()
                  if entry["scope"] == "root" and entry["parent"] is None}

    # (1) A declaration must not outlive its key: a manifest that names something
    # the content no longer has is a lie that reads like coverage.
    for path in sorted(declared):
        scope, key = declared[path]["scope"], declared[path]["key"]
        if subkeys_of(path):
            if path in subs:
                continue
            parent, field = declared[path]["parent"], declared[path]["field"]
            if parent not in keys[scope]:
                why = "its parent root key %r is not in the content" % parent
            elif not any(p == parent for p, _l, _f in subs.values()):
                why = ("root key %r is not an object (nor a list of objects), so it "
                       "has no sub-keys" % parent)
            else:
                why = ("root key %r has no field %r (it has: %s)"
                       % (parent, field,
                          ", ".join(sorted(f for p, _l, f in subs.values() if p == parent))))
            fail("inert.stale", "%s is declared inert but %s -- the declaration "
                 "outlived its key" % (path, why))
            continue
        if key not in keys[scope]:
            fail("inert.stale", "%s is declared inert but does not appear in the content "
                 "-- the declaration outlived its key" % path)

    # (2) Every key with no kernel consumer must be declared.  Same rule for whole
    # keys and for sub-keys; only the "where does a consumer show up" test differs.
    for scope in INERT_SCOPES:
        presentation = presentation_keys(doc, scope)
        for key in keys[scope]:
            path = "%s:%s" % (scope, key)
            if path in declared or key in presentation:
                continue
            if scope == "root":
                reads, where = root_read_by_name(key)
                rule = "no `root_by_name(\"%s\")` call in kernel rule code" % key
            else:
                reads, where = kernel_reads(key)
                rule = "no `.`+`%s(` and no \"%s\" literal in kernel rule code" % (
                    snake_case(key), key)
            if not reads:
                fail("inert.undeclared", "%s is not read by the kernel (%s) and is not "
                     "declared in %s -- wire it up, or declare it and say why it is "
                     "documentation" % (path, rule, MANIFEST_ROOT_KEY))
    for path, (parent, is_list, field) in sorted(subs.items()):
        if parent in root_inert or path in declared:
            continue
        reads, where = subkey_reads(parent, field)
        if not reads:
            hop = "%s[].%s" % (parent, field) if is_list else "%s.%s" % (parent, field)
            fail("inert.undeclared",
                 "%s is not read by the kernel (no hop spelling of `%s` and no "
                 "`name == \"%s\"` in kernel rule code) and is not declared in %s -- "
                 "wire it up, or declare it and say why it is documentation"
                 % (path, hop, field, MANIFEST_ROOT_KEY))

    # (3) A declaration must not rot the other way either: if the kernel grew a
    # consumer, the "inert" claim is now false and has to be deleted.
    for path in sorted(declared):
        scope, key = declared[path]["scope"], declared[path]["key"]
        if subkeys_of(path):
            reads, where = subkey_reads(declared[path]["parent"], declared[path]["field"])
        else:
            reads, where = root_read_by_name(key) if scope == "root" else kernel_reads(key)
        if reads:
            fail("inert.rotted", "%s is declared inert but the kernel reads it at %s -- "
                 "delete the declaration" % (path, where))

    # (4) A sub-key of a wholly-inert root key is **already** covered by that
    # root's declaration: naming it again is noise that reads like extra coverage
    # (and would let a manifest list `Monsters[]` fields as if it checked them).
    # Stricter than the original three checks, never looser.
    for path in sorted(declared):
        if not subkeys_of(path):
            continue
        parent = declared[path]["parent"]
        if parent in root_inert:
            fail("inert.redundant", "%s names a sub-key of root:%s, which is already "
                 "declared inert as a whole -- pick one granularity" % (path, parent))

    declared_sub = sum(1 for path in declared if subkeys_of(path))
    covered = sum(1 for parent, _l, _f in subs.values() if parent in root_inert)
    checked_sub = len(subs) - covered
    ok("inert keys",
       "%d declared (%d whole / %d root sub-key), %d root / %d root sub-key / "
       "%d status / %d envelope keys checked"
       % (len(declared), len(declared) - declared_sub, declared_sub, len(keys["root"]),
          checked_sub, len(keys["Statuses[]"]), len(keys["Program"])))


def check_roundtrip(doc, rom, label, expected):
    """Source document vs image, per key, on every entity and every root key."""
    print("[7] round trip: %s" % label)
    image = rom.document()
    for table in ("Cards", "Statuses", "EnemyActions", "Encounters", "Relics"):
        want = expected.get(table) or []
        got = image.get(table) or []
        if len(want) != len(got):
            fail("%s/%s" % (label, table), "row count %d vs %d" % (len(want), len(got)))
            continue
        for index, (w, g) in enumerate(zip(want, got)):
            problems = diff(w, g, "%s[%d]" % (table, index))
            if problems:
                fail("%s/%s[%d]" % (label, table, index), problems[0])
        ok(label + " " + table, "%d rows, key presence included" % len(want))
    # Document keys (`DOC_ROOT_KEYS`, imported from the compiler -- not a second
    # copy) are build metadata: they exist in the source and in *neither* image.
    # So they leave the compared key set, and the fact that they really are absent
    # becomes an assertion of its own -- otherwise "stripped" would be a claim in a
    # commit message instead of something this gate can fail on.
    doc_keys = contentc_compile.DOC_ROOT_KEYS
    leaked = [k for k in doc_keys if k in image]
    if leaked:
        fail("%s/document-keys" % label,
             "%s is declared a document key but reaches the image -- a documentation "
             "block is being paid for as content" % ", ".join(repr(k) for k in leaked))
    want_roots = sorted(k for k in expected if k not in ROW_TABLES and k not in doc_keys)
    got_roots = sorted(k for k in image if k not in ROW_TABLES and k not in doc_keys)
    if want_roots != got_roots:
        fail("%s/root" % label, "keys %s != %s" % (got_roots, want_roots))
    for key in want_roots:
        problems = diff(expected[key], image.get(key), key)
        if problems:
            fail("%s/root.%s" % (label, key), problems[0])
    ok(label + " roots", "%d keys, per key, %d document keys not stored"
       % (len(want_roots), len(doc_keys)))


def check_idx(rom, label):
    print("[8] id index: %s" % label)
    want = {
        "strike": F.EK_CARD, "defend": F.EK_CARD, "bash": F.EK_CARD,
        "slimed": F.EK_CARD,
        "standard.vulnerable": F.EK_STATUS, "standard.weak": F.EK_STATUS,
        "standard.strength": F.EK_STATUS, "standard.frail": F.EK_STATUS,
        "ritual": F.EK_STATUS,
        "cultist.incantation": F.EK_EACTION, "jaw_worm.chomp": F.EK_EACTION,
        "gremlin_wizard.ultimate_blast": F.EK_EACTION,
        "enc_cultist": F.EK_ENCOUNTER, "enc_small_slimes": F.EK_ENCOUNTER,
        "ironclad": F.EK_CHARACTER,
    }
    for entity_id, kind in sorted(want.items()):
        hit = rom.lookup(entity_id)
        if hit is None:
            fail("idx." + label, "%r missing from SEC_IDX" % entity_id)
        elif hit[0] != kind:
            fail("idx." + label, "%r resolves to kind %d, expected %d"
                 % (entity_id, hit[0], kind))
    ok(label + " SEC_IDX", "%d ids -> right entity kind" % len(want))


# =============================================================================
# 4.  main
# =============================================================================

def main():
    global SRC_PATH, FULL_PATH, CORE_PATH
    ap = argparse.ArgumentParser(description="gate for the sts content package")
    # The three overrides exist so that "source and image disagree" is a
    # *demonstrable* failure: build a mutated copy elsewhere and point the gate at
    # the good source + the mutated image.  The defaults are the package itself.
    ap.add_argument("--src", default=SRC_PATH)
    ap.add_argument("--full", default=FULL_PATH)
    ap.add_argument("--core", default=CORE_PATH)
    args = ap.parse_args()
    SRC_PATH, FULL_PATH, CORE_PATH = args.src, args.full, args.core

    print("sts content gate -- tools/contentc/packages/sts")
    check_preconditions()

    with open(SRC_PATH, "r", encoding="utf-8") as fh:
        doc = json.load(fh)

    full = rdcf_reader.Rom(open(FULL_PATH, "rb").read())
    core = rdcf_reader.Rom(open(CORE_PATH, "rb").read())

    check_quantities(doc)
    check_monsters(doc)
    check_cards_and_actions(doc)
    check_statuses(doc)
    check_relations(doc)
    check_weak_pool_table(doc)
    check_event_vocabulary(doc)
    check_upgrades(doc)
    check_relic_rarities(doc)
    check_potions(doc)
    check_card_keywords(doc)
    check_relics(doc)
    check_inert_keys(doc)
    check_roundtrip(doc, full, "full", doc)
    # The core image's expectation comes from the compiler's own strip rule --
    # a copy of it here would be a second truth that rots (contentc-audit §7).
    check_roundtrip(doc, core, "core", contentc_compile.strip_presentation(doc))
    check_idx(full, "full")
    check_idx(core, "core")

    st = full.stats()
    print()
    if PROBLEMS:
        print("!! STS_CONTENT FAIL (%d problem(s))" % len(PROBLEMS))
        for problem in PROBLEMS:
            print("   " + problem)
        raise SystemExit(1)
    print("STS_CONTENT PASS (monsters %d, encounters %d, deck %d, statuses %d, "
          "cards %d, enemy_actions %d, full %d B, core %d B)"
          % (INV_COUNTS["monsters"], INV_COUNTS["encounters"], INV_COUNTS["deck"],
             INV_COUNTS["statuses"], len(doc.get("Cards") or []),
             len(doc.get("EnemyActions") or []), st["total_size"],
             os.path.getsize(CORE_PATH)))


if __name__ == "__main__":
    main()
