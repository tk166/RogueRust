"""§192 data migration: `ProgramAsc` (envelope) + `AscensionMin` (int) -> a variant **list**.

    before   "ProgramAsc": {envelope}, "AscensionMin": 2
    after    "ProgramAsc": [{"AscensionMin": 2, "Program": {envelope}}]

Then the reason the list exists: `jaw_worm.bellow` gets its **second** tier. The wiki states three
numbers in one line (`native/wiki_asc/jaw_worm.txt:30`):

    Effect = Gains (3;{{Asc|2|4}};{{Asc|17|5}}) Strength. Gains (6;{{Asc|17|9}}) Block.

i.e. Strength 3 -> 4 at A2 -> **5** at A17, Block 6 -> 9 at A17. With one slot per action §190 could
only carry the A2 number; the A17 entry has to repeat the A2 change *and* add its own, because only
the single highest eligible variant is used.
"""
import copy
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"


def main():
    document = json.load(io.open(SRC, encoding="utf-8"))
    actions = document["EnemyActions"]

    migrated = 0
    for action in actions:
        if "ProgramAsc" not in action:
            assert "AscensionMin" not in action, "AscensionMin without ProgramAsc: " + action["Id"]
            continue
        assert "AscensionMin" in action, "ProgramAsc without AscensionMin: " + action["Id"]
        threshold = action.pop("AscensionMin")
        envelope = action.pop("ProgramAsc")
        # The envelope must be the *shape* `Program` has: a bare `Root` here fails one step later,
        # in `intent.rs`, with `Missing("Root")` (§187's mistake, still worth asserting).
        assert set(envelope) == set(action["Program"]), sorted(envelope)
        assert "Root" in envelope
        action["ProgramAsc"] = [{"AscensionMin": threshold, "Program": envelope}]
        migrated += 1
    print("migrated", migrated, "variants to the list shape")

    # ---- the second tier -------------------------------------------------------------------
    bellow = next(a for a in actions if a["Id"] == "jaw_worm.bellow")
    assert len(bellow["ProgramAsc"]) == 1, len(bellow["ProgramAsc"])
    assert bellow["ProgramAsc"][0]["AscensionMin"] == 2
    a17 = copy.deepcopy(bellow["ProgramAsc"][0]["Program"])
    children = a17["Root"]["value"]["Children"]
    assert a17["Root"]["kind"] == "node.sequence" and len(children) == 2, children
    strength, block = children
    assert strength["kind"] == "node.applyStatus", strength["kind"]
    assert strength["value"]["StatusDefinitionId"]["value"] == "standard.strength"
    assert strength["value"]["Stacks"]["value"]["Value"] == 4, "A2 left Strength at 4"
    assert block["kind"] == "node.gainBlock", block["kind"]
    assert block["value"]["Amount"]["value"]["Value"] == 6, "A17 sets the base Block, not A2's"

    # A17: Strength 4 -> 5 **and** Block 6 -> 9 (the wiki's third and second number).
    strength["value"]["Stacks"]["value"]["Value"] = 5
    block["value"]["Amount"]["value"]["Value"] = 9
    bellow["ProgramAsc"].append({"AscensionMin": 17, "Program": a17})
    print("jaw_worm.bellow: A2 (Str 4, Block 6) + A17 (Str 5, Block 9)")

    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("wrote", SRC)


if __name__ == "__main__":
    main()
