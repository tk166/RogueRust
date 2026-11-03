"""§190: fill in the ascension numbers for every move whose **base** already matches the wiki.

13 variants -> 41. The rule from §187 still holds: mutate the base program, never author a node, and
fail loudly if the constant to change is not there.

Where the wiki gives two thresholds for one move (Jaw Worm's Bellow raises Strength at A2 **and**
Block at A17), the schema's single `ProgramAsc` can only carry one; the earlier one wins and the
comment says so. A second slot is a format change, not a data change -- written down in §190.4.

Moves whose base does **not** match the wiki are deliberately left alone: an ascension variant is a
delta on a base, and a delta on a wrong base is a lie. They are listed in `docs/sts-wiki-gap.md` §2.G
so the next pass fixes the base first.
"""
import copy
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"


def walk(node, visit):
    visit(node)
    if isinstance(node, dict):
        for value in node.values():
            walk(value, visit)
    elif isinstance(node, list):
        for value in node:
            walk(value, visit)


def nodes(root, kind):
    found = []
    walk(root, lambda n: found.append(n) if isinstance(n, dict) and n.get("kind") == kind else None)
    return found


def damage(root, before, after):
    """Every `node.dealDamage` whose const amount is `before` becomes `after` (multi-hit safe: each
    hit is its own node, so all of them are rewritten -- which is what `5×2 -> 6×2` means)."""
    hits = 0
    for node in nodes(root, "node.dealDamage"):
        amount = node["value"].get("Amount") or {}
        if amount.get("kind") == "const" and amount["value"]["Value"] == before:
            amount["value"]["Value"] = after
            hits += 1
    assert hits > 0, "no dealDamage with amount %d" % before
    return None


def status(root, status_id, before, after):
    hits = 0
    for node in nodes(root, "node.applyStatus"):
        if node["value"]["StatusDefinitionId"]["value"] != status_id:
            continue
        stacks = node["value"].get("Stacks") or {}
        if stacks.get("kind") == "const" and stacks["value"]["Value"] == before:
            stacks["value"]["Value"] = after
            hits += 1
    assert hits > 0, "no %s at %d stacks" % (status_id, before)
    return None


def cards(root, card_id, before, after):
    hits = 0
    for node in nodes(root, "node.createCardInstance"):
        if node["value"]["CardDefinitionId"]["value"] != card_id:
            continue
        count = node["value"].get("Count") or {}
        if count.get("kind") == "const" and count["value"]["Value"] == before:
            count["value"]["Value"] = after
            hits += 1
    assert hits > 0, "no %s x%d" % (card_id, before)
    return None


def one_more_hit(root):
    """`1x5 -> 1x6` (Byrd's Peck at A2).

    The content writes a *fixed-count* multi-hit **unrolled** -- five separate `dealDamage` nodes,
    not a `repeat` -- so the ascension variant grows the sequence instead of changing a number. That
    is the shape the content chose; inventing a `repeat` here would make the two halves of the same
    move look different to every reader.
    """
    children = root["value"]["Children"]
    assert children and all(c["kind"] == "node.dealDamage" for c in children), "not an unrolled multi-hit"
    assert len(children) == 5, len(children)
    children.append(copy.deepcopy(children[-1]))
    return None


# (action id, AscensionMin, mutation)  -- numbers from native/wiki_asc/<monster>.txt
PLAN = [
    # --- Act 1 normal (damage tier 2) -----------------------------------------------------
    ("cultist.incantation", 2, lambda r: status(r, "ritual", 3, 4)),
    ("jaw_worm.chomp", 2, lambda r: damage(r, 11, 12)),
    # Bellow raises Strength at A2 **and** Block at A17; the one variant slot carries the earlier one.
    ("jaw_worm.bellow", 2, lambda r: status(r, "standard.strength", 3, 4)),
    ("acid_slime_m.corrosive_spit", 2, lambda r: damage(r, 7, 8)),
    ("acid_slime_m.tackle", 2, lambda r: damage(r, 10, 12)),
    ("acid_slime_s.tackle", 2, lambda r: damage(r, 3, 4)),
    ("spike_slime_s.tackle", 2, lambda r: damage(r, 5, 6)),
    ("spike_slime_m.flame_tackle", 2, lambda r: damage(r, 8, 10)),
    ("fungi_beast.grow", 2, lambda r: status(r, "standard.strength", 3, 4)),
    ("byrd.peck", 2, one_more_hit),
    ("byrd.swoop", 2, lambda r: damage(r, 12, 14)),
    ("chosen.debilitate", 2, lambda r: damage(r, 10, 12)),
    ("orb_walker.laser", 2, lambda r: damage(r, 10, 11)),
    ("orb_walker.claw", 2, lambda r: damage(r, 15, 16)),
    ("fat_gremlin.smash", 2, lambda r: damage(r, 4, 5)),
    ("sneaky_gremlin.puncture", 2, lambda r: damage(r, 9, 10)),
    ("gremlin_wizard.ultimate_blast", 2, lambda r: damage(r, 25, 30)),
    ("shelled_parasite.double_strike", 2, lambda r: damage(r, 6, 7)),
    ("shelled_parasite.suck", 2, lambda r: damage(r, 10, 12)),
    ("spire_growth.aggressive", 2, lambda r: damage(r, 16, 18)),
    ("spire_growth.aggressive_heavy", 2, lambda r: damage(r, 22, 25)),
    # --- move-set tier 17 (normal enemies) ------------------------------------------------
    ("louse_red.grow", 17, lambda r: status(r, "standard.strength", 3, 4)),
    ("louse_green.grow", 17, lambda r: status(r, "standard.strength", 3, 4)),
    # --- Act 1/2 elite (damage tier 3, move-set 18) ---------------------------------------
    ("gremlin_nob.skull_bash", 3, lambda r: damage(r, 6, 8)),
    ("gremlin_nob.rush", 3, lambda r: damage(r, 14, 16)),
    ("gremlin_nob.bellow", 18, lambda r: status(r, "standard.strength", 2, 3)),
    ("sentry.beam", 3, lambda r: damage(r, 9, 10)),
    # --- boss tier 4 / move-set 19 --------------------------------------------------------
    ("slime_boss.slam", 4, lambda r: damage(r, 35, 38)),
    ("slime_boss.goop_spray", 19, lambda r: cards(r, "slimed", 3, 5)),
]


def main():
    document = json.load(io.open(SRC, encoding="utf-8"))
    actions = {action["Id"]: action for action in document["EnemyActions"]}
    touched = 0
    for action_id, threshold, mutate in PLAN:
        action = actions[action_id]
        assert "ProgramAsc" not in action, "already has a variant: " + action_id
        root = copy.deepcopy(action["Program"]["Root"])
        mutate(root)
        envelope = copy.deepcopy(action["Program"])
        envelope["Root"] = root
        action["ProgramAsc"] = envelope
        action["AscensionMin"] = threshold
        touched += 1
        print("%-32s A%-2d" % (action_id, threshold))
    assert touched == len(PLAN), (touched, len(PLAN))
    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("wired", touched, "more variants")


if __name__ == "__main__":
    main()
