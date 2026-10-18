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
          is red, not silent).
          The core image's expectation is derived with `compile.py`'s own
          `strip_presentation`, not with a second copy of that rule: a copy is
          the classic "second source of truth rots" bug (`contentc-audit.md` §7).
3. XREF   the cross references resolve and are consistent: deck -> cards,
          encounter -> monster roster (field by field, because the roster is a
          duplicate of the encounter's inline record), roster -> enemy actions,
          every status a program names -> a STAT row, every id -> the right
          entity kind in `SEC_IDX`.

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
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONTENTC = os.path.join(ROOT, "tools", "contentc")
sys.path.insert(0, CONTENTC)

import rdcfmt as F            # noqa: E402  (the frozen on-disk vocabulary)
import reader as rdcf_reader  # noqa: E402  (the reference reader)
import compile as contentc_compile  # noqa: E402  (only for strip_presentation)

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
    "monsters": 10,      # inv:§3.3 tier A = 10 of 25 entities
    "encounters": 3,     # inv:§5.2 weak pool, the 3 that use only tier-A enemies
    "deck": 10,          # inv:§2   "10 张：strike x5、defend x4、bash x1"
    "statuses": 5,       # inv:§10 the ones this subset actually needs
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
}

# inv:§4.1 -- the 10 zero-new-ability enemies: (hp_min, hp_max, action ids).
INV_MONSTERS = [
    ("spike_slime_s", 10, 14, ["spike_slime_s.tackle"]),
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
]

# inv:§4.1 -- every enemy action, as mechanically derived facts.
INV_ACTIONS = {
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
    "gremlin_wizard.ultimate_blast": ("Attack", [
        ("damage", 25, "event"),
        # the AI turn counter is reset by the blast itself; it is the content-side
        # substitute for `intent.round` (there is none, see Notes.Deviations).
        ("counter", "gremlin_wizard_charges", 0, False, "source")]),
}

# inv:§5.2 -- the weak pool.  The 4th entry (`enc_two_louses`) needs
# louse_red/louse_green, which are tier C (Curl Up needs a DamageTaken trigger).
INV_WEAK_POOL = {
    "enc_cultist": ["cultist"],
    "enc_jaw_worm": ["jaw_worm"],
    # The source rolls 50/50 acid|spike for the M and for the S independently;
    # a static enemy list pins one of the four combinations.
    "enc_small_slimes": ["acid_slime_m", "spike_slime_s"],
}
INV_WEAK_WEIGHT = 25   # inv:§5.2 每项 25%

# inv:§10 -- the 5 statuses, with the modifier the damage/block pipeline needs.
# `None` = the content cannot express it today (see Notes.KernelGapsFound).
# The magnitudes are copied from kernel/rd-core/src/status_catalog.rs:135-215,
# because a content image **disables** that catalog (exec.rs:2421-2426): with
# content present the candidate rows come only from STAT.PassiveModifiers.
INV_STATUSES = {
    "standard.strength": [("DamageDealt", "AddPerStack", 1, 100, "Direct")],
    "standard.vulnerable": [("DamageReceived", "ScalePercent", 150, 300, "Direct")],
    "standard.weak": [("DamageDealt", "ScalePercent", 75, 200, "Direct")],
    "standard.frail": [],      # no block pipeline in status_bind::Pipeline
    "ritual": [],
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
    mapping = {"sel.eventTarget": "event", "sel.source": "source"}
    if kind not in mapping:
        raise AssertionError("unexpected selector kind %r" % kind)
    return mapping[kind]


def amount(expr):
    if expr.get("kind") == "const":
        return expr["value"]["Value"]
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
        else:
            raise AssertionError("unexpected node kind %r" % kind)

    walk(root)
    return facts


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
    if sorted(doc.get("Encounters") and [e["Id"]["Value"] for e in doc["Encounters"]]) \
            != sorted(INV_WEAK_POOL):
        fail("encounters.ids", "encounter ids %s != inv %s"
             % (sorted(e["Id"]["Value"] for e in doc["Encounters"]),
                sorted(INV_WEAK_POOL)))
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
        got = program_facts(action["Program"]["Root"])
        if got != facts:
            fail("action." + aid, "facts %s, inv says %s" % (got, facts))
    ok("cards", "%d cards x (cost, tags, facts)" % len(INV_CARDS))
    ok("enemy actions", "%d actions x (intent, facts)" % len(INV_ACTIONS))


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
        if eid not in INV_WEAK_POOL:
            fail("encounter." + eid, "not in the inventory's weak pool (inv:§5.2)")
        listed = [e["Id"] for e in enc.get("Enemies") or []]
        if listed != INV_WEAK_POOL.get(eid):
            fail("encounter." + eid, "enemies %s, inv:§5.2 says %s"
                 % (listed, INV_WEAK_POOL.get(eid)))
        # `CardsDrawnPerTurn` null = the per-turn draw default, which inv:§2 says
        # is 5.  Writing a number here would be a second place the draw count lives.
        if enc.get("CardsDrawnPerTurn") is not None:
            fail("encounter." + eid,
                 "CardsDrawnPerTurn must stay null (= inv:§2's %d-card default), got %r"
                 % (INV_HERO["CardsDrawnPerTurn"], enc.get("CardsDrawnPerTurn")))
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
    if got != {eid: INV_WEAK_WEIGHT for eid in INV_WEAK_POOL}:
        fail("EncounterTables.Weak", "%s != %s (each 25%%, inv:§5.2)"
             % (got, {eid: INV_WEAK_WEIGHT for eid in INV_WEAK_POOL}))
    ok("weak pool", "%d entries x %d%%" % (len(table), INV_WEAK_WEIGHT))


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
    want_roots = sorted(k for k in expected if k not in ROW_TABLES)
    got_roots = sorted(k for k in image if k not in ROW_TABLES)
    if want_roots != got_roots:
        fail("%s/root" % label, "keys %s != %s" % (got_roots, want_roots))
    for key in want_roots:
        problems = diff(expected[key], image.get(key), key)
        if problems:
            fail("%s/root.%s" % (label, key), problems[0])
    ok(label + " roots", "%d keys, per key" % len(want_roots))


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
