"""§191: fix the **bases** of the 11 moves §190 flagged, then give them their ascension numbers.

§190 deliberately refused to add ascension variants on top of wrong bases. This is the other half:

| move | our base | wiki base | fix |
|---|---|---|---|
| `spiker.cut` | 8 | 7 (A2: 9) | 8 -> 7, then A2 variant |
| `the_champ.heavy_slash` | 18 | 16 (A4: 18) | 18 -> 16, then A4 variant |
| `the_champ.execute` | one 30 | 10x2 | restructure to two hits of 10 (no asc value) |
| `chosen.poke` | 6+6 | 5x2 (A2: 6x2) | 6 -> 5, then A2 variant |
| `gremlin_leader.slash` | one 16 | 6x3 | restructure to three hits of 6 (no asc value) |
| `darkling.chomp` | one 11 | 8x2 (A2: 9x2) | restructure to two hits of 8, then A2 variant |
| `sentry.bolt` | 10 damage | adds 2 Dazed (A18: 3) | needs the `dazed` card; then A18 variant |
| `spire_growth.strategic` | Constricted 2 | 10 (A2: 12) | 2 -> 10, then A2 variant |

**Not fixed here on purpose:** `giant_head.*` (a documented 320-HP simplification since §130) and
`maw.*` (the wiki has no such page). Both stay in `docs/sts-wiki-gap.md` §G as known deviations.

`dazed` is a new status card (Unplayable, Ethereal, no effect) -- the third "junk" card next to
`slimed` and `wound`, and the one Sentry's Bolt actually uses.
"""
import copy
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"


def nodes(root, kind):
    out = []
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("kind") == kind:
                out.append(node)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


def set_const_damage(root, before, after):
    hits = 0
    for node in nodes(root, "node.dealDamage"):
        amount = node["value"].get("Amount") or {}
        if amount.get("kind") == "const" and amount["value"]["Value"] == before:
            amount["value"]["Value"] = after
            hits += 1
    assert hits == 1, "expected exactly one %d-damage hit, found %d" % (before, hits)


def rebuild(envelope, children):
    """Turn a one-node program into a sequence (the two restructures).

    `Program` is the **envelope** (`{Root, MaxProgramSteps, ...}`); the tree is `envelope["Root"]`.
    Getting that wrong is the §187 mistake in miniature -- it asserts on `envelope.get("kind")`,
    which is `None`.
    """
    assert "Root" in envelope, sorted(envelope)
    envelope["Root"] = {"kind": "node.sequence", "value": {"Children": children}}


def main():
    document = json.load(io.open(SRC, encoding="utf-8"))
    actions = {action["Id"]: action for action in document["EnemyActions"]}

    # ---------------------------------------------------------------- the junk card
    if not any(card["Id"] == "dazed" for card in document["Cards"]):
        template = next(card for card in document["Cards"] if card["Id"] == "slimed")
        row = copy.deepcopy(template)
        row.update({
            "Id": "dazed",
            "NameKey": "Dazed",
            "DescriptionKey": "Unplayable. Ethereal.",
            "Tags": [{"value": "status"}, {"value": "unplayable"}, {"value": "ethereal"}, {"value": "junk"}],
            "Rarity": "Status",
            "TurnEndHandDestinationZone": "ExhaustPile",
        })
        document["Cards"].append(row)
        print("card added: dazed")

    # ---------------------------------------------------------------- base fixes
    cut = actions["spiker.cut"]["Program"]["Root"]
    set_const_damage(cut, 8, 7)

    heavy = actions["the_champ.heavy_slash"]["Program"]["Root"]
    set_const_damage(heavy, 18, 16)

    poke = actions["chosen.poke"]["Program"]["Root"]
    for node in nodes(poke, "node.dealDamage"):
        amount = node["value"]["Amount"]
        assert amount["value"]["Value"] == 6
        amount["value"]["Value"] = 5

    strategic = actions["spire_growth.strategic"]["Program"]["Root"]
    applied = 0
    for node in nodes(strategic, "node.applyStatus"):
        if node["value"]["StatusDefinitionId"]["value"] != "standard.constricted":
            continue
        stacks = node["value"]["Stacks"]
        assert stacks["value"]["Value"] == 2, stacks
        stacks["value"]["Value"] = 10
        applied += 1
    assert applied == 1, applied

    # ---------------------------------------------------------------- restructures
    # `the_champ.execute`: one 30 -> two hits of 10 (`Deals 10x2 damage`).
    execute = actions["the_champ.execute"]["Program"]["Root"]
    assert execute["kind"] == "node.dealDamage"
    execute["value"]["Amount"]["value"]["Value"] = 10
    rebuild(actions["the_champ.execute"]["Program"], [execute, copy.deepcopy(execute)])

    # `gremlin_leader.slash`: one 16 -> Stab 6x3.
    slash = actions["gremlin_leader.slash"]["Program"]["Root"]
    assert slash["kind"] == "node.dealDamage"
    slash["value"]["Amount"]["value"]["Value"] = 6
    rebuild(actions["gremlin_leader.slash"]["Program"], [copy.deepcopy(slash) for _ in range(3)])

    # `darkling.chomp`: one 11 -> two hits of 8.
    chomp = actions["darkling.chomp"]["Program"]["Root"]
    assert chomp["kind"] == "node.dealDamage"
    chomp["value"]["Amount"]["value"]["Value"] = 8
    rebuild(actions["darkling.chomp"]["Program"], [chomp, copy.deepcopy(chomp)])

    # `sentry.bolt`: 10 damage -> add 2 Dazed into the discard pile.
    bolt = {
        "kind": "node.createCardInstance",
        "value": {
            "CardDefinitionId": {"value": "dazed"},
            "Count": {"kind": "const", "value": {"Value": 2}},
            "TargetSelector": {
                "kind": "sel.eventTarget",
                "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"},
            },
            "ToZone": "DiscardPile",
            "ResultKey": None,
        },
    }
    actions["sentry.bolt"]["Program"]["Root"] = bolt

    # ---------------------------------------------------------------- their ascension numbers
    PLAN = [
        # action id, threshold, mutation on a fresh copy of the (now correct) base
        ("spiker.cut", 2, lambda r: set_const_damage(r, 7, 9)),
        ("the_champ.heavy_slash", 4, lambda r: set_const_damage(r, 16, 18)),
        ("chosen.poke", 2, lambda r: [n["value"]["Amount"]["value"].update({"Value": 6})
                                      for n in nodes(r, "node.dealDamage")]),
        ("darkling.chomp", 2, lambda r: [n["value"]["Amount"]["value"].update({"Value": 9})
                                         for n in nodes(r, "node.dealDamage")]),
        ("spire_growth.strategic", 2, lambda r: [n["value"]["Stacks"]["value"].update({"Value": 12})
                                                 for n in nodes(r, "node.applyStatus")]),
        ("sentry.bolt", 18, lambda r: [n["value"]["Count"]["value"].update({"Value": 3})
                                       for n in nodes(r, "node.createCardInstance")]),
    ]
    for action_id, threshold, mutate in PLAN:
        action = actions[action_id]
        assert "ProgramAsc" not in action, "already variant: " + action_id
        root = copy.deepcopy(action["Program"]["Root"])
        mutate(root)
        envelope = copy.deepcopy(action["Program"])
        envelope["Root"] = root
        action["ProgramAsc"] = envelope
        action["AscensionMin"] = threshold
        print("%-32s A%-2d" % (action_id, threshold))

    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("cards:", len(document["Cards"]), "| variants:",
          sum(1 for a in document["EnemyActions"] if "ProgramAsc" in a))


if __name__ == "__main__":
    main()
