"""§154: pin the ten new `+` rows in the content inventory (`native/sts_content_check.py`).

The inventory is the gate's second opinion on every card row: cost, tags and the effect facts read
out of the program. Adding rows to the content without adding them here makes the id-set check fail
-- which is the point (a new card must be declared, not slip in).

Deltas are the wiki's (see `patch_154_upgrades.py`); the facts are what the program actually does.
"""

import io

PATH = r"D:\Vibe\sts-tui\native\sts_content_check.py"

NEW_ROWS = '''
    # §154: the ten `+` rows that were missing. The run upgrades by appending `+` to the card id, so
    # a card without one becomes an id the image does not contain -- and the next fight refuses to
    # build (`UnknownCard(CardDefinitionId("iron_wave+"))`, reported from the browser).
    "anger+": {"Cost": 0, "Tags": ["attack"],
               "Facts": [("damage", 8, "event"), ("card", "anger+", 1)]},
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
'''

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

if '"anger+"' in source:
    print("rows already present")
else:
    anchor = '    "whirlwind+": {"Cost": 0'
    at = source.find(anchor)
    if at < 0:
        raise SystemExit("whirlwind+ anchor missing")
    source = source[:at] + NEW_ROWS.lstrip("\n") + source[at:]
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("ten + rows pinned")

# Card count message + the "every upgradable card has a +" rule.
if "def check_upgrades(doc):" not in source:
    with io.open(PATH, encoding="utf-8") as handle:
        source = handle.read()
    RULE = '''

# The tags a card can carry and still be upgraded at a campfire. Curses and statuses cannot.
NOT_UPGRADABLE_TAGS = ("curse", "status")


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
'''
    anchor = "def check_potions(doc):"
    at = source.find(anchor)
    if at < 0:
        raise SystemExit("check_potions anchor missing")
    source = source[:at] + RULE.strip("\n") + "\n\n\n" + source[at:]
    source = source.replace("    check_potions(doc)", "    check_upgrades(doc)\n    check_potions(doc)", 1)
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("check_upgrades added")
