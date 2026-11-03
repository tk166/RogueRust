"""§193 data: the three enemies whose damage the wiki calls a range get a spawn roll.

Sources (the two lines that say "chosen at the start of combat"):

    native/wiki_asc/louse.txt:28      N between (5-7;{{Asc|2|6-8}})
    native/wiki_asc/darkling.txt:32   N between (7-11;{{Asc|2|9-13}})

Shape written per enemy record:

    "Rolls": [{"Key": "roll.bite", "Min": 5, "Max": 7},
              {"Key": "roll.bite", "Min": 6, "Max": 8, "AscensionMin": 2}]

and the action reads it with the **reference's own** `combatantCounter` expression (no new node
kind). The `AscensionMin`-less entry is the base -- see `Content::spawn_rolls` for why `0` means
"always" here while it means "unfilled" for `ProgramAsc`.

`"Rolls": []` is added to **every** record (not just the three): the writer derives one opcode per
object *shape*, so a lone extra key would give those three records a private shape. Keeping one shape
is not cosmetic -- it is what makes `EnemySpec::rolls` a plain field read for 37/37 records.
"""
import copy
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

LOUSE_RANGE = [{"Key": "roll.bite", "Min": 5, "Max": 7},
               {"Key": "roll.bite", "Min": 6, "Max": 8, "AscensionMin": 2}]
DARKLING_RANGE = [{"Key": "roll.nip", "Min": 7, "Max": 11},
                  {"Key": "roll.nip", "Min": 9, "Max": 13, "AscensionMin": 2}]

# enemy record id -> (counter key, the label's range text, rolls)
PLAN = {
    "louse_red": ("roll.bite", "5-7", LOUSE_RANGE),
    "darkling": ("roll.nip", "7-11", DARKLING_RANGE),
}

# action id -> (enemy record id, the damage node to rewrite)
#
# ⚠️ `louse_green.bite` is **not** here on purpose. This content has `louse_green.*` actions but **no
# `louse_green` enemy record** -- nothing spawns it (`enc_louse` holds one red louse). Converting it
# to a counter read would put a "0 damage" landmine in a table entry that the ENEMY_DIFF harness
# happily runs (it synthesises `<prefix>.<action>` as "the enemy it belongs to"). It stays a const
# 6 -- the midpoint of the wiki's 5-7 -- and `sts_content_check.py` pins the two facts together:
# "this action reads a const" + "no record lists it". The day someone wires the green louse in, that
# second check goes red and forces a record with a roll.
ACTIONS = {
    "louse_red.bite": ("louse_red", "roll.bite"),
    "darkling.nip": ("darkling", "roll.nip"),
}


def counter_amount(key):
    return {
        "kind": "combatantCounter",
        "value": {
            "Selector": {
                "kind": "sel.source",
                "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"},
            },
            "CounterId": key,
        },
    }


def main():
    document = json.load(io.open(SRC, encoding="utf-8"))

    # ---------------------------------------------------------------- records
    records = {}
    for encounter in document["Encounters"]:
        for record in encounter["Enemies"]:
            records.setdefault(record["Id"], []).append(record)
    assert sorted(records) == sorted(
        set(records)), "duplicate record ids?"                # sanity on the collector itself
    for record_id in records:
        if "Rolls" in records[record_id][0]:
            raise SystemExit("already migrated: " + record_id)
    for record_id, group in records.items():
        for record in group:
            record["Rolls"] = copy.deepcopy(PLAN[record_id][2]) if record_id in PLAN else []
    print("37 records: `Rolls` added (%d with a range)" % len(PLAN))

    # ---------------------------------------------------------------- programs
    actions = {action["Id"]: action for action in document["EnemyActions"]}
    for action_id, (record_id, key) in ACTIONS.items():
        action = actions[action_id]
        root = action["Program"]["Root"]
        assert root["kind"] == "node.dealDamage", (action_id, root["kind"])
        amount = root["value"]["Amount"]
        assert amount["kind"] == "const", (action_id, amount["kind"])
        assert "ProgramAsc" not in action, "this action carries a tier -- the range lives in the record"
        root["value"]["Amount"] = counter_amount(key)
        assert record_id in records
        action["Intent"]["Label"] = action["Intent"]["Label"].replace(
            " %d damage" % amount["value"]["Value"],
            " %s damage" % PLAN[record_id][1])
        action["DescriptionKey"] = action["Intent"]["Label"]
        print("%-20s -> counter `%s`  (%s)" % (action_id, key, action["Intent"]["Label"]))

    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("wrote", SRC)


if __name__ == "__main__":
    main()
