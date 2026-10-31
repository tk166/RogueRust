"""§161.7 part 2: Combust's HP loss, and the two gate tables that pin the card set.

The inventory's card row for Combust says "lose 1 HP and deal 5(7) damage to ALL enemies" and its
flag column says `hp-loss-trigger`. The status's `TurnEnded` trigger only did the damage -- so the
card would have shipped with a description it does not honour. `sel.source` + `IgnoresBlock` is the
"lose HP" shape (unblocked damage to yourself), which the node vocabulary already has.
"""
import io
import json

PACKAGE = "tools/contentc/packages/sts/sts.roguedeck.json"
CHECK = "native/sts_content_check.py"

SELF = {
    "kind": "sel.source",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"},
}

LOSE_ONE_HP = {
    "kind": "node.dealDamage",
    "value": {
        "TargetSelector": SELF,
        # "Lose 1 HP" ignores block -- that IS the difference between losing HP and taking damage.
        "IgnoresBlock": True,
        "Amount": {"kind": "const", "value": {"Value": 1}},
        "ResultKey": None,
        "Element": None,
    },
}

NEW_CARDS = ["combust", "combust+", "inflame", "inflame+", "metallicize", "metallicize+"]


def main():
    doc = json.loads(io.open(PACKAGE, encoding="utf-8").read())
    for status in doc["Statuses"]:
        if status["Id"] != "standard.combust":
            continue
        root = status["Triggers"][0]["Program"]["Root"]
        assert root["kind"] == "node.sequence", root["kind"]
        children = root["value"]["Children"]
        assert len(children) == 1, len(children)
        root["value"]["Children"] = [LOSE_ONE_HP] + children
        break
    else:
        raise SystemExit("standard.combust not found")
    io.open(PACKAGE, "w", encoding="utf-8", newline="").write(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    )

    check = io.open(CHECK, encoding="utf-8").read()
    # metalicize now has a trigger; the gate's table is the machine-readable copy of the inventory
    old = '''                        # §147: "lose HP at the end of your turn" is a TurnEnded trigger.
                        "standard.constricted": ["TurnEnded"]}[sid]'''
    new = '''                        # §147: "lose HP at the end of your turn" is a TurnEnded trigger.
                        "standard.constricted": ["TurnEnded"],
                        # §161.7: Metallicize is a *power* -- "at the end of your turn, gain
                        # 3(4) Block". Its status had no trigger at all, i.e. `Heart of Iron`
                        # has been handing out a decorative buff since §158.
                        "standard.metallicize": ["TurnEnded"]}[sid]'''
    assert check.count(old) == 1, check.count(old)
    check = check.replace(old, new)
    io.open(CHECK, "w", encoding="utf-8", newline="").write(check)
    print("combust loses 1 HP; gate knows metallicize's trigger")


if __name__ == "__main__":
    main()
